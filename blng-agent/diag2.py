"""诊断2: 点击 New Design 后的编辑器真实状态（冷启动）。"""
import asyncio, json, logging, sys

from blng_tool import ensure_edge, _connect
from blng_auto import try_restore

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("diag2")


async def dump(c, sid, tag):
    cur = await c.eval("location.href", sid)
    has_ta = await c.eval("!!document.querySelector('textarea')", sid)
    btns = await c.eval("JSON.stringify([...document.querySelectorAll('button')].map(b=>b.innerText.trim().slice(0,40)).filter(Boolean))", sid)
    body = (await c.eval("(document.body.innerText||'').slice(0,900)", sid)) or ""
    print(f"\n===== [{tag}] =====")
    print("URL:", cur, "| TEXTAREA:", has_ta)
    print("BUTTONS:", btns)
    print("BODY:", body.replace("\n", " | ")[:600])


async def main():
    if not ensure_edge():
        print("Edge 启动失败")
        return
    c = await _connect()
    ok, url, sid = await try_restore(c)
    log.info("restore ok=%s url=%s", ok, url)
    if not ok:
        print("会话恢复失败")
        await c.ws.close()
        return
    await c.call("Page.enable", {}, session=sid)
    await asyncio.sleep(4)
    await dump(c, sid, "dashboard")

    # 点击 New Design
    r = await c.eval("""(() => {const b=[...document.querySelectorAll('button')]
        .find(x=>/^new design$/i.test(x.innerText.trim()));
      if(!b) return 'not-found'; if(b.disabled) return 'disabled'; b.click(); return 'clicked';})()""", sid)
    print("\nNew Design click:", r)
    await asyncio.sleep(8)
    await dump(c, sid, "after-new-design")

    # 若出现 textarea 直接报告；否则继续观察 10s
    if not await c.eval("!!document.querySelector('textarea')", sid):
        await asyncio.sleep(10)
        await dump(c, sid, "after-18s")
    await c.ws.close()

asyncio.run(main())
