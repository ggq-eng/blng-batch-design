"""
blng_login2.py —— BLNG 完整登录（邮箱 -> 密码 -> 进入应用）
============================================================
流程:
  1. 填邮箱 -> Continue with email
  2. 若进入密码页 -> 填密码 -> Continue
  3. 若进入 OTP 页 -> 打印提示，等待验证码
  4. 输出登录后页面状态 + 截图

复杂度: O(1) 每步；整体约 20-30s
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time

from blng_tool import ensure_edge, _connect, SHOT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("blng.login2")

EMAIL = "226****82@qq.com（已脱敏）"
PASSWORD = "Hq******!（已脱敏）"


async def _set_input(c, sid: str, selector: str, value: str) -> str:
    """用原生 setter 填值并触发 React 事件。"""
    js = """
    (() => {
      const el = document.querySelector(%s);
      if (!el) return 'not-found';
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, %s);
      el.dispatchEvent(new Event('input', {bubbles:true}));
      el.dispatchEvent(new Event('change', {bubbles:true}));
      el.dispatchEvent(new Event('blur',{bubbles:true}));
      return el.value === %s ? 'ok' : 'mismatch:'+el.value;
    })()
    """ % (json.dumps(selector), json.dumps(value), json.dumps(value))
    return await c.eval(js, sid)


async def _click_text(c, sid: str, text: str) -> str:
    """点击文本匹配的按钮。"""
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


async def _probe(c, sid: str) -> dict:
    js = """JSON.stringify({
        url: location.href,
        text: (document.body.innerText||'').slice(0,2000),
        inputs: [...document.querySelectorAll('input')].map(i=>({type:i.type,ph:i.placeholder})),
        buttons: [...document.querySelectorAll('button')].map(b=>({t:b.innerText.trim(),disabled:b.disabled}))
    })"""
    raw = await c.eval(js, sid)
    return json.loads(raw) if raw else {}


async def run() -> dict:
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}
    c = await _connect()
    out: dict = {"success": False}
    try:
        sid = await c.new_page("https://app.blng.ai/")
        await c.call("Page.enable", {}, session=sid)

        # --- Step 1: 邮箱 ---
        log.info("填入邮箱...")
        log.info("  结果: %s", await _set_input(c, sid, 'input[type=email]', EMAIL))
        await asyncio.sleep(1.2)
        log.info("点击 Continue with email: %s", await _click_text(c, sid, "Continue with email"))
        await asyncio.sleep(8)

        p1 = await _probe(c, sid)
        log.info("步骤1后页面: has_password=%s", any(i["type"] == "password" for i in p1.get("inputs", [])))

        # --- Step 2: 密码 ---
        if any(i["type"] == "password" for i in p1.get("inputs", [])):
            log.info("检测到密码页，填入密码...")
            # 密码页的 email 框可能是空的，先补邮箱
            em = await _set_input(c, sid, 'input[type=email]', EMAIL)
            log.info("  邮箱: %s", em)
            await asyncio.sleep(0.8)
            pw = await _set_input(c, sid, 'input[type=password]', PASSWORD)
            log.info("  密码: %s", pw)
            await asyncio.sleep(1.2)
            r = await _click_text(c, sid, "continue")
            log.info("  点击 Continue: %s", r)
            await asyncio.sleep(10)

        # --- Step 3: 结果 ---
        final = await _probe(c, sid)
        out["final"] = final
        ts = time.strftime("%Y%m%d_%H%M%S")
        shot = SHOT_DIR / f"loggedin_{ts}.png"
        await c.shot(shot, sid)
        out["screenshot"] = str(shot)

        txt = (final.get("text") or "").lower()
        if any(k in txt for k in ("sign in", "log in", "invalid", "incorrect", "error", "wrong")):
            out["success"] = False
            out["error"] = "登录疑似失败，详见 final.text"
        else:
            out["success"] = True
        return out

    except Exception as e:
        log.exception("登录异常")
        out.update(error=f"{type(e).__name__}: {e}")
        return out
    finally:
        await c.ws.close()


if __name__ == "__main__":
    res = asyncio.run(run())
    print("\n" + "=" * 60)
    print(json.dumps(res, ensure_ascii=False, indent=2))
