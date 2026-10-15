"""
blng_login.py —— BLNG 邮箱登录流程探测与执行
=============================================
BLNG 采用 passwordless (OTP/magic-link) 登录:
  - 页面仅有 email 输入框，无 password 字段
  - 提交后大概率要求邮箱验证码 或 发送登录链接

流程:
  1. 填邮箱 -> 点击 Continue with email
  2. 探测下一步 UI（验证码输入框 / 提示文案）
  3. 若需验证码，输出提示等待用户提供

复杂度: O(1) 每步；含渲染等待约 5-10s
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
log = logging.getLogger("blng.login")

EMAIL = "226****82@qq.com（已脱敏）"
PASSWORD = "[已脱敏]！"


async def run(email: str, otp: str | None = None) -> dict:
    """执行登录流程。若提供 otp 则一并填入。"""
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}

    c = await _connect()
    out: dict = {"success": False, "stage": None, "email": email}
    try:
        sid = await c.new_page("https://app.blng.ai/")
        await c.call("Page.enable", {}, session=sid)

        # --- Step 1: 填入邮箱 ---
        # 使用原生 setter 触发 React 的 onChange
        fill_js = """
        (() => {
          const inp = document.querySelector('input[type=email]');
          if (!inp) return 'no-email-input';
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
          setter.call(inp, %s);
          inp.dispatchEvent(new Event('input',{bubbles:true}));
          inp.dispatchEvent(new Event('change',{bubbles:true}));
          return 'filled';
        })()
        """ % json.dumps(email)
        r = await c.eval(fill_js, sid)
        log.info("填邮箱: %s", r)
        if r != "filled":
            out.update(error=f"未找到邮箱输入框: {r}")
            return out

        await asyncio.sleep(1.2)  # 等按钮 enable

        # --- Step 2: 点击继续 ---
        click_js = """
        (() => {
          const btn = [...document.querySelectorAll('button')]
            .find(b => b.type==='submit' || /continue with email/i.test(b.innerText));
          if (!btn) return 'no-button';
          if (btn.disabled) return 'button-disabled';
          btn.click();
          return 'clicked';
        })()
        """
        r2 = await c.eval(click_js, sid)
        log.info("点击继续: %s", r2)
        out["stage"] = "email_submitted"
        await asyncio.sleep(8)  # 等服务端响应 + UI 切换

        # --- Step 3: 探测下一步 ---
        probe = await c.eval("""JSON.stringify({
            url: location.href,
            text: (document.body.innerText||'').slice(0,1500),
            inputs: [...document.querySelectorAll('input')].map(i=>({type:i.type,ph:i.placeholder,name:i.name})),
            buttons: [...document.querySelectorAll('button')].map(b=>({t:b.innerText.trim(),disabled:b.disabled}))
        })""", sid)
        info = json.loads(probe) if probe else {}
        out["next_step"] = info

        ts = time.strftime("%Y%m%d_%H%M%S")
        shot = SHOT_DIR / f"login_{ts}.png"
        await c.shot(shot, sid)
        out["screenshot"] = str(shot)

        if otp:
            log.info("检测到 OTP=%s，执行填入", otp)
            # 留给下一步实现
            out["note"] = "OTP 填报流程预留"

        out["success"] = True
        return out

    except Exception as e:
        log.exception("登录流程异常")
        out.update(error=f"{type(e).__name__}: {e}")
        return out
    finally:
        await c.ws.close()


if __name__ == "__main__":
    otp_arg = sys.argv[1] if len(sys.argv) > 1 else None
    res = asyncio.run(run(EMAIL, otp_arg))
    print(json.dumps(res, ensure_ascii=False, indent=2))
