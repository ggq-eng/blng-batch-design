"""诊断4: 编辑器里 img 的 DOM 结构与生成顺序的关系。"""
import asyncio, json, logging, sys
from blng_tool import ensure_edge, _connect
from blng_auto import try_restore, DASHBOARD

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("diag4")

URL = "https://app.blng.ai/design/4be097b7-fb72-44a1-b2fe-80ce02138058"


async def main():
    if not ensure_edge():
        print("Edge 启动失败"); return
    c = await _connect()
    ok, url, sid = await try_restore(c, URL)
    log.info("restore ok=%s", ok)
    await c.call("Page.enable", {}, session=sid)
    await asyncio.sleep(6)
    js = """JSON.stringify([...document.querySelectorAll('img')]
      .filter(i=>i.naturalWidth>=512)
      .map((i,idx)=>({idx, nw:i.naturalWidth, nh:i.naturalHeight,
        cls:i.className.slice(0,40), alt:(i.alt||'').slice(0,30),
        parent:(i.parentElement?i.parentElement.className.slice(0,40):''),
        src:i.src.slice(0,60)})))"""
    raw = await c.eval(js, sid)
    arr = json.loads(raw) if raw else []
    print("total imgs>512:", len(arr))
    for a in arr:
        print(f"  DOM#{a['idx']} {a['nw']}x{a['nh']} cls='{a['cls']}' parent='{a['parent']}' src=...{a['src'][-40:]}")
    await c.ws.close()

asyncio.run(main())
