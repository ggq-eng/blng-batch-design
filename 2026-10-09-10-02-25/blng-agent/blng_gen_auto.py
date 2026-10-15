"""
blng_gen_auto.py —— 一键端到端图片生成（建项目 → 提交 → 等结果 → 下载）
=========================================================================
一条命令完成全流程，无需手动操作。

关键实现:
  - 建项目: New Design → 比例 → 分辨率 → Start
  - 提示词: 用原生 setter 触发 React onChange 写入 textarea
  - 提交: 点击最后一个无文本图标按钮（实测为蓝色发送键）
  - 等结果: 轮询聊天区，检测 "Created scene in Ys" / "N image created"
  - 下载: 把聊天缩略图绘到 canvas 导出 dataURL（绕开 blob: 限制）

注意: 画布上的 "24%" 是缩放比例，不是进度！真正的完成信号在聊天区文案。

复杂度: 建项目 O(1)；生成等待 O(P)，实测 26s 出图，轮询上限受 timeout 约束。

用法:
  python blng_gen_auto.py "你的提示词"
  python blng_gen_auto.py "你的提示词" --ratio=landscape --res=2k --timeout=300
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
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
log = logging.getLogger("blng.genauto")

OUT_DIR = Path(__file__).parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)

RATIO = {"square": "Square", "landscape": "Landscape", "portrait": "Portrait"}
RES = {"hd": "HD", "2k": "2K", "4k": "4K"}


def _slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return s[:n] or "blng_output"


async def click_btn(c, sid, pattern: str) -> str:
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


async def submit(c, sid) -> str:
    """点击发送按钮：优先最后一个无文本图标按钮。"""
    js = """(() => {
      const bs=[...document.querySelectorAll('button')].filter(b=>!b.innerText.trim());
      if(!bs.length) return 'no-icon-btn';
      bs[bs.length-1].click();
      return 'clicked';})()"""
    return await c.eval(js, sid)


async def export_images(c, sid, slug: str) -> list[str]:
    """把页面上的成品图通过 canvas 导出为本地 PNG。"""
    js = """(async () => {
        const imgs=[...document.querySelectorAll('img')].filter(i=>i.naturalWidth>=512);
        const out=[];
        for (const im of imgs.slice(-3)) {
            try {
                const cv=document.createElement('canvas');
                cv.width=im.naturalWidth; cv.height=im.naturalHeight;
                cv.getContext('2d').drawImage(im,0,0);
                out.push({w:im.naturalWidth,h:im.naturalHeight,
                    data:cv.toDataURL('image/png').split(',')[1]});
            } catch(e) { out.push({err:String(e)}); }
        }
        return JSON.stringify(out);
    })()"""
    raw = await c.eval(js, sid)
    items = json.loads(raw) if raw else []
    saved = []
    for i, it in enumerate(items):
        if it.get("data"):
            p = OUT_DIR / f"{slug}_{i+1}_{it['w']}x{it['h']}.png"
            p.write_bytes(base64.b64decode(it["data"]))
            log.info("已保存 %s (%dx%d, %.1f MB)", p.name, it["w"], it["h"],
                     p.stat().st_size / 1024 / 1024)
            saved.append(str(p))
    return saved


async def run(prompt: str, ratio="landscape", res="hd", timeout=300) -> dict:
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}

    c = await _connect()
    out: dict = {"success": False, "prompt": prompt, "ratio": ratio, "res": res}
    t0 = time.time()
    try:
        ok, url, sid = await try_restore(c)
        if not ok:
            return {"success": False, "error": "登录态失效，先运行 blng_auto.py ensure"}
        await c.call("Page.enable", {}, session=sid)

        # 1) 建项目
        log.info("① 新建项目 ratio=%s res=%s", ratio, res)
        await click_btn(c, sid, r"^new design$")
        await asyncio.sleep(5)
        await click_btn(c, sid, r"^%s" % RATIO.get(ratio, "Landscape"))
        await asyncio.sleep(1)
        await click_btn(c, sid, r"^%s$" % RES.get(res, "HD"))
        await asyncio.sleep(1)
        await click_btn(c, sid, r"^start$")
        await asyncio.sleep(12)

        # 2) 填提示词
        for _ in range(4):
            if await c.eval("!!document.querySelector('textarea')", sid):
                break
            await asyncio.sleep(5)
        log.info("② 写入提示词: %s", await fill(c, sid, "textarea", prompt))
        await asyncio.sleep(2)

        # 3) 提交
        log.info("③ 提交: %s", await submit(c, sid))
        await asyncio.sleep(5)

        # 4) 轮询（真正的完成信号在聊天区）
        log.info("④ 等待生成...")
        done = False
        while time.time() - t0 < timeout:
            await asyncio.sleep(5)
            txt = await c.eval("(document.body.innerText||'').slice(0,1200)", sid) or ""
            if re.search(r"\d+\s+image[s]?\s+created|Created scene in", txt, re.I):
                log.info("   ✓ 生成完成")
                done = True
                break
            m = re.search(r"Thought for \d+", txt)
            if m:
                log.info("   %s", m.group(0))
        out["generated"] = done

        # 5) 导出
        slug = _slug(prompt)
        await asyncio.sleep(3)
        out["files"] = await export_images(c, sid, slug)

        ts = time.strftime("%Y%m%d_%H%M%S")
        shot = SHOT_DIR / f"done_{ts}.png"
        await c.shot(shot, sid)
        out["screenshot"] = str(shot)
        out["duration_sec"] = round(time.time() - t0, 1)
        out["success"] = bool(out["files"])
        out["project_url"] = await c.eval("location.href", sid)
        return out

    except Exception as e:
        log.exception("生成异常")
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    finally:
        await c.ws.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a.lstrip("-").split("=")[0]: a.split("=")[1]
            for a in sys.argv[1:] if "=" in a and a.startswith("--")}
    prompt = args[0] if args else "a basketball court facing the open sea at golden hour, cinematic, photorealistic"
    r = asyncio.run(run(prompt, opts.get("ratio", "landscape"),
                        opts.get("res", "hd"), int(opts.get("timeout", "300"))))
    print(json.dumps(r, ensure_ascii=False, indent=2))
