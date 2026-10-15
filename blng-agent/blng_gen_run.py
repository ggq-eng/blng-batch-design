"""
blng_gen_run.py —— 完整生成流程（建项目 -> 填提示词 -> 提交 -> 等结果 -> 下载）
================================================================================
单次调用完成端到端生成。

复杂度: 轮询等待 O(P)，P 受 timeout 约束；免费账号实测 30-120s。
"""

from __future__ import annotations

import asyncio
import base64
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
log = logging.getLogger("blng.run")

OUT_DIR = Path(__file__).parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)

RATIO = {"square": "Square", "landscape": "Landscape", "portrait": "Portrait"}
RES = {"hd": "HD", "2k": "2K", "4k": "4K"}


async def click(c, sid, pattern: str) -> str:
    js = """
    (() => {const re=new RegExp(%s,'i');
      const b=[...document.querySelectorAll('button')].find(x=>re.test(x.innerText.trim()));
      if(!b) return 'not-found'; if(b.disabled) return 'disabled';
      b.click(); return 'clicked';})()
    """ % json.dumps(pattern)
    return await c.eval(js, sid)


async def fill(c, sid, selector: str, value: str) -> str:
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


async def press_enter(c, sid, selector: str) -> None:
    js = """
    (() => {const el=document.querySelector(%s); if(!el) return;
      ['keydown','keypress','keyup'].forEach(t=>{
        el.dispatchEvent(new KeyboardEvent(t,{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
      });})()
    """ % json.dumps(selector)
    await c.eval(js, sid)


async def run(prompt: str, ratio="landscape", res="hd", timeout=300, reuse_url: str | None = None) -> dict:
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}

    c = await _connect()
    out: dict = {"success": False, "prompt": prompt}
    try:
        ok, url, sid = await try_restore(c)
        if not ok:
            return {"success": False, "error": "登录态失效"}
        await c.call("Page.enable", {}, session=sid)

        # --- 建新项目 ---
        if not reuse_url:
            log.info("新建项目 (ratio=%s res=%s)...", ratio, res)
            await click(c, sid, r"^new design$")
            await asyncio.sleep(5)
            await click(c, sid, r"^%s" % RATIO.get(ratio, "Landscape"))
            await asyncio.sleep(1)
            await click(c, sid, r"^%s$" % RES.get(res, "HD"))
            await asyncio.sleep(1)
            await click(c, sid, r"^start$")
            await asyncio.sleep(12)  # 等编辑器完全就绪
        else:
            log.info("复用项目 %s", reuse_url)
            await c.call("Page.navigate", {"url": reuse_url}, session=sid)
            await asyncio.sleep(10)

        # --- 填提示词 ---
        sel = "textarea"
        for attempt in range(3):
            exists = await c.eval("!!document.querySelector('textarea')", sid)
            if exists:
                break
            log.info("等编辑器… (%d)", attempt + 1)
            await asyncio.sleep(6)

        r = await fill(c, sid, sel, prompt)
        log.info("填提示词: %s", r)
        await asyncio.sleep(2)
        await c.shot(SHOT_DIR / f"gen_before_{time.strftime('%Y%m%d_%H%M%S')}.png", sid)

        # --- 提交 ---
        await press_enter(c, sid, sel)
        await asyncio.sleep(2)
        sub = await click(c, sid, r"^(generate|send|submit)$")
        log.info("提交: %s", sub)
        if sub in ("not-found", "disabled"):
            # 尝试查找发送图标按钮
            alt = await c.eval("""(() => {
                const bs=[...document.querySelectorAll('button')].filter(b=>!b.innerText.trim());
                if(!bs.length) return 'no-icon-btn';
                bs[bs.length-1].click(); return 'clicked-icon';})()""", sid)
            log.info("备用提交: %s", alt)

        # --- 轮询等待 ---
        log.info("等待生成 (timeout=%ds)...", timeout)
        t0 = time.time()
        last = ""
        while time.time() - t0 < timeout:
            await asyncio.sleep(6)
            st = await c.eval("""JSON.stringify({
                text: (document.body.innerText||'').slice(0,600),
                imgs: [...document.querySelectorAll('img')].map(i=>i.src).filter(s=>s && !s.startsWith('data:')).slice(0,6),
                progress: (document.body.innerText.match(/(\\d{1,3})%/)||[])[0]||null
            })""", sid)
            info = json.loads(st) if st else {}
            txt = info.get("text", "")[:120].replace("\n", " ")
            if txt != last:
                log.info("  状态: %s", txt)
                last = txt
            if info.get("progress"):
                log.info("  进度: %s", info["progress"])

        ts = time.strftime("%Y%m%d_%H%M%S")
        final = await c.eval("""JSON.stringify({
            url: location.href,
            text: (document.body.innerText||'').slice(0,1500),
            imgs: [...document.querySelectorAll('img')].map(i=>i.src).filter(s=>s && !s.startsWith('data:')).slice(0,10)
        })""", sid)
        out["final"] = json.loads(final) if final else {}
        shot = SHOT_DIR / f"gen_after_{ts}.png"
        await c.shot(shot, sid)
        out["screenshot"] = str(shot)

        # 抓大图并下载
        imgs = out["final"].get("imgs", [])
        big = [u for u in imgs if any(k in u for k in ("cdn", "s3", "assets", "media", "generate", "output"))]
        out["candidate_images"] = big or imgs
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
    opts = {a.lstrip("-").split("=")[0]: a.split("=")[1] for a in sys.argv[1:] if "=" in a and a.startswith("--")}
    prompt = args[0] if args else "a basketball court facing the open sea at golden hour, cinematic, photorealistic"
    r = asyncio.run(run(prompt, opts.get("ratio", "landscape"), opts.get("res", "hd"),
                        int(opts.get("timeout", "300")), opts.get("project")))
    print(json.dumps(r, ensure_ascii=False, indent=2))
