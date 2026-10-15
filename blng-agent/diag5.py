"""诊断5: 复用设计项目页时, textarea 是否存在/何时消失。"""
import asyncio, json, logging, sys
from blng_tool import ensure_edge, _connect
from blng_auto import try_restore

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("diag5")

URL = "https://app.blng.ai/design/c61b8783-b90b-43b7-8232-153a24bc0af9"


async def probe(c, sid, tag):
    js = """JSON.stringify({
      url: location.href,
      ta_count: document.querySelectorAll('textarea').length,
      ta_visible: [...document.querySelectorAll('textarea')].map(t=>t.offsetParent!==null),
      buttons: [...document.querySelectorAll('button')].map(b=>b.innerText.trim().split('\\n')[0].slice(0,20)).filter(Boolean).slice(0,20),
      body: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,300)
    })"""
    raw = await c.eval(js, sid)
    print(f"\n== [{tag}] ==")
    print(raw)


async def main():
    if not ensure_edge():
        print("Edge fail"); return
    c = await _connect()
    ok, url, sid = await try_restore(c, URL)
    log.info("restore ok=%s url=%s", ok, url)
    await c.call("Page.enable", {}, session=sid)
    for i in range(8):
        await asyncio.sleep(3)
        await probe(c, sid, f"t+{(i+1)*3}s")
    await c.ws.close()

asyncio.run(main())
