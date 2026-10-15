"""
blng_agent.py —— 基于 browser-use 的 BLNG 站点自动化 Agent
============================================================
用途: 为 Agent 提供 https://app.blng.ai/ 的浏览器自动化能力

设计要点:
  - LLM 仅作决策组件，状态与重试由外层控制（避免无限循环烧 token）
  - 全链路日志埋点 + 结构化结果输出（可观测性）
  - 分级降级: 截图存证 -> 重试 -> 失败快照，绝不静默失败
  - 复杂度: O(N * S)，N=步数, S=单步 LLM 推理开销；受 max_steps 硬约束

依赖: browser-use>=0.13.11, python-dotenv, playwright(隐式)
入口: python blng_agent.py "任务描述"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------
# 日志埋点: 控制台 + 文件双写
# --------------------------------------------------------------------
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / f"run_{RUN_TS}.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("blng.agent")

load_dotenv(Path(__file__).parent / ".env")

# --------------------------------------------------------------------
# 【关键】绕过系统代理对本地/CDP 的劫持
# 本机环境存在 HTTP_PROXY=http://127.0.0.1:58732，会把 127.0.0.1:9222
# 的 CDP 请求也代理转发，导致 502。必须显式排除 localhost 段。
# --------------------------------------------------------------------
_LOCAL_NO_PROXY = "localhost,127.0.0.1,::1,0.0.0.0"
for _k in ("NO_PROXY", "no_proxy"):
    _existing = os.environ.get(_k, "")
    os.environ[_k] = f"{_existing},{_LOCAL_NO_PROXY}" if _existing else _LOCAL_NO_PROXY
log.info("NO_PROXY 已设置: %s", os.environ["NO_PROXY"])


# --------------------------------------------------------------------
# 配置装载: 缺失即快速失败（fail-fast），不猜默认值
# --------------------------------------------------------------------
def load_config() -> dict:
    """读取并校验运行配置。复杂度 O(1)。"""
    cfg = {
        "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "base_url": os.getenv("OPENAI_BASE_URL", "").strip() or None,
        "model": os.getenv("BROWSER_USE_LLM_MODEL", "gpt-4o-mini").strip(),
        "cdp_url": os.getenv("BU_CDP_URL", "").strip() or None,
        "headless": os.getenv("BU_HEADLESS", "false").lower() == "true",
        "max_steps": int(os.getenv("BU_MAX_STEPS", "25")),
        "step_timeout": int(os.getenv("BU_STEP_TIMEOUT", "120")),
        "target_url": os.getenv("TARGET_URL", "https://app.blng.ai/").strip(),
    }
    if not cfg["api_key"] or cfg["api_key"].startswith("sk-your"):
        log.error("OPENAI_API_KEY 未配置或仍为占位符，请编辑 .env")
        raise SystemExit(2)
    log.info(
        "配置装载完成 | model=%s | base_url=%s | cdp=%s | headless=%s | max_steps=%d",
        cfg["model"], cfg["base_url"] or "(默认官方)", cfg["cdp_url"] or "(独立浏览器)",
        cfg["headless"], cfg["max_steps"],
    )
    return cfg


# --------------------------------------------------------------------
# 构建 LLM 客户端: 支持 OpenAI 兼容网关（如 ai.zlskcn.com）
# --------------------------------------------------------------------
def build_llm(cfg: dict):
    """按 base_url 是否配置，选择通用 ChatOpenAI 通道。复杂度 O(1)。"""
    from browser_use import ChatOpenAI

    kwargs = {"model": cfg["model"], "api_key": cfg["api_key"]}
    if cfg["base_url"]:
        # 兼容网关必须显式传 base_url
        kwargs["base_url"] = cfg["base_url"]
    log.info("LLM 客户端初始化 | model=%s base_url=%s", cfg["model"], cfg["base_url"])
    return ChatOpenAI(**kwargs)


def build_browser(cfg: dict):
    """构建 Browser。复杂度 O(1)。"""
    from browser_use import Browser

    if cfg["cdp_url"]:
        log.info("接入已有浏览器 CDP: %s", cfg["cdp_url"])
        return Browser(cdp_url=cfg["cdp_url"], headless=cfg["headless"])
    log.info("使用 browser-use 独立浏览器实例 (headless=%s)", cfg["headless"])
    return Browser(headless=cfg["headless"])


# --------------------------------------------------------------------
# 主执行逻辑
# --------------------------------------------------------------------
async def run_task(task: str) -> dict:
    """执行单个任务，返回结构化结果。"""
    from browser_use import Agent

    cfg = load_config()
    result: dict = {
        "task": task,
        "target_url": cfg["target_url"],
        "started_at": datetime.now().isoformat(),
        "success": False,
        "steps": 0,
        "final_result": None,
        "error": None,
        "duration_sec": None,
    }
    t0 = time.time()

    try:
        llm = build_llm(cfg)
        browser = build_browser(cfg)

        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
        )
        log.info("Agent 启动 | task=%r", task)

        history = await asyncio.wait_for(agent.run(), timeout=cfg["step_timeout"] * cfg["max_steps"])

        steps = 0
        try:
            steps = history.number_of_steps()
        except Exception:  # 版本差异兜底
            steps = len(getattr(history, "history", []) or [])

        result.update(
            success=True,
            steps=steps,
            final_result=history.final_result(),
        )
        log.info("Agent 完成 | steps=%d | result=%s", steps, result["final_result"])

    except asyncio.TimeoutError:
        result["error"] = f"总执行超时 (> {cfg['step_timeout'] * cfg['max_steps']}s)"
        log.error(result["error"])
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        log.exception("Agent 执行失败")
    finally:
        result["duration_sec"] = round(time.time() - t0, 2)

    return result


def main() -> int:
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = (
            "打开 https://app.blng.ai/ ，报告页面标题、登录方式选项，"
            "以及页面上可见的主要文案。不要尝试登录。"
        )

    log.info("=" * 60)
    log.info("BLNG Agent 启动 | run=%s", RUN_TS)
    log.info("任务: %s", task)

    result = asyncio.run(run_task(task))

    # 结果落盘 + 控制台输出
    out = LOG_DIR / f"result_{RUN_TS}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("=" * 60)
    log.info("结果已写入 %s", out)

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
