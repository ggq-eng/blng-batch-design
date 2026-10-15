"""
blng_tool.py —— BLNG 站点自动化工具（browser-use + Edge CDP）
================================================================
给 Agent 使用的浏览器自动化基座。已解决三大环境障碍:
  1. 无 Chrome / Chromium 下载失败  -> 复用本机 Edge
  2. 系统代理劫持本地请求 (502)      -> NO_PROXY 排除 localhost
  3. 沙箱回收子进程                  -> 同会话内启动+执行

对外能力:
  - goto(url)            导航并等待渲染
  - get_text(sel)        取元素文本
  - eval_js(expr)        执行任意 JS
  - screenshot(path)     截图存证
  - snapshot()           结构化快照（标题/URL/可见文本）

复杂度: 单次操作 O(1)；新建 tab 含渲染等待，约 3-8s。
用法: python blng_tool.py <command> [args...]
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# ---- 代理排除（必须在一切网络调用前）----
_LOOPBACK = "localhost,127.0.0.1,::1,0.0.0.0"
for _k in ("NO_PROXY", "no_proxy"):
    _v = os.environ.get(_k, "")
    os.environ[_k] = f"{_v},{_LOOPBACK}" if _v else _LOOPBACK

import websockets  # noqa: E402

# --------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------
BASE = Path(__file__).parent
# Edge 可执行文件（可用环境变量 BLNG_EDGE 覆盖）
EDGE = os.environ.get("BLNG_EDGE") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
# 浏览器配置目录：务必落在本 skill 目录内，保证跨机器可移植
PROFILE = str(BASE / ".edge-profile")
CDP_HTTP = "http://127.0.0.1:9222"
SHOT_DIR = BASE / "screenshots"
SHOT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("blng.tool")


# --------------------------------------------------------------------
# Edge 生命周期管理
# --------------------------------------------------------------------
def is_cdp_alive(timeout: float = 3.0) -> bool:
    """检测 CDP 端口是否已就绪。复杂度 O(1)。"""
    try:
        req = urllib.request.Request(f"{CDP_HTTP}/json/version")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def ensure_edge(wait: int = 25) -> bool:
    """
    幂等启动 Edge CDP。已存活则直接返回。
    注意: 必须在同一进程/会话内调用并保持引用，否则子进程会被回收。
    """
    if is_cdp_alive():
        log.info("Edge CDP 已存活，复用")
        return True

    log.info("启动 Edge (CDP :9222) ...")
    try:
        subprocess.Popen(
            [EDGE, "--remote-debugging-port=9222", f"--user-data-dir={PROFILE}",
             "--no-first-run", "--no-default-browser-check",
             "--disable-features=msEdgeSidebarV2", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log.error("找不到 msedge.exe: %s", EDGE)
        return False

    for i in range(wait):
        if is_cdp_alive():
            log.info("Edge CDP 就绪，耗时 %ds", i + 1)
            return True
        time.sleep(1)
    log.error("Edge CDP 启动超时")
    return False


# --------------------------------------------------------------------
# CDP 客户端（轻量封装，不依赖 browser-use 内部实现）
# --------------------------------------------------------------------
class CDP:
    """极简 Chrome DevTools Protocol 客户端。"""

    def __init__(self, ws):
        self.ws = ws
        self._mid = 0

    async def call(self, method: str, params: dict | None = None, session: str | None = None):
        self._mid += 1
        mid = self._mid
        payload = {"id": mid, "method": method, "params": params or {}}
        if session:
            payload["sessionId"] = session
        await self.ws.send(json.dumps(payload))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} 失败: {msg['error']}")
                return msg.get("result", {})

    async def new_page(self, url: str, settle: float = 6.0) -> str:
        """新建标签页并导航，返回 sessionId。"""
        r = await self.call("Target.createTarget", {"url": url})
        tid = r["targetId"]
        s = await self.call("Target.attachToTarget", {"targetId": tid, "flatten": True})
        sid = s["sessionId"]
        await asyncio.sleep(settle)  # 等 SPA 渲染
        return sid

    async def eval(self, expr: str, sid: str):
        r = await self.call("Runtime.evaluate",
                            {"expression": expr, "returnByValue": True, "awaitPromise": True},
                            session=sid)
        return r.get("result", {}).get("value")

    async def shot(self, path: Path, sid: str):
        r = await self.call("Page.captureScreenshot", {"format": "png"}, session=sid)
        path.write_bytes(base64.b64decode(r["data"]))
        return path


async def _connect():
    info = json.load(urllib.request.urlopen(f"{CDP_HTTP}/json/version", timeout=8))
    ws = await websockets.connect(info["webSocketDebuggerUrl"], max_size=80 * 1024 * 1024)
    return CDP(ws)


# --------------------------------------------------------------------
# 对外 API（供 Agent 调用）
# --------------------------------------------------------------------
async def snapshot(url: str = "https://app.blng.ai/", shot: bool = True) -> dict:
    """
    导航到 URL 并返回结构化快照。
    返回: {url, title, text, screenshot}
    """
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}
    client = await _connect()
    try:
        sid = await client.new_page(url)
        await client.call("Page.enable", {}, session=sid)
        data = await client.eval(
            "JSON.stringify({t:document.title,u:location.href,"
            "x:(document.body&&document.body.innerText||'').slice(0,3000)})", sid)
        info = json.loads(data) if data else {}
        out = {"success": True, "url": info.get("u"), "title": info.get("t"), "text": info.get("x")}
        if shot:
            ts = time.strftime("%Y%m%d_%H%M%S")
            p = SHOT_DIR / f"snap_{ts}.png"
            await client.shot(p, sid)
            out["screenshot"] = str(p)
        return out
    except Exception as e:
        log.exception("snapshot 失败")
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await client.ws.close()


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    url = sys.argv[2] if len(sys.argv) > 2 else "https://app.blng.ai/"

    if cmd == "start":
        ok = ensure_edge()
        print("CDP 就绪" if ok else "启动失败")
        return 0 if ok else 1

    if cmd == "snapshot":
        res = asyncio.run(snapshot(url))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("success") else 1

    if cmd == "doctor":
        alive = is_cdp_alive()
        print(json.dumps({
            "edge_path_exists": Path(EDGE).exists(),
            "cdp_alive": alive,
            "cdp_http": CDP_HTTP,
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"未知命令: {cmd}. 可用: start | snapshot | doctor")
    return 2


if __name__ == "__main__":
    sys.exit(main())
