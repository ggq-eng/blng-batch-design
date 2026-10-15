"""
blng_session.py —— BLNG 持久化会话管理
========================================
问题: BLNG 的认证态存在 localStorage + cookies，进程重启后丢失。
方案: 登录成功后导出存储快照，后续会话自动注入。

能力:
  - login()       执行登录并保存会话
  - load()        加载已保存会话并注入
  - ensure()      自动判断：有效则复用，失效则重新登录
  - status()      检查当前登录态

复杂度: 登录 O(1)*渲染等待；注入 O(1)
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
log = logging.getLogger("blng.session")

STATE_FILE = Path(__file__).parent / ".blng_session.json"

# ============================================================
#  凭据配置 —— 使用前请填写你自己的 BLNG 账号
# ============================================================
# 方式一（推荐）：直接填写下面两行
EMAIL = ""
PASSWORD = ""
# 方式二：设置环境变量 BLNG_EMAIL / BLNG_PASSWORD（优先级高于上面的填写）
import os as _os
EMAIL = _os.environ.get("BLNG_EMAIL") or EMAIL
PASSWORD = _os.environ.get("BLNG_PASSWORD") or PASSWORD
# ============================================================

DASHBOARD = "https://app.blng.ai/dashboard"


# --------------------------------------------------------------------
# 底层操作
# --------------------------------------------------------------------
async def _set_input(c, sid, selector, value) -> str:
    js = """
    (() => {
      const el = document.querySelector(%s);
      if (!el) return 'not-found';
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto,'value').set.call(el, %s);
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      el.dispatchEvent(new Event('blur',{bubbles:true}));
      return el.value === %s ? 'ok' : 'mismatch';
    })()
    """ % (json.dumps(selector), json.dumps(value), json.dumps(value))
    return await c.eval(js, sid)


async def _click_text(c, sid, text) -> str:
    js = """
    (() => {
      const b = [...document.querySelectorAll('button')]
        .find(x => x.innerText.trim().toLowerCase() === %s);
      if (!b) return 'not-found';
      if (b.disabled) return 'disabled';
      b.click(); return 'clicked';
    })()
    """ % json.dumps(text.lower())
    return await c.eval(js, sid)


async def _is_logged_in(c, sid) -> bool:
    """判定是否已进入应用内部。"""
    r = await c.eval(
        "location.pathname.includes('dashboard') || "
        "/All designs|My files|New Design/i.test(document.body.innerText)", sid)
    return bool(r)


async def _probe(c, sid) -> dict:
    raw = await c.eval("""JSON.stringify({
        url: location.href,
        text: (document.body.innerText||'').slice(0,1200),
        inputs: [...document.querySelectorAll('input')].map(i=>i.type)
    })""", sid)
    return json.loads(raw) if raw else {}


# --------------------------------------------------------------------
# 会话导出 / 注入
# --------------------------------------------------------------------
async def _export_state(c, sid) -> dict:
    """导出 cookies + localStorage + sessionStorage。"""
    cookies = await c.call("Network.getCookies", {}, session=sid)
    ls = await c.eval("JSON.stringify(Object.fromEntries(Object.entries(localStorage)))", sid)
    ss = await c.eval("JSON.stringify(Object.fromEntries(Object.entries(sessionStorage)))", sid)
    return {
        "cookies": cookies.get("cookies", []),
        "localStorage": json.loads(ls) if ls else {},
        "sessionStorage": json.loads(ss) if ss else {},
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


async def _inject_state(c, sid, state: dict) -> None:
    """注入 cookies 与 storage。"""
    for ck in state.get("cookies", []):
        params = {k: ck[k] for k in ("name", "value", "domain", "path") if k in ck}
        if "expires" in ck and ck["expires"]:
            params["expires"] = ck["expires"]
        if "httpOnly" in ck:
            params["httpOnly"] = ck["httpOnly"]
        if "secure" in ck:
            params["secure"] = ck["secure"]
        try:
            await c.call("Network.setCookie", params, session=sid)
        except Exception as e:
            log.warning("注入 cookie 失败 %s: %s", ck.get("name"), e)

    for store, key in (("localStorage", "localStorage"), ("sessionStorage", "sessionStorage")):
        for k, v in (state.get(key) or {}).items():
            js = "%s.setItem(%s, %s)" % (store, json.dumps(k), json.dumps(v))
            await c.eval(js, sid)


# --------------------------------------------------------------------
# 对外 API
# --------------------------------------------------------------------
async def login(save: bool = True) -> dict:
    """执行完整登录，导出会话。"""
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}
    c = await _connect()
    out = {"success": False}
    try:
        sid = await c.new_page("https://app.blng.ai/")
        await c.call("Page.enable", {}, session=sid)
        await c.call("Network.enable", {}, session=sid)

        await _set_input(c, sid, "input[type=email]", EMAIL)
        await asyncio.sleep(1.2)
        await _click_text(c, sid, "Continue with email")
        await asyncio.sleep(8)

        p = await _probe(c, sid)
        if "password" in p.get("inputs", []):
            await _set_input(c, sid, "input[type=email]", EMAIL)
            await asyncio.sleep(0.6)
            await _set_input(c, sid, "input[type=password]", PASSWORD)
            await asyncio.sleep(1.2)
            await _click_text(c, sid, "continue")
            await asyncio.sleep(12)
        else:
            out["note"] = "未出现密码页；可能需 OTP 验证码"

        ok = await _is_logged_in(c, sid)
        out["success"] = ok
        out["url"] = (await _probe(c, sid)).get("url")

        if ok and save:
            state = await _export_state(c, sid)
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            n = len(state.get("cookies", []))
            log.info("会话已保存 -> %s (cookies=%d, ls=%d)", STATE_FILE.name,
                     n, len(state.get("localStorage", {})))
            out["saved"] = str(STATE_FILE)
            out["cookies"] = n

        ts = time.strftime("%Y%m%d_%H%M%S")
        shot = SHOT_DIR / f"session_{ts}.png"
        await c.shot(shot, sid)
        out["screenshot"] = str(shot)
        return out
    except Exception as e:
        log.exception("登录异常")
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    finally:
        await c.ws.close()


async def check(url: str = DASHBOARD) -> dict:
    """检查当前（进程内）登录态。"""
    if not ensure_edge():
        return {"logged_in": False, "error": "Edge CDP 不可用"}
    c = await _connect()
    try:
        sid = await c.new_page(url)
        ok = await _is_logged_in(c, sid)
        p = await _probe(c, sid)
        return {"logged_in": ok, "url": p.get("url"), "text": (p.get("text") or "")[:300]}
    finally:
        await c.ws.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    if cmd == "login":
        res = asyncio.run(login())
    elif cmd == "status":
        res = asyncio.run(check())
    else:
        res = {"error": f"未知命令 {cmd}; 可用: login | status"}
    print(json.dumps(res, ensure_ascii=False, indent=2))
