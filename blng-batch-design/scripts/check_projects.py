"""check_projects.py — 只读: 查当前账号的活跃 design file 数量与套餐(免费版上限 3 个)。"""
import asyncio, json, logging, sys
from blng_tool import ensure_edge, _connect
from blng_auto import try_restore, DASHBOARD

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("chk")


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
    # 抓 API: 设计列表
    js = """(async () => {
      const out = {};
      try {
        const r = await fetch('/api/designs', {credentials:'include'});
        out.designs_status = r.status;
        if (r.ok) { const j = await r.json(); out.designs_json = JSON.stringify(j).slice(0,1500); }
      } catch(e) { out.designs_err = String(e); }
      try {
        const r2 = await fetch('/api/user/plan', {credentials:'include'});
        out.plan_status = r2.status;
        if (r2.ok) { const j2 = await r2.json(); out.plan_json = JSON.stringify(j2).slice(0,800); }
      } catch(e) { out.plan_err = String(e); }
      out.body = (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,600);
      return JSON.stringify(out);
    })()"""
    raw = await c.eval(js, sid)
    print(raw)
    await c.ws.close()

asyncio.run(main())
