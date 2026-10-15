"""
blng_generate.py —— BLNG 图片生成自动化
==========================================
流程:
  1. 恢复登录态 (Cognito refreshToken)
  2. 点 New Design -> 选画布尺寸 (Preset/Resolution/Aspect) -> Start
  3. 在编辑器输入提示词 -> 提交生成
  4. 轮询等待结果 -> 抓取图片 URL 并下载

复杂度:
  - 建项目 O(1)
  - 生成等待 O(P)，P=生成轮询次数（受 timeout 约束）
  - 免费账号单次生成约 30-120s

用法:
  python blng_generate.py "a basketball court facing the sea, sunset, photorealistic"
  python blng_generate.py "<prompt>" --ratio landscape --res 2k
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from blng_tool import ensure_edge, _connect, SHOT_DIR
from blng_auto import try_restore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("blng.gen")

OUT_DIR = Path(__file__).parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)

RATIO = {"square": "Square", "landscape": "Landscape", "portrait": "Portrait"}
RES = {"hd": "HD", "2k": "2K", "4k": "4K"}


async def _click_btn(c, sid, pattern: str) -> str:
    """按文本正则点击按钮。"""
    js = """
    (() => {
      const re = new RegExp(%s, 'i');
      const b = [...document.querySelectorAll('button')].find(x => re.test(x.innerText.trim()));
      if (!b) return 'not-found';
      if (b.disabled) return 'disabled';
      b.click(); return 'clicked';
    })()
    """ % json.dumps(pattern)
    return await c.eval(js, sid)


async def _set_react_input(c, sid, selector: str, value: str) -> str:
    js = """
    (() => {
      const el = document.querySelector(%s);
      if (!el) return 'not-found';
      el.focus();
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, %s);
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return el.value === %s ? 'ok' : 'mismatch';
    })()
    """ % (json.dumps(selector), json.dumps(value), json.dumps(value))
    return await c.eval(js, sid)


async def generate(prompt: str, ratio: str = "landscape", res: str = "hd",
                   timeout: int = 240) -> dict:
    """端到端图片生成。"""
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}

    c = await _connect()
    out: dict = {"success": False, "prompt": prompt, "ratio": ratio, "res": res}
    try:
        ok, url, sid = await try_restore(c)
        if not ok:
            return {"success": False, "error": "登录态失效，请先运行 blng_auto.py ensure"}
        await c.call("Page.enable", {}, session=sid)

        # --- Step 1: 打开 New Design ---
        log.info("打开 New Design...")
        log.info("  %s", await _click_btn(c, sid, r"^new design$"))
        await asyncio.sleep(5)

        # --- Step 2: 设置画布 ---
        log.info("设置画布: ratio=%s res=%s", ratio, res)
        r1 = await _click_btn(c, sid, r"^%s" % RATIO.get(ratio, "Landscape"))
        log.info("  比例: %s", r1)
        await asyncio.sleep(1)
        r2 = await _click_btn(c, sid, r"^%s$" % RES.get(res, "HD"))
        log.info("  分辨率: %s", r2)
        await asyncio.sleep(1)

        # --- Step 3: Start ---
        r3 = await _click_btn(c, sid, r"^start$")
        log.info("  开始: %s", r3)
        await asyncio.sleep(8)

        st = await c.eval("""JSON.stringify({
            url: location.href,
            textareas: [...document.querySelectorAll('textarea')].map(t=>({ph:t.placeholder})),
            editables: document.querySelectorAll('[contenteditable=true]').length,
            inputs: [...document.querySelectorAll('input')].map(i=>({t:i.type,ph:i.placeholder})),
            buttons: [...document.querySelectorAll('button')].map(b=>b.innerText.trim()).filter(Boolean).slice(0,25)
        })""", sid)
        editor = json.loads(st) if st else {}
        out["editor_probe"] = editor
        log.info("编辑器状态: url=%s textareas=%d", editor.get("url"), len(editor.get("textareas", [])))

        ts = time.strftime("%Y%m%d_%H%M%S")
        await c.shot(SHOT_DIR / f"editor_{ts}.png", sid)

        out["note"] = "已进入编辑器；提示词提交逻辑见下一步探测结果"
        out["success"] = True
        return out

    except Exception as e:
        log.exception("生成异常")
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    finally:
        await c.ws.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a.split("=")[0].lstrip("-"): a.split("=")[1] for a in sys.argv[1:] if "=" in a and a.startswith("--")}
    prompt = args[0] if args else "a basketball court facing the open sea at golden hour, cinematic, photorealistic"
    r = asyncio.run(generate(prompt, opts.get("ratio", "landscape"), opts.get("res", "hd")))
    print(json.dumps(r, ensure_ascii=False, indent=2))
