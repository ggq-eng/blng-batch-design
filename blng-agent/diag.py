"""诊断: 冷启动后 dashboard 的真实按钮/输入框状态。"""
import asyncio, json, sys, logging
import urllib.request
from pathlib import Path
from blng_tool import ensure_edge, _connect
from blng_auto import try_restore

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("diag")

async def main():
    if not ensure_edge():
        print("Edge 启动失败"); return
    c = await _connect()
    ok, url, sid = await try_restore(c)
    log.info("restore ok=%s url=%s", ok, url)
    if not ok:
        print("会话恢复失败"); await c.ws.close(); return
    await c.call("Page.enable", {}, session=sid)
    await asyncio.sleep(4)
    # 当前 URL
    cur = await c.eval("location.href", sid)
    # 所有 button 文本
    btns = await c.eval("JSON.stringify([...document.querySelectorAll('button')].map(b=>({t:b.innerText.trim().slice(0,40),en:b.disabled})))", sid)
    # textarea?
    has_ta = await c.eval("!!document.querySelector('textarea')", sid)
    # 可见文案前 1200 字
    body = await c.eval("(document.body.innerText||'').slice(0,1200)", sid) or ""
    print("URL:", cur)
    print("HAS_TEXTAREA:", has_ta)
    print("BUTTONS:", btns)
    print("BODY_TEXT:\n", body)
    await c.ws.close()

asyncio.run(main())
