"""诊断3: canvas-size 弹窗的 DOM 细节（分辨率/Start 按钮为何点不到）。"""
import asyncio, json, logging, sys
from blng_tool import ensure_edge, _connect
from blng_auto import try_restore

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("diag3")


async def dump_modal(c, sid, tag):
    js = """(() => {
      const btns=[...document.querySelectorAll('button')].map(b=>({
        t:b.innerText.trim().replace(/\\s+/g,' ').slice(0,40),
        dis:b.disabled, vis:b.offsetParent!==null,
        r:(()=>{const x=b.getBoundingClientRect();return [Math.round(x.x),Math.round(x.y),Math.round(x.width),Math.round(x.height)];})()
      }));
      const dlg=document.querySelector('[role=dialog]')||document.querySelector('dialog');
      return JSON.stringify({dialog:dlg?dlg.innerText.replace(/\\s+/g,' ').slice(0,600):null,
        btns}, null, 0);
    })()"""
    raw = await c.eval(js, sid)
    print(f"\n===== [{tag}] =====")
    try:
        d = json.loads(raw)
        print("DIALOG:", d.get("dialog"))
        for b in d.get("btns", []):
            print(f"  btn '{b['t']}' dis={b['dis']} vis={b['vis']} rect={b['r']}")
    except Exception as e:
        print("parse fail:", e, raw[:400])


async def main():
    if not ensure_edge():
        print("Edge 启动失败"); return
    c = await _connect()
    ok, url, sid = await try_restore(c)
    log.info("restore ok=%s", ok)
    if not ok:
        await c.ws.close(); return
    await c.call("Page.enable", {}, session=sid)
    await asyncio.sleep(3)
    await dump_modal(c, sid, "dashboard")

    # 点击 New Design
    await c.eval("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>/^new design$/i.test(x.innerText.trim()));if(b)b.click();})()""", sid)
    await asyncio.sleep(4)
    await dump_modal(c, sid, "after New Design")

    # 点击 Square
    await c.eval("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>/^square/i.test(x.innerText.trim()));if(b)b.click();})()""", sid)
    await asyncio.sleep(3)
    await dump_modal(c, sid, "after click Square")

    await c.ws.close()

asyncio.run(main())
