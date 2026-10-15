"""
diamond_pipeline.py —— 钻石设计图批量生成与归档管线
================================================================
替代人工在 BLNG 网站上的重复操作。

流程:
  1. 逐条读取提示词
  2. 建项目 -> 写入提示词 -> 提交 -> 等待生成（失败/超时重试，最多 2 次）
  3. 下载成品图到本地（canvas 导出，绕开 blob: 限制）
  4. 按「款式名_编号.png」归档到 diamond/YYYY-MM-DD/

可靠性设计:
  - 每条提示词独立 try/except，单条失败不影响后续
  - 重试上限 MAX_RETRY=2（共 3 次尝试）
  - 失败原因结构化记录（超时/无图/页面异常）
  - 生成完成判据: 聊天区出现 "N image created" 或 "Created ... in Ns"
  - 全量结果落盘 manifest.json，支持断点续跑（skip 已完成）

复杂度:
  - 单条: O(P) 轮询，P 受 timeout 约束（实测 30-90s 出图）
  - 整体: O(N * P)，N=提示词条数，串行执行避免并发触发风控

用法:
  python diamond_pipeline.py                    # 跑内置钻石提示词
  python diamond_pipeline.py --file prompts.json
  python diamond_pipeline.py --resume           # 跳过已成功项
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from blng_tool import ensure_edge, _connect, SHOT_DIR
from blng_auto import try_restore

# --------------------------------------------------------------------
# 日志
# --------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("diamond")

BASE = Path(__file__).parent
DATE_DIR = BASE / "diamond" / datetime.now().strftime("%Y-%m-%d")
DATE_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST = DATE_DIR / "manifest.json"

MAX_RETRY = 2          # 额外重试次数（总尝试 = MAX_RETRY + 1）
GEN_TIMEOUT = 180      # 单次生成等待上限（秒）
POLL_INTERVAL = 5      # 轮询间隔
RATIO = "Square"
RES = "2K"
ORIGIN = "https://app.blng.ai"

# --------------------------------------------------------------------
# 内置钻石设计提示词（覆盖主要品类）
# --------------------------------------------------------------------
DEFAULT_PROMPTS = [
    {
        "name": "solitaire_ring",
        "prompt": "a classic solitaire diamond engagement ring with a brilliant round-cut center stone, platinum band, luxury jewelry photography, soft studio lighting, macro detail, white background",
    },
    {
        "name": "halo_ring",
        "prompt": "an elegant halo diamond ring with a cushion-cut center stone surrounded by pave diamonds, rose gold band, luxury jewelry photography, shallow depth of field",
    },
    {
        "name": "diamond_necklace",
        "prompt": "a delicate diamond pendant necklace with a pear-shaped brilliant diamond on a fine white gold chain, luxury jewelry photography, soft reflections, dark velvet background",
    },
    {
        "name": "diamond_earrings",
        "prompt": "a pair of diamond drop earrings with marquise and round brilliant stones, art deco style, luxury jewelry photography, dramatic side lighting",
    },
    {
        "name": "tennis_bracelet",
        "prompt": "a diamond tennis bracelet with a continuous line of round brilliant-cut diamonds in white gold, luxury jewelry photography, elegant composition, soft gradient background",
    },
    {
        "name": "eternity_band",
        "prompt": "a diamond eternity band ring fully set with emerald-cut diamonds, channel setting, yellow gold, luxury jewelry photography, crisp macro detail, neutral background",
    },
]


# --------------------------------------------------------------------
# 页面操作原语
# --------------------------------------------------------------------
async def click_btn(c, sid, pattern: str) -> str:
    js = """
    (() => {const re=new RegExp(%s,'i');
      const b=[...document.querySelectorAll('button')].find(x=>re.test(x.innerText.trim()));
      if(!b) return 'not-found'; if(b.disabled) return 'disabled';
      b.click(); return 'clicked';})()
    """ % json.dumps(pattern)
    return await c.eval(js, sid)


async def fill_react(c, sid, selector: str, value: str) -> str:
    js = """
    (() => {const el=document.querySelector(%s); if(!el) return 'not-found';
      el.focus();
      const proto = el.tagName==='TEXTAREA' ? window.HTMLTextAreaElement.prototype
                                             : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto,'value').set.call(el,%s);
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      return el.value===%s?'ok':'mismatch';})()
    """ % (json.dumps(selector), json.dumps(value), json.dumps(value))
    return await c.eval(js, sid)


async def submit_prompt(c, sid) -> str:
    """点击最后一个无文本图标按钮（实测为发送键）。"""
    js = """(() => {
      const bs=[...document.querySelectorAll('button')].filter(b=>!b.innerText.trim());
      if(!bs.length) return 'no-icon-btn';
      bs[bs.length-1].click(); return 'clicked';})()"""
    return await c.eval(js, sid)


async def export_latest_image(c, sid, dest: Path) -> dict:
    """
    导出页面上最新的大图到本地。
    用 canvas.drawImage -> toDataURL 绕开 blob: 限制。
    """
    js = """(async () => {
        const imgs=[...document.querySelectorAll('img')]
            .filter(i=>i.naturalWidth>=512 && i.naturalHeight>=512);
        if(!imgs.length) return JSON.stringify({err:'no-large-img'});
        const im=imgs[imgs.length-1];
        try {
            const cv=document.createElement('canvas');
            cv.width=im.naturalWidth; cv.height=im.naturalHeight;
            cv.getContext('2d').drawImage(im,0,0);
            return JSON.stringify({w:im.naturalWidth,h:im.naturalHeight,
                data:cv.toDataURL('image/png').split(',')[1]});
        } catch(e) { return JSON.stringify({err:String(e)}); }
    })()"""
    raw = await c.eval(js, sid)
    d = json.loads(raw) if raw else {}
    if not d.get("data"):
        return {"ok": False, "reason": d.get("err", "empty-image-data")}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(base64.b64decode(d["data"]))
    return {"ok": True, "path": str(dest), "width": d["w"], "height": d["h"],
            "size_mb": round(dest.stat().st_size / 1024 / 1024, 2)}


async def new_project(c, sid) -> str:
    """
    新建画布项目。
    关键修复: 必须先确保处于 dashboard，否则在编辑器页点 New Design 会失效，
    导致后续 textarea 找不到（历史 bug: fill-not-found）。
    """
    # 1) 回到 dashboard（若已在编辑器/其他页）
    here = await c.eval("location.href", sid)
    if "dashboard" not in str(here):
        log.info("    (返回 dashboard)")
        await c.call("Page.navigate", {"url": f"{ORIGIN}/dashboard"}, session=sid)
        await asyncio.sleep(8)

    # 2) 等 New Design 按钮出现
    for _ in range(6):
        has = await c.eval(
            "!![...document.querySelectorAll('button')].find(b=>/new design/i.test(b.innerText))", sid)
        if has:
            break
        await asyncio.sleep(3)

    await click_btn(c, sid, r"^new design$")
    await asyncio.sleep(5)
    await click_btn(c, sid, r"^%s" % RATIO)
    await asyncio.sleep(1)
    await click_btn(c, sid, r"^%s$" % RES)
    await asyncio.sleep(1)
    await click_btn(c, sid, r"^start$")
    await asyncio.sleep(14)

    # 3) 确认 textarea 就绪
    for _ in range(8):
        if await c.eval("!!document.querySelector('textarea')", sid):
            return "ready"
        await asyncio.sleep(3)
    return "textarea-not-ready"


async def wait_generated(c, sid, timeout: int) -> tuple[bool, str]:
    """轮询等待生成完成。返回 (是否成功, 状态描述)。"""
    t0 = time.time()
    last_note = ""
    while time.time() - t0 < timeout:
        await asyncio.sleep(POLL_INTERVAL)
        txt = await c.eval("(document.body.innerText||'').slice(0,1500)", sid) or ""
        if re.search(r"\d+\s+image[s]?\s+created|Created\s+\w[\w\s]*\s+in\s+\d+\s*second", txt, re.I):
            return True, "generated"
        if re.search(r"(failed|error|something went wrong|try again)", txt, re.I):
            return False, "page-error"
        m = re.search(r"Thought for \d+", txt)
        if m:
            last_note = m.group(0)
    return False, f"timeout after {timeout}s ({last_note})"


# --------------------------------------------------------------------
# 单条处理
# --------------------------------------------------------------------
async def process_one(c, item: dict, idx: int, total: int) -> dict:
    """处理一条提示词，含重试。"""
    name = item["name"]
    prompt = item["prompt"]
    rec: dict = {"index": idx, "name": name, "prompt": prompt,
                 "attempts": [], "success": False, "file": None}

    for attempt in range(1, MAX_RETRY + 2):
        log.info("[%d/%d] %s — 第 %d 次尝试", idx, total, name, attempt)
        t0 = time.time()
        detail = {"attempt": attempt, "result": None, "reason": None, "duration": None}
        try:
            ok, url, sid = await try_restore(c)
            if not ok:
                detail.update(result="fail", reason="session-invalid")
                rec["attempts"].append(detail)
                continue
            await c.call("Page.enable", {}, session=sid)

            st = await new_project(c, sid)
            if st != "ready":
                detail.update(result="fail", reason=st)
                rec["attempts"].append(detail)
                continue
            r = await fill_react(c, sid, "textarea", prompt)
            if r != "ok":
                detail.update(result="fail", reason=f"fill-{r}")
                rec["attempts"].append(detail)
                continue
            await asyncio.sleep(2)
            await submit_prompt(c, sid)
            await asyncio.sleep(4)

            gen_ok, note = await wait_generated(c, sid, GEN_TIMEOUT)
            if not gen_ok:
                detail.update(result="fail", reason=note)
                rec["attempts"].append(detail)
                continue

            dest = DATE_DIR / f"{name}_{idx:02d}.png"
            exp = await export_latest_image(c, sid, dest)
            if not exp.get("ok"):
                detail.update(result="fail", reason=f"export-{exp.get('reason')}")
                rec["attempts"].append(detail)
                continue

            detail.update(result="ok", reason=None)
            rec["attempts"].append(detail)
            rec.update(success=True, file=exp["path"],
                       width=exp["width"], height=exp["height"], size_mb=exp["size_mb"])
            log.info("  ✓ %s -> %s (%dx%d, %s MB)", name, Path(exp["path"]).name,
                     exp["width"], exp["height"], exp["size_mb"])
            return rec

        except Exception as e:
            detail.update(result="fail", reason=f"{type(e).__name__}: {e}")
            rec["attempts"].append(detail)
            log.warning("  ✗ 异常: %s", e)
        finally:
            detail["duration"] = round(time.time() - t0, 1)

    log.error("  ✗ %s 最终失败，原因: %s", name,
              rec["attempts"][-1]["reason"] if rec["attempts"] else "unknown")
    return rec


# --------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------
async def run_pipeline(items: list[dict], resume: bool = False) -> dict:
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}

    # 断点续跑：读取已成功的 manifest
    done: dict[str, dict] = {}
    if resume and MANIFEST.exists():
        try:
            prev = json.loads(MANIFEST.read_text(encoding="utf-8"))
            done = {r["name"]: r for r in prev.get("results", []) if r.get("success")}
            log.info("断点续跑：已有 %d 条成功记录", len(done))
        except Exception as e:
            log.warning("读取 manifest 失败: %s", e)

    c = await _connect()
    report: dict = {
        "started_at": datetime.now().isoformat(),
        "archive_dir": str(DATE_DIR),
        "ratio": RATIO, "res": RES,
        "total": len(items),
        "results": [],
    }
    try:
        for i, item in enumerate(items, 1):
            if resume and item["name"] in done:
                log.info("[%d/%d] %s — 已存在，跳过", i, len(items), item["name"])
                report["results"].append(done[item["name"]])
                continue
            rec = await process_one(c, item, i, len(items))
            report["results"].append(rec)
            # 每条后落盘，防中断丢失
            report["finished_at"] = datetime.now().isoformat()
            report["succeeded"] = sum(1 for r in report["results"] if r.get("success"))
            report["failed"] = sum(1 for r in report["results"] if not r.get("success"))
            MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await c.ws.close()

    report["finished_at"] = datetime.now().isoformat()
    report["succeeded"] = sum(1 for r in report["results"] if r.get("success"))
    report["failed"] = sum(1 for r in report["results"] if not r.get("success"))
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="钻石设计图批量生成与归档")
    ap.add_argument("--file", help="提示词 JSON 文件（[{name, prompt}, ...]）")
    ap.add_argument("--resume", action="store_true", help="跳过已成功项")
    args = ap.parse_args()

    if args.file:
        items = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        items = DEFAULT_PROMPTS

    log.info("=" * 64)
    log.info("钻石设计图管线启动 | 共 %d 条 | 归档 -> %s", len(items), DATE_DIR)
    report = asyncio.run(run_pipeline(items, args.resume))

    print("\n" + "=" * 64)
    print(f"成功 {report.get('succeeded', 0)} / {report.get('total', 0)}")
    for r in report.get("results", []):
        mark = "✓" if r.get("success") else "✗"
        line = f"  {mark} {r['name']}"
        if r.get("success"):
            line += f" -> {Path(r['file']).name}"
        else:
            line += f" | 原因: {r['attempts'][-1]['reason'] if r.get('attempts') else 'unknown'}"
        print(line)
    print(f"\n归档目录: {DATE_DIR}")
    print(f"清单文件: {MANIFEST}")
    print("=" * 64)
    return 0 if report.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
