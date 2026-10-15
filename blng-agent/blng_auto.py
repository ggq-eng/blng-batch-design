"""
blng_auto.py —— BLNG 自动会话（登录态自动注入 + 失效自动重登）
================================================================
认证架构: AWS Cognito
  - accessToken  有效期 ~1h
  - idToken      有效期 ~1h
  - refreshToken 有效期 ~30d  ← 长存活凭据
  - 存储位置: localStorage (CognitoIdentityServiceProvider.*)

策略:
  ensure() 自动判断:
    1. 注入已保存的 Cognito 凭据 -> 访问 dashboard
    2. 若成功 -> 直接复用（refreshToken 会静默续期）
    3. 若失败 -> 自动重新账号密码登录并刷新快照

复杂度: 复用 O(1)+渲染等待；重登 O(1)*多次等待
用法:
  python blng_auto.py ensure           # 保证处于登录态
  python blng_auto.py snapshot <url>   # 登录态下抓取任意页面
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from blng_tool import ensure_edge, _connect, SHOT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("blng.auto")

STATE_FILE = Path(__file__).parent / ".blng_session.json"
DASHBOARD = "https://app.blng.ai/dashboard"
ORIGIN = "https://app.blng.ai"


async def _is_logged_in(c, sid) -> bool:
    return bool(await c.eval(
        "location.pathname.includes('/dashboard') || "
        "location.pathname.includes('/design/') || "
        "!!document.querySelector('textarea') || "
        "/All designs|My files|New Design|Upgrade/i.test(document.body.innerText)", sid))


async def try_restore(c, url: str = DASHBOARD) -> tuple[bool, str | None, str | None]:
    """
    尝试用已保存的 Cognito 凭据恢复会话。
    关键: 必须先导航到同源页面才能写 localStorage，再重新加载使其生效。
    返回: (是否登录, 最终URL, sessionId)
    """
    if not STATE_FILE.exists():
        log.info("无会话快照，跳过恢复")
        return False, None, None

    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    # 1) 先到源站（about:blank 无法访问 localStorage）
    sid = await c.new_page(f"{ORIGIN}/", settle=3)
    await c.call("Network.enable", {}, session=sid)

    # 2) 注入 cookies
    for ck in state.get("cookies", []):
        params = {k: ck[k] for k in ("name", "value", "domain", "path") if k in ck}
        if ck.get("expires"):
            params["expires"] = ck["expires"]
        for f in ("httpOnly", "secure", "sameSite"):
            if f in ck:
                params[f] = ck[f]
        try:
            await c.call("Network.setCookie", params, session=sid)
        except Exception as e:
            log.debug("cookie %s 注入失败: %s", ck.get("name"), e)

    # 3) 注入 localStorage（Cognito 凭据）
    for k, v in (state.get("localStorage") or {}).items():
        await c.eval("localStorage.setItem(%s,%s)" % (json.dumps(k), json.dumps(v)), sid)
    log.info("已注入 %d cookies + %d localStorage 项",
             len(state.get("cookies", [])), len(state.get("localStorage", {})))

    # 4) 导航到 dashboard 验证
    await c.call("Page.navigate", {"url": url}, session=sid)
    await asyncio.sleep(7)
    ok = await _is_logged_in(c, sid)
    got = await c.eval("location.href", sid)
    log.info("恢复结果: logged_in=%s url=%s", ok, got)
    return ok, got, sid


async def _do_login(c) -> tuple[bool, str | None]:
    """账号密码登录并刷新快照。返回 (是否成功, sessionId)。"""
    from blng_session import EMAIL, PASSWORD
    sid = await c.new_page(f"{ORIGIN}/", settle=5)
    await c.call("Network.enable", {}, session=sid)

    async def setin(sel, val):
        return await c.eval("""
        (() => {const el=document.querySelector(%s); if(!el) return 'no';
          Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(el,%s);
          el.dispatchEvent(new Event('input',{bubbles:true}));
          el.dispatchEvent(new Event('change',{bubbles:true})); return 'ok';})()
        """ % (json.dumps(sel), json.dumps(val)), sid)

    async def click(txt):
        return await c.eval("""
        (() => {const b=[...document.querySelectorAll('button')]
          .find(x=>x.innerText.trim().toLowerCase()===%s);
          if(!b||b.disabled) return 'no'; b.click(); return 'ok';})()
        """ % json.dumps(txt.lower()), sid)

    await setin("input[type=email]", EMAIL)
    await asyncio.sleep(1.2)
    await click("continue with email")
    await asyncio.sleep(8)
    if await c.eval("!!document.querySelector('input[type=password]')", sid):
        await setin("input[type=email]", EMAIL)
        await asyncio.sleep(0.6)
        await setin("input[type=password]", PASSWORD)
        await asyncio.sleep(1.2)
        await click("continue")
        await asyncio.sleep(12)

    ok = await _is_logged_in(c, sid)
    if ok:
        # 刷新快照
        cookies = (await c.call("Network.getCookies", {}, session=sid)).get("cookies", [])
        ls = await c.eval("JSON.stringify(Object.fromEntries(Object.entries(localStorage)))", sid)
        ss = await c.eval("JSON.stringify(Object.fromEntries(Object.entries(sessionStorage)))", sid)
        STATE_FILE.write_text(json.dumps({
            "cookies": cookies,
            "localStorage": json.loads(ls) if ls else {},
            "sessionStorage": json.loads(ss) if ss else {},
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("登录成功，会话快照已刷新")
    return ok, sid


async def ensure() -> dict:
    """保证登录态：优先恢复，失败则重登。"""
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}
    c = await _connect()
    try:
        ok, url, sid = await try_restore(c)
        method = "restore"
        if not ok:
            log.info("恢复失败，执行重新登录...")
            rl = await _do_login(c)
            ok, method, sid = rl[0], "relogin", rl[1]
            url = DASHBOARD if ok else url
        return {"success": ok, "method": method, "url": url}
    except Exception as e:
        log.exception("ensure 异常")
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await c.ws.close()


async def snapshot_authed(url: str) -> dict:
    """登录态下抓取页面。直接复用 restore 返回的有效 sessionId。"""
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}
    c = await _connect()
    try:
        ok, got_url, sid = await try_restore(c, url)
        if not ok or not sid:
            return {"success": False, "error": "登录态无效", "url": got_url}
        info = json.loads(await c.eval(
            "JSON.stringify({t:document.title,u:location.href,"
            "x:(document.body.innerText||'').slice(0,3000)})", sid))
        ts = time.strftime("%Y%m%d_%H%M%S")
        p = SHOT_DIR / f"auth_{ts}.png"
        await c.shot(p, sid)
        return {"success": True, "title": info.get("t"), "url": info.get("u"),
                "text": info.get("x"), "screenshot": str(p)}
    except Exception as e:
        log.exception("snapshot_authed 异常")
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await c.ws.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ensure"
    if cmd == "ensure":
        r = asyncio.run(ensure())
    elif cmd == "snapshot":
        target = sys.argv[2] if len(sys.argv) > 2 else DASHBOARD
        r = asyncio.run(snapshot_authed(target))
    else:
        r = {"error": f"未知命令 {cmd}; 可用: ensure | snapshot <url>"}
    print(json.dumps(r, ensure_ascii=False, indent=2))
