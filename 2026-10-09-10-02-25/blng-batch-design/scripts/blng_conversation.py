"""
blng_conversation.py —— 单对话内连续生成 N 张图
==================================================
需求: "在一个对话中生成八张图" —— 同一 BLNG 项目内连续发提示词，
      而非每条新建项目。

与 diamond_pipeline.py 的区别:
  - pipeline: 每条提示词 -> New Design 建新项目（相互独立）
  - 本脚本:  建 1 个项目 -> 在同一个 textarea 连续发 N 条提示词

关键技术点:
  1. WebSocket 保活: 长等待期间定期发心跳，避免 keepalive ping timeout
  2. 断线重连: CDP 连接断开后自动重连并 attach 原 target
  3. 逐条导出: 每条生成后立即抓取最新大图，避免被后续图覆盖

复杂度: O(N * P)，N=提示词数，P=单条等待轮询；串行执行
用法:
  python blng_conversation.py --file cn_knot_prompts.json --name chinese_knot
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import websockets

from blng_tool import ensure_edge, _connect, CDP, CDP_HTTP, SHOT_DIR
from blng_auto import try_restore, DASHBOARD

import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("blng.conv")

BASE = Path(__file__).parent
OUT_ROOT = BASE / "conversations"
RATIO = "Square"
RES = "2K"
# ============================================================
#  默认落盘目录 —— 已写死为用户指定路径
#  如需改动：改这里，或运行时用 --out-dir 覆盖，或设环境变量 BLNG_OUT_DIR
# ============================================================
import os as _os
DEFAULT_OUT_DIR = _os.environ.get("BLNG_OUT_DIR") or r"D:\Desktop\新建文件夹 (2)\设计图"
# ============================================================
ORIGIN = "https://app.blng.ai"
MAX_RETRY = 2
GEN_TIMEOUT = 240
POLL = 5


# --------------------------------------------------------------------
# 保活连接
# --------------------------------------------------------------------
class LiveCDP(CDP):
    """带心跳保活的 CDP 客户端。"""

    def __init__(self, ws):
        super().__init__(ws)
        self._hb_task: asyncio.Task | None = None

    def start_heartbeat(self, interval: int = 20):
        """定期发送 Runtime.evaluate 维持连接。"""
        async def beat():
            while True:
                await asyncio.sleep(interval)
                try:
                    await super(LiveCDP, self).call(
                        "Runtime.evaluate", {"expression": "1", "returnByValue": True})
                except Exception as e:
                    log.debug("心跳失败: %s", e)
                    return
        self._hb_task = asyncio.create_task(beat())

    def stop(self):
        if self._hb_task:
            self._hb_task.cancel()


async def connect_live() -> LiveCDP:
    info = json.loads(urllib.request.urlopen(f"{CDP_HTTP}/json/version", timeout=8).read())
    ws = await websockets.connect(info["webSocketDebuggerUrl"],
                                  max_size=120 * 1024 * 1024,
                                  ping_interval=15, ping_timeout=40)
    return LiveCDP(ws)


# --------------------------------------------------------------------
# 页面操作
# --------------------------------------------------------------------
async def click(c, sid, pattern: str) -> str:
    return await c.eval("""(() => {const re=new RegExp(%s,'i');
      const b=[...document.querySelectorAll('button')].find(x=>re.test(x.innerText.trim()));
      if(!b) return 'not-found'; if(b.disabled) return 'disabled'; b.click(); return 'clicked';})()
    """ % json.dumps(pattern), sid)


async def click_wait(c, sid, pattern: str, timeout: int = 20, tag: str = "") -> bool:
    """
    轮询点击直到成功。冷启动 SPA 弹窗/按钮渲染有延迟，
    固定 sleep 会错过（历史 bug: fill-not-found 根因）。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = await click(c, sid, pattern)
        if r == "clicked":
            log.info("   click[%s] ✓ (%.0fs)", tag or pattern, time.time() - t0)
            return True
        await asyncio.sleep(1.5)
    log.warning("   click[%s] 超时未点到 (%ds)", tag or pattern, timeout)
    return False


