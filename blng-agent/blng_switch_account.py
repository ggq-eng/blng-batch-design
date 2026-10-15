"""
blng_switch_account.py —— 切换 BLNG 账号
==========================================
流程:
  1. 备份旧账号会话快照（可恢复）
  2. 清空浏览器 localStorage / sessionStorage / cookies
  3. 用新账号登录
  4. 保存新账号会话快照

复杂度: O(1) + 渲染等待
用法: python blng_switch_account.py <email> <password>
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import time
from pathlib import Path

from blng_tool import ensure_edge, _connect, SHOT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("blng.switch")

BASE = Path(__file__).parent
STATE = BASE / ".blng_session.json"
ORIGIN = "https://app.blng.ai"


async def _set_input(c, sid, sel, val):
    js = """
    (() => {const el=document.querySelector(%s); if(!el) return 'not-found';
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(el,%s);
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      return el.value===%s?'ok':'mismatch';})()
    """ % (json.dumps(sel), json.dumps(val), json.dumps(val))
    return await c.eval(js, sid)


async def _click(c, sid, text):
    js = """
    (() => {const b=[...document.querySelectorAll('button')]
      .find(x=>x.innerText.trim().toLowerCase()===%s);
      if(!b) return 'not-found'; if(b.disabled) return 'disabled';
      b.click(); return 'clicked';})()
    """ % json.dumps(text.lower())
    return await c.eval(js, sid)


async def switch(email: str, password: str) -> dict:
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}

    # 1) 备份旧会话
    if STATE.exists():
        bak = BASE / f".blng_session.backup_{time.strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copy2(STATE, bak)
        log.info("旧会话已备份 -> %s", bak.name)

    c = await _connect()
    out = {"success": False, "email": email}
    try:
        # 2) 打开站点并清空存储
        sid = await c.new_page(f"{ORIGIN}/", settle=4)
        await c.call("Network.enable", {}, session=sid)
        await c.eval("localStorage.clear(); sessionStorage.clear();", sid)
        # 逐个删除 cookie（setCookie 传空值 + 过期时间，最兼容的方式）
        try:
            cks = (await c.call("Network.getCookies", {}, session=sid)).get("cookies", [])
            for ck in cks:
                await c.call("Network.deleteCookies",
                             {"name": ck["name"], "domain": ck.get("domain"),
                              "path": ck.get("path", "/")}, session=sid)
            log.info("已清除 %d 个 cookie", len(cks))
        except Exception as e:
            log.warning("deleteCookies 失败，改用 JS 过期法: %s", e)
            await c.eval("""
            document.cookie.split(';').forEach(c=>{
                const n=c.split('=')[0].trim();
                ['/','/app'].forEach(p=>{
                  document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path='+p;
                });
            });
            """, sid)
        log.info("已清空 localStorage / sessionStorage / cookies")

        # 3) 硬刷新，回到未登录态
        await c.call("Page.reload", {"ignoreCache": True}, session=sid)
        await asyncio.sleep(7)

        # 3.5) 等待登录表单挂载（React 异步渲染，直接查询会 not-found）
        for wait_i in range(10):
            if await c.eval("!!document.querySelector('input[type=email]')", sid):
                log.info("登录表单已就绪")
                break
            log.info("  等表单渲染… (%d)", wait_i + 1)
            await asyncio.sleep(3)
        else:
            return {"success": False, "email": email, "error": "登录表单未渲染"}

        # 4) 填邮箱
        r = await _set_input(c, sid, "input[type=email]", email)
        log.info("填邮箱(%s): %s", email, r)
        await asyncio.sleep(1.2)
        log.info("点击 Continue: %s", await _click(c, sid, "continue with email"))
        await asyncio.sleep(9)

        # 5) 密码页
        has_pw = False
        for _ in range(8):
            if await c.eval("!!document.querySelector('input[type=password]')", sid):
                has_pw = True
                break
            await asyncio.sleep(2)
        log.info("是否出现密码页: %s", has_pw)
        if has_pw:
            await _set_input(c, sid, "input[type=email]", email)
            await asyncio.sleep(0.6)
            log.info("填密码: %s", await _set_input(c, sid, "input[type=password]", password))
            await asyncio.sleep(1.2)
            log.info("点击 Continue: %s", await _click(c, sid, "continue"))
            await asyncio.sleep(12)

        # 6) 判定
        url = await c.eval("location.href", sid)
        txt = await c.eval("(document.body.innerText||'').slice(0,400)", sid) or ""
        ok = "dashboard" in str(url) or "/design/" in str(url) or bool(
            __import__("re").search(r"All designs|My files|New Design", txt))
        out.update(success=bool(ok), url=url)
        log.info("登录结果: %s | url=%s", ok, url)

        if ok:
            cookies = (await c.call("Network.getCookies", {}, session=sid)).get("cookies", [])
            ls = await c.eval("JSON.stringify(Object.fromEntries(Object.entries(localStorage)))", sid)
            ss = await c.eval("JSON.stringify(Object.fromEntries(Object.entries(sessionStorage)))", sid)
            STATE.write_text(json.dumps({
                "cookies": cookies,
                "localStorage": json.loads(ls) if ls else {},
                "sessionStorage": json.loads(ss) if ss else {},
                "account": email,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info("新账号会话已保存 (%d cookies, %d localStorage)",
                     len(cookies), len(json.loads(ls) if ls else {}))
            out["saved"] = str(STATE)

        ts = time.strftime("%Y%m%d_%H%M%S")
        out["screenshot"] = str(await c.shot(SHOT_DIR / f"switch_{ts}.png", sid))
        return out

    except Exception as e:
        log.exception("切换账号异常")
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    finally:
        await c.ws.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python blng_switch_account.py <email> <password>")
        sys.exit(2)
    r = asyncio.run(switch(sys.argv[1], sys.argv[2]))
    print(json.dumps(r, ensure_ascii=False, indent=2))
