"""诊断6: dashboard 文件列表 + 点卡片进入项目是否稳定。"""
import asyncio, json, logging, sys
from blng_tool import ensure_edge, _connect
from blng_auto import try_restore

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("diag6")


async def main():
    if not ensure_edge():
        print("Edge fail"); return
    c = await _connect()
    ok, url, sid = await try_restore(c)   # dashboard
    log.info("restore ok=%s", ok)
    await c.call("Page.enable", {}, session=sid)
    await asyncio.sleep(4)

    body = await c.eval("(document.body.innerText||'').replace(/\\s+/g,' ')", sid)
    print("=== DASHBOARD BODY (full) ===")
    print(body[:1200])

    # 所有指向 /design/ 的链接
    links = await c.eval(
        "JSON.stringify([...document.querySelectorAll('a[href*=\"/design/\"]')].map(a=>({h:a.getAttribute('href'),t:a.innerText.trim().slice(0,30)})))", sid)
    print("=== DESIGN LINKS ===")
    print(links)

    await c.ws.close()

asyncio.run(main())