async def wait_textarea(c, sid, timeout: int = 60) -> bool:
    """轮询等待编辑器 textarea 出现。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if await c.eval("!!document.querySelector('textarea')", sid):
            return True
        await asyncio.sleep(2)
    return False


async def fill(c, sid, value: str) -> str:
    return await c.eval("""(() => {const el=document.querySelector('textarea');
      if(!el) return 'not-found';
      el.focus();
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(el,%s);
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      return el.value===%s?'ok':'mismatch';})()
    """ % (json.dumps(value), json.dumps(value)), sid)


async def submit(c, sid) -> str:
    return await c.eval("""(() => {const bs=[...document.querySelectorAll('button')].filter(b=>!b.innerText.trim());
      if(!bs.length) return 'no-icon'; bs[bs.length-1].click(); return 'clicked';})()""", sid)


async def snapshot_imgs(c, sid) -> list[str]:
    """获取当前页面上所有大图的指纹集合（src + 尺寸）。"""
    raw = await c.eval("""JSON.stringify(
        [...document.querySelectorAll('img')]
          .filter(i=>i.naturalWidth>=512)
          .map(i=>i.src+'|'+i.naturalWidth+'x'+i.naturalHeight)
    )""", sid)
    return json.loads(raw) if raw else []


async def snapshot_pixels(c, sid, sample: int = 32) -> list[str]:
    """
    内容指纹: 把每张大图缩到 32x32 取样像素, 生成简易哈希字符串。
    用于跨轮去重 —— 比 src 指纹可靠(同图不同 blob URL 会被识别为相同)。
    """
    raw = await c.eval("""(() => {
      const imgs=[...document.querySelectorAll('img')].filter(i=>i.naturalWidth>=512);
      const out=[];
      for (const im of imgs) {
        try {
          const cv=document.createElement('canvas'); cv.width=%d; cv.height=%d;
          const cx=cv.getContext('2d'); cx.drawImage(im,0,0,%d,%d);
          const d=cx.getImageData(0,0,%d,%d).data;
          let h=''; for (let i=0;i<d.length;i+=16){h+=d[i];h+='.';}
          out.push(h);
        } catch(e){ out.push('ERR:'+e); }
      }
      return JSON.stringify(out);
    })()""" % (sample, sample, sample, sample, sample, sample), sid)
    return json.loads(raw) if raw else []


def _px_from_fp(fp: str) -> str:
    """从 src 指纹取 src 部分做归一化键(供像素映射)。"""
    return fp.split("|")[0]


async def count_messages(c, sid) -> int:
    """统计对话轮次（用 'Created ... in Ns' 出现次数近似）。"""
    txt = await c.eval("(document.body.innerText||'')", sid) or ""
    return len(re.findall(r"Created\s+\w[\w\s]*\s+in\s+\d+\s*second", txt, re.I))


async def export_new_image(c, sid, dest: Path, before_px: list[str],
                           before_fp: list[str] | None = None) -> dict:
    """
    导出【当前最新】的大图 —— 实测最优策略(2026-10-09):

    关键发现: BLNG 编辑器 DOM 是虚拟化的, 同时只挂载少量 <img>。
    新生成完成后, 会出现一张 class 含 'overlay' 的预览大图(即当前聚焦设计),
    这就是"本轮新图"。历史设计只作为 'loaded' 缩略图存在。

    策略(按优先级):
      1. class 含 'overlay' 的 img  → 最准, 就是当前设计
      2. 像素指纹差集取最新
      3. src 指纹差集取最新
    """
    # ---- 策略1: overlay 预览图 ----
    js_overlay = """(() => {
        const im=[...document.querySelectorAll('img')]
          .filter(i=>/overlay/i.test(i.className) && i.naturalWidth>=512)
          .pop();
        if(!im) return 'none';
        try {
            const cv=document.createElement('canvas');
            cv.width=im.naturalWidth; cv.height=im.naturalHeight;
            cv.getContext('2d').drawImage(im,0,0);
            return JSON.stringify({w:im.naturalWidth,h:im.naturalHeight,
                data:cv.toDataURL('image/png').split(',')[1]});
        } catch(e) { return JSON.stringify({err:String(e)}); }
    })()"""
    raw = await c.eval(js_overlay, sid)
    if raw and raw != "none":
        d = json.loads(raw)
        if d.get("data"):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(base64.b64decode(d["data"]))
            px = await snapshot_pixels(c, sid)
            return {"ok": True, "path": str(dest), "width": d["w"], "height": d["h"],
                    "size_mb": round(dest.stat().st_size / 1024 / 1024, 2),
                    "new_count": 1, "fingerprint": "overlay",
                    "pixel_hash": px[0] if px else "", "method": "overlay"}

    # ---- 策略2/3: 差集回退 ----
    after_fp = await snapshot_imgs(c, sid)
    after_px = await snapshot_pixels(c, sid)
    if after_px and before_px:
        new_idxs = [i for i, h in enumerate(after_px)
                    if i < len(after_fp) and h not in before_px]
    else:
        new_idxs = []
    if not new_idxs and before_fp:
        new_idxs = [i for i, s in enumerate(after_fp) if s not in before_fp]
    if not new_idxs:
        return {"ok": False,
                "reason": f"no-new-image (px {len(before_px)}->{len(after_px)} "
                          f"fp {len(before_fp or [])}->{len(after_fp)})"}
    idx = new_idxs[-1]
    fp = after_fp[idx] if idx < len(after_fp) else ""
    px = after_px[idx] if idx < len(after_px) else ""
    js = """(async () => {
        const imgs=[...document.querySelectorAll('img')].filter(i=>i.naturalWidth>=512);
        const im=imgs[%d];
        if(!im) return JSON.stringify({err:'index-out'});
        try {
            const cv=document.createElement('canvas');
            cv.width=im.naturalWidth; cv.height=im.naturalHeight;
            cv.getContext('2d').drawImage(im,0,0);
            return JSON.stringify({w:im.naturalWidth,h:im.naturalHeight,
                data:cv.toDataURL('image/png').split(',')[1]});
        } catch(e) { return JSON.stringify({err:String(e)}); }
    })()""" % idx
    raw = await c.eval(js, sid)
    d = json.loads(raw) if raw else {}
    if not d.get("data"):
        return {"ok": False, "reason": d.get("err", "no-data")}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(base64.b64decode(d["data"]))
    return {"ok": True, "path": str(dest), "width": d["w"], "height": d["h"],
            "size_mb": round(dest.stat().st_size / 1024 / 1024, 2),
            "new_count": len(new_idxs), "fingerprint": fp, "pixel_hash": px,
            "method": "diff"}


async def wait_done(c, sid, timeout: int, before_count: int, before_imgs: list[str]) -> tuple[bool, str]:
    """
    等待【本条】生成完成。
    关键修复: 用"消息轮次增加"或"图片数量增加"作为判据，
    绝不依赖可能残留的文本匹配（历史 bug: 11 秒假完成）。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        await asyncio.sleep(POLL)
        try:
            cnt = await count_messages(c, sid)
            imgs = await snapshot_imgs(c, sid)
            if cnt > before_count or len(imgs) > len(before_imgs):
                return True, "generated"
            txt = await c.eval("(document.body.innerText||'').slice(0,2000)", sid) or ""
            if re.search(r"(failed|something went wrong)", txt, re.I):
                return False, "page-error"
            elapsed = int(time.time() - t0)
            if elapsed % 30 == 0:
                log.info("     …已等 %ds (轮次%d/%d 图%d/%d)", elapsed, cnt, before_count,
                         len(imgs), len(before_imgs))
        except Exception as e:
            log.debug("轮询异常: %s", e)
    return False, f"timeout-{timeout}s"


