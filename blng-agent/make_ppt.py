"""
make_ppt.py —— 图片文件夹 -> 一图一页 PPT（自动批量）
========================================================
需求(B方案第二步): 把某个目录下的所有图片，按篮球那款版式
(白底 + 居中大图 + 右下页码) 自动生成一份 .pptx。

设计要点:
  1. 自然排序图片名(01,02,...,100 而非 1,10,100)
  2. 复用 slidep 引擎真身(命令行 shim 路径写错, 见 _engine() 注释)
  3. 每页: 写 .slide -> lint -> upsert-dsl; 全 ok 才继续
  4. 出稿后校验: 页数 == 图片数, 且逐页嵌入图 MD5 == 源文件 MD5
  5. 支持断点续跑: 已存在的 slide 文件不重写(除非 --force)

复杂度: O(N * L)，N=图片数，L=单页编译；串行。
用法:
  python make_ppt.py --dir "D:\\...\\设计图" --out "D:\\...\\设计图.pptx"
  python make_ppt.py --dir ./imgs --out ./out.pptx --title "设计图集"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("make_ppt")

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# 引擎真身位置(命令行 shim 检查的是 node_modules/, 实际在 lib/node_modules/)
NODE_EXE = r"C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-6\node.exe"
ENGINE = (r"C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-6"
          r"\lib\node_modules\@tencent\slidep\dist\index.js")


def _natural_key(p: Path):
    """自然排序: 把数字段按数值比较。"""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", p.stem)]


def _engine() -> tuple[str, str]:
    """定位 slidep 引擎。shim 走 node_modules/ 会误报"引擎未就绪"，故直连真身。"""
    if Path(NODE_EXE).exists() and Path(ENGINE).exists():
        return NODE_EXE, ENGINE
    # 回退: 动态搜索
    root = Path(NODE_EXE).parent
    for cand in (root / "lib/node_modules/@tencent/slidep/dist/index.js",
                 root / "node_modules/@tencent/slidep/dist/index.js"):
        if cand.exists():
            return NODE_EXE, str(cand)
    raise FileNotFoundError(f"找不到 slidep 引擎: {ENGINE}")


def _run(node: str, engine: str, args: list[str], timeout: int = 120) -> dict:
    """调用引擎并解析 JSON 输出。复杂度 O(1)。"""
    cmd = [node, engine, *args]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    out = (p.stdout or "").strip()
    # 引擎会混入 DeprecationWarning 等噪声，取最后一行合法 JSON
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"ok": False, "error": f"no-json (rc={p.returncode})",
            "stderr": (p.stderr or "")[-400:], "stdout": out[-400:]}


def _make_slide(img_rel: str, page: int, total: int) -> str:
    """生成单页 DSL: 白底 + 居中图(objectFit contain) + 右下页码。"""
    return (
        "<Slide style={{ width: 1280, height: 720, backgroundColor: '#FFFFFF', "
        "position: 'relative', display: 'flex', alignItems: 'center', "
        "justifyContent: 'center' }}>\n"
        f'    <Image src="{img_rel}" style={{{{ width: 600, height: 600, '
        "objectFit: 'contain' }} />\n"
        "    <Text style={{ position: 'absolute', right: 40, bottom: 28, "
        f"fontSize: 16, color: '#9CA3AF' }}}}>{page:02d}/{total:02d}</Text>\n"
        "</Slide>\n"
    )


def _md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def build(img_dir: Path, out_pptx: Path, title: str, force: bool = False) -> dict:
    """主流程。返回 {ok, slides, images, failed[]}。"""
    if not img_dir.is_dir():
        return {"ok": False, "error": f"目录不存在: {img_dir}"}

    imgs = sorted([p for p in img_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in IMG_EXT], key=_natural_key)
    if not imgs:
        return {"ok": False, "error": f"目录内无图片: {img_dir}"}
    log.info("发现 %d 张图片", len(imgs))

    node, engine = _engine()
    proj = out_pptx.parent
    assets = proj / "assets"
    slides_dir = proj / "slides"
    assets.mkdir(parents=True, exist_ok=True)
    slides_dir.mkdir(parents=True, exist_ok=True)

    # 1) 复制图片到 assets(英文安全名) 并建立映射
    mapping = []  # (asset_name, src_path)
    for i, p in enumerate(imgs, 1):
        safe = f"{i:03d}_{re.sub(r'[^0-9A-Za-z_]', '_', p.stem)}"
        ext = p.suffix.lower()
        asset = assets / f"{safe}{ext}"
        if force or not asset.exists() or _md5(asset.read_bytes()) != _md5(p.read_bytes()):
            shutil.copy2(p, asset)
        mapping.append((asset.name, p))
    total = len(mapping)

    # 2) 建空白 pptx
    if out_pptx.exists() and force:
        out_pptx.unlink()
    if not out_pptx.exists():
        r = _run(node, engine, ["create", str(out_pptx)])
        if not r.get("ok"):
            return {"ok": False, "error": f"create 失败: {r}"}
        log.info("已创建 %s", out_pptx.name)

    # 3) 逐页 写 -> lint -> upsert
    failed = []
    for i, (asset_name, src) in enumerate(mapping, 1):
        slide_file = slides_dir / f"{i:03d}.slide"
        if force or not slide_file.exists():
            slide_file.write_text(
                _make_slide(f"assets/{asset_name}", i, total), encoding="utf-8")

        lint = _run(node, engine, ["lint", str(out_pptx), "--dsl-file", str(slide_file)])
        if not lint.get("ok"):
            failed.append({"page": i, "stage": "lint", "err": lint})
            log.error("   ✗ 第 %d 页 lint 失败: %s", i, lint.get("error"))
            continue

        up = _run(node, engine, ["upsert-dsl", str(out_pptx), "--dsl-file", str(slide_file)],
                  timeout=180)
        if not up.get("ok"):
            failed.append({"page": i, "stage": "upsert", "err": up})
            log.error("   ✗ 第 %d 页 写入失败: %s", i, up.get("error"))
            continue
        if i % 10 == 0 or i == total:
            log.info("   ✓ 已写入 %d/%d 页", i, total)

    # 4) 校验: 页数 + 逐页嵌入图 MD5
    verify = {"slides": 0, "media_match": 0, "mismatch": []}
    try:
        with zipfile.ZipFile(out_pptx) as z:
            sl = sorted(n for n in z.namelist()
                        if re.match(r"ppt/slides/slide\d+\.xml$", n))
            verify["slides"] = len(sl)
            for i in range(1, len(mapping) + 1):
                try:
                    rels = z.read(f"ppt/slides/_rels/slide{i}.xml.rels").decode()
                    m = re.search(r"media/(image\d+\.\w+)", rels)
                    if not m:
                        verify["mismatch"].append({"page": i, "why": "no-media-ref"})
                        continue
                    data = z.read(f"ppt/slides/media/{m.group(1)}")
                    if _md5(data) == _md5(mapping[i - 1][1].read_bytes()):
                        verify["media_match"] += 1
                    else:
                        verify["mismatch"].append({"page": i, "why": "md5-diff"})
                except Exception as e:
                    verify["mismatch"].append({"page": i, "why": f"{type(e).__name__}"})
    except Exception as e:
        verify["error"] = f"{type(e).__name__}: {e}"

    ok = (not failed) and verify["slides"] == total \
        and verify["media_match"] == total and not verify["mismatch"]
    return {"ok": ok, "out": str(out_pptx), "images": total,
            "failed": failed, "verify": verify}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="图片目录")
    ap.add_argument("--out", required=True, help="输出 .pptx 路径")
    ap.add_argument("--title", default="图片集", help="(保留)")
    ap.add_argument("--force", action="store_true", help="强制重建(覆盖)")
    a = ap.parse_args()

    r = build(Path(a.dir), Path(a.out), a.title, force=a.force)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
