# BLNG 自动化踩坑手册（务必先读）

本文档记录在 app.blng.ai 上做批量生成时踩过的所有坑及已验证的解法。
**跳过本文档会重复浪费时间排障。**

---

## 一、环境类

### 1. 不要下载 Chromium，直接用本机 Edge
`browser-use` 自带的 Chromium 下载在国内经常卡住（89MB 超时）。
方案：复用本机 Edge + CDP。`blng_tool.ensure_edge()` 已实现。

### 2. 系统代理会劫持本地回环 → 502
若环境有 `HTTP_PROXY`，它会劫持 `127.0.0.1:9222` 导致 CDP 报 502。
**必须在导入任何网络库之前**设置：
```bash
NO_PROXY=localhost,127.0.0.1,::1,0.0.0.0
HTTP_PROXY= HTTPS_PROXY=
```
`blng_tool.py` 顶部已自动写入 `NO_PROXY`。

### 3. 沙箱/宿主会回收子进程
- `nohup ... &`、PowerShell `Start-Process` 启动的后台进程，**在工具调用结束后会被回收**。
- `schtasks` 通常被安全策略拉黑。
- **结论：长任务只能在同一条命令内前台跑完，或依赖平台的背景任务机制。**

---

## 二、页面导航类

### 4. 冷启动点 "New Design" 会弹模态框
点 `New Design` 后弹出 **"Set the canvas size"** 弹窗，内含：
- Presets（`Square 2K 2048 × 2048px` 等卡片）
- Resolution（HD / 2K / 4K / Custom）
- Aspect ratio（Square / Landscape / Portrait）
- Cancel / Start

**正确做法：直接点预设卡片 `Square 2K 2048×2048px` → 模态框立即关闭并进入编辑器。**

### 5. 【高频坑】点了 Square 后 2K / Start 点不到
因为点预设卡片已经**确认尺寸并关闭弹窗**，后续按钮根本不存在。
**不要再点 `Square` / `2K` / `Start`。**

### 6. 用轮询点击，不要用固定 sleep
SPA 渲染有延迟，固定 `sleep` 会错过刚渲染出来的按钮 → `fill-not-found`。
用 `click_wait()`（轮询点击）与 `wait_textarea()`（轮询等编辑器）。

### 7. 【致命】项目会被清理，不能复用旧项目
- 免费版项目可能**在几十分钟内被清理**。
- 复用（深链 `/design/<id>`）到已删除的项目时，页面加载 4-5 秒后**自动跳回 `/dashboard`**，导致填词时 textarea 消失 → 全批 `fill-not-found`。
- **结论：不要用 `--reuse-url` 复用很久以前的项目。**
  应让脚本**新建专用项目并全程停在页面内连续出图**（不离开页面就不会被踢）。

---

## 三、图片导出类

### 8. 生成完成的判定不能靠文本
页面残留的历史文本会让正则误判"已完成"（曾出现 11 秒假完成）。
**正确判据：对话轮次计数增加 或 图片数量增加。**

### 9. 【最顽固】导出必须取 `class` 含 `overlay` 的预览图
BLNG 编辑器 **DOM 是虚拟化的**，同时只挂载 1-2 张 `<img>`；新图完成后会出现一张
`class` 含 `overlay` 的大图 = 当前聚焦设计。

错误做法（都踩过）：
- ❌ 取 `imgs[imgs.length-1]` → 永远最后一张
- ❌ src 指纹差集 → 同图不同 blob URL 认不出来
- ❌ "取 DOM 最后一个新增" → 会抓到上一轮的旧图

**正确做法：优先直接取 `.overlay` 图；失败再回退像素指纹差集（32×32 采样）。**

### 10. 去重必须用内容（像素）哈希，且要视觉复核
同一张图二次编码后 MD5 会不同 → 单纯 MD5 去重**会漏掉重复内容**。
- 用 `snapshot_pixels()` 做像素哈希跨轮去重。
- **出图后仍要抽查若干张**：哈希唯一 ≠ 内容正确（曾出现"哈希不同但图片抓错"）。
- 批量产出最终校验：`md5sum *.png | awk '{print $1}' | sort -u | wc -l` 应等于总数。

### 11. 本地产出为 canvas 二次编码 PNG
可能非无损；免费账号云端原图仅在当前会话内有效。需要无损原图请在页面内另存或升级账号。

---

## 四、配额与产能

### 12. 免费版有 3 个 active design file 上限
- 超出后无法新建项目（必须归档/删除旧项目）。
- 免费版还有：24 小时设计历史、仅限个人非商业用途。

### 13. 免费版**没有每日生成上限**
官方 FAQ 明确：限制是"并发（how much runs at once）"，**不是 daily cap**。
所以产量只受时间约束。

### 14. 单张耗时 16~252 秒，波动极大
实测均值约 **70~95 秒/张**（免费版排队 + 偶发重试）。
规划口径：**1 小时约 40~50 张**。

### 15. 单条命令有 10 分钟上限
所以必须**分批**：每批 4-8 张；配合 `--start/--end` 切片与
**已存在则跳过（skip-existing）**实现断点续跑。

---

## 五、PPT 生成类

### 16. 命令行 `slidep` shim 路径写错
shim 检查 `node_modules/@tencent/slidep`，但引擎实际在 **`lib/node_modules/@tencent/slidep`**，
所以 shim 永远报"引擎未就绪（正在下载 56MB）"——**这是假消息，引擎早就装好了**。
`make_ppt.py` 的 `_engine()` 已直连引擎真身。

### 17. slidep 把图片放在 `ppt/slides/media/`（非标准 `ppt/media/`）
查 `ppt/media/` 为空**是正常的**，不要误判为"图片没嵌入"。
校验图↔页映射：读 `ppt/slides/_rels/slideN.xml.rels` 取 `media/imageX.png`，逐张比对 MD5。

### 18. `slidep screenshot` 子命令有内部路径 bug
传入非法的 `file:///workspace/...` 导致渲染失败。**无法用它出预览图**，
改用解压 XML + MD5 的方式校验。

### 19. 幻灯片画布固定 1280×720
每页 = 一个 `{NN}.slide`（受限 DSL，**不是 React**：禁止 import/export/hooks）。
流程固定为：写 slide → `lint` → `upsert-dsl`，全部 `ok:true` 才算成功。

### 20. 运行时产物含活凭据 —— 二次分发前必须清理
运行一次 `login` 后，`scripts/` 下会生成：

- `.blng_session.json` —— **含 accessToken / idToken / refreshToken，refreshToken 有效期约 30 天**，等同于账号的长期钥匙；
- `.edge-profile/` —— 浏览器用户目录，内含登录 Cookie；
- `screenshots/`、`design_prompts.json` 等调试产物。

**这些文件不在交付包内**（打包脚本只收 `SKILL.md` + `references/` + `scripts/*.py`），
但如果你在登录后**重新打包整个目录**，它们会被一并收进去，造成凭据泄漏。

> 二次分发前的清理清单：
> ```bash
> rm -f  scripts/.blng_session.json
> rm -rf scripts/.edge-profile scripts/screenshots
> grep -rn "2267154782\|你的密码" .   # 应为 0 命中
> ```
> 清理后需重新登录（`python scripts/blng_session.py login`）才能继续跑批。