# --------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------
async def run_conversation(items: list[dict], name: str,
                           start: int = 1, end: int | None = None,
                           reuse_dir: str | None = None,
                           reuse_url: str | None = None,
                           out_dir_root: str | None = None) -> dict:
    if not ensure_edge():
        return {"success": False, "error": "Edge CDP 不可用"}

    # 断点续跑: items 已在外部切片, 但 index 需保留原始序号
    base_index = start - 1

    if reuse_dir:
        # 显式复用目录优先级最高
        out_dir = Path(reuse_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    elif out_dir_root:
        # 默认落盘目录（已写死为 D:\Desktop\新建文件夹 (2)\设计图）
        # —— 直接落盘，不建时间戳子目录
        out_dir = Path(out_dir_root)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        out_dir = OUT_ROOT / f"{name}_{run_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.json"

    c = await connect_live()
    report = {"session": name, "started_at": datetime.now().isoformat(),
              "conversation_mode": True, "total": len(items),
              "ratio": RATIO, "res": RES, "archive_dir": str(out_dir),
              "resumed": bool(reuse_dir or reuse_url), "results": []}
    # 续跑时合并已有 manifest 结果
    if (reuse_dir or out_dir_root) and manifest.exists():
        try:
            old = json.loads(manifest.read_text(encoding="utf-8"))
            report["results"] = old.get("results", [])
            report["project_url"] = old.get("project_url")
        except Exception as e:
            log.warning("读取旧 manifest 失败: %s", e)
    try:
        ok, url, sid = await try_restore(c, reuse_url or DASHBOARD)
        if not ok:
            return {"success": False, "error": "登录态失效"}
        c.start_heartbeat()
        await c.call("Page.enable", {}, session=sid)

        if reuse_url:
            # 复用已有对话项目: 直接在编辑器继续发提示词
            log.info("↻ 复用已有项目: %s", reuse_url)
            if not await wait_textarea(c, sid, 45):
                body = await c.eval("(document.body.innerText||'').slice(0,500)", sid)
                raise RuntimeError(f"复用项目未进编辑器; body={body!r}")
            await asyncio.sleep(3)
            project_url = reuse_url
        else:
            # 建一个项目（整个对话只建这一次）
            # 实测(2026-10-09): 点 New Design -> 弹出"Set the canvas size"弹窗,
            #   弹窗内已有默认预设卡片 "Square 2K 2048 × 2048px";
            #   直接点这张卡片 = 确认尺寸并进入编辑器(弹窗自动关闭)。
            #   切勿再点弹窗内 Square/2K/Start —— 点预设卡片后弹窗即消失,
            #   后续按钮不存在(历史 bug: click[res=2K]/click[start] 超时)。
            log.info("① 创建对话项目 (target=Square 2K 2048x2048)")
            await click(c, sid, r"^got it$")
            if not await click_wait(c, sid, r"^new design$", 25, "new design"):
                raise RuntimeError("New Design 按钮未找到（登录态或页面异常）")
            # 点击预设卡片 "Square 2K 2048 × 2048px"
            if not await click_wait(c, sid, r"^square\s*2k\s*2048", 20, "preset Square-2K"):
                raise RuntimeError("预设卡片 Square 2K 未找到")
            if not await wait_textarea(c, sid, 60):
                body = await c.eval("(document.body.innerText||'').slice(0,500)", sid)
                raise RuntimeError(f"编辑器 textarea 未出现; body={body!r}")
            await asyncio.sleep(3)

            project_url = await c.eval("location.href", sid)
            log.info("   项目: %s", project_url)
        report["project_url"] = project_url

        # 连续发提示词
        seen_fps: set[str] = set()   # 已导出的图片指纹，跨轮去重
        for i, item in enumerate(items, 1):
            pname, prompt = item["name"], item["prompt"]
            real_idx = base_index + i   # 全局序号, 用于文件命名
            log.info("[%d/%d] (#%d) %s", i, len(items), real_idx, pname)
            rec = {"index": real_idx, "name": pname, "prompt": prompt,
                   "attempts": [], "success": False}
            done = False

            # ---- 断点续跑: 该图已存在且非空 -> 跳过(省额度) ----
            skip_dest = out_dir / f"{real_idx:03d}_{pname}.png"
            if skip_dest.exists() and skip_dest.stat().st_size > 1024:
                rec.update(success=True, file=str(skip_dest), skipped=True,
                           size_mb=round(skip_dest.stat().st_size / 1024 / 1024, 2))
                log.info("   ⏭ 已存在，跳过")
                report["results"] = [r for r in report["results"] if r.get("index") != real_idx]
                report["results"].append(rec)
                report["succeeded"] = sum(1 for x in report["results"] if x.get("success"))
                manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                continue

            for att in range(1, MAX_RETRY + 2):
                t0 = time.time()
                try:
                    # 提交前记录基线（等页面稳定，避免把上一轮图算进来）
                    await asyncio.sleep(3)
                    before_imgs = await snapshot_imgs(c, sid)
                    before_px = await snapshot_pixels(c, sid)
                    before_cnt = await count_messages(c, sid)

                    r = await fill(c, sid, prompt)
                    if r != "ok":
                        rec["attempts"].append({"attempt": att, "reason": f"fill-{r}"})
                        await asyncio.sleep(5)
                        continue
                    await asyncio.sleep(2)
                    await submit(c, sid)
                    await asyncio.sleep(4)

                    gok, note = await wait_done(c, sid, GEN_TIMEOUT, before_cnt, before_imgs)
                    if not gok:
                        rec["attempts"].append({"attempt": att, "reason": note})
                        continue

                    # 等图渲染稳定（关键：延长到 8s，确保 canvas 可读）
                    await asyncio.sleep(8)
                    dest = out_dir / f"{real_idx:03d}_{pname}.png"
                    exp = await export_new_image(c, sid, dest, before_px, before_imgs)
                    if not exp.get("ok"):
                        rec["attempts"].append({"attempt": att, "reason": f"export-{exp.get('reason')}"})
                        continue

                    # 跨轮去重：优先用像素哈希
                    fpx = exp.get("pixel_hash") or exp.get("fingerprint", "")
                    if fpx and fpx in seen_fps:
                        rec["attempts"].append({"attempt": att, "reason": f"dup-content {str(fpx)[:40]}"})
                        log.warning("   ⚠ #%d 命中重复内容，重试", real_idx)
                        continue
                    if fpx:
                        seen_fps.add(fpx)

                    rec.update(success=True, file=exp["path"], width=exp["width"],
                               height=exp["height"], size_mb=exp["size_mb"],
                               duration=round(time.time() - t0, 1),
                               fingerprint=exp.get("fingerprint", ""),
                               pixel_hash=exp.get("pixel_hash", ""))
                    log.info("   ✓ %s (%dx%d, %sMB, 新增%d张)", Path(exp["path"]).name,
                             exp["width"], exp["height"], exp["size_mb"], exp.get("new_count", 0))
                    done = True
                    break
                except Exception as e:
                    rec["attempts"].append({"attempt": att, "reason": f"{type(e).__name__}: {e}"})
                    log.warning("   ✗ %s", e)
                    # 断线重连
                    try:
                        c.stop()
                        await c.ws.close()
                    except Exception:
                        pass
                    c = await connect_live()
                    c.start_heartbeat()
                    try:
                        ok2, _, sid = await try_restore(c, project_url)
                        await c.call("Page.enable", {}, session=sid)
                        log.info("   ↻ 已重连")
                    except Exception as e2:
                        log.error("   重连失败: %s", e2)
                        break

            if not done:
                log.error("   ✗ %s 最终失败", pname)
            report["results"].append(rec)
            report["succeeded"] = sum(1 for x in report["results"] if x.get("success"))
            manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        c.stop()
        report["finished_at"] = datetime.now().isoformat()
        report["succeeded"] = sum(1 for x in report["results"] if x.get("success"))
        report["failed"] = report["total"] - report["succeeded"]
        manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        try:
            c.stop()
            await c.ws.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--name", default="conversation")
    ap.add_argument("--start", type=int, default=1, help="起始序号(1-based, 含)")
    ap.add_argument("--end", type=int, default=None, help="结束序号(1-based, 含)")
    ap.add_argument("--reuse-dir", default=None, help="复用输出目录(断点续跑)")
    ap.add_argument("--reuse-url", default=None, help="复用已有项目 URL(续跑同一对话)")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                    help=f"指定落盘目录(默认已写死: {DEFAULT_OUT_DIR})")
    a = ap.parse_args()
    all_items = json.loads(Path(a.file).read_text(encoding="utf-8"))
    lo = max(1, a.start)
    hi = a.end if a.end else len(all_items)
    items = all_items[lo - 1:hi]
    log.info("=" * 64)
    log.info("单对话连续生成 | 切片 [%d-%d]/%d 条 | 会话名 %s",
             lo, hi, len(all_items), a.name)
    r = asyncio.run(run_conversation(items, a.name, start=lo, end=hi,
                                     reuse_dir=a.reuse_dir, reuse_url=a.reuse_url,
                                     out_dir_root=a.out_dir))
    print("\n" + "=" * 64)
    print(f"成功 {r.get('succeeded',0)} / {r.get('total',0)}")
    for x in r.get("results", []):
        print(f"  {'✓' if x.get('success') else '✗'} {x['name']}"
              + (f" -> {Path(x['file']).name}" if x.get("success") else ""))
    print(f"\n对话目录: {r.get('archive_dir')}")
    print("=" * 64)
    return 0 if r.get("failed", 1) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
