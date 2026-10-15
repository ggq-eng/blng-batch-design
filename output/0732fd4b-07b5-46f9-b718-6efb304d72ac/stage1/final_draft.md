# BLNG 批量出图 Skill 使用说明

> **TL;DR**：本 Skill 用 Edge 浏览器自动化驱动 BLNG（app.blng.ai），在**一个对话内连续生成多张**珠宝/钻石设计图，按序号自动落盘到指定目录，最后一键合成「一张图片一页」的 PPT。填好账号密码、登录一次，之后跑批就是一条命令的事。

---

## 一、这个 Skill 能做什么

本 Skill 把「BLNG 网页端手工出图」沉淀为可复用的自动化管线，核心能力如下。

| 能力 | 状态 | 说明 |
|---|---|---|
| 单对话连续出图 | ✅ 支持 | 提示词逐条提交，在同一项目内累积生成 |
| 按序命名落盘 | ✅ 支持 | 文件名格式 `{序号:03d}_{款式名}.png`，如 `001_design_001.png` |
| 断点续跑 | ✅ 支持 | 目录内已存在且大于 1KB 的图片自动跳过，重复跑同一区间是安全的 |
| 一图一页 PPT | ✅ 支持 | 自动生成，并校验页数与每页内嵌图片 MD5 |
| 免费版突破单日总量 | ❌ 不支持 | 免费版无每日上限，但同时仅允许 3 个活跃设计文件 |
| 跨对话复用旧项目续跑 | ❌ 不支持 | BLNG 会清理免费档旧项目，续跑须新开项目 |

**速度参考**：实测约 **76 秒 / 张**。50 张约 1 小时，250 张约 5.3 小时。因此大批量任务必须**切片执行**（见第六节）。

---

## 二、前置要求

### 2.1 环境清单

| 项 | 要求 | 用途 |
|---|---|---|
| 操作系统 | Windows | 依赖本机 Edge 的调试端口 |
| 浏览器 | Microsoft Edge | 无需 Chrome/Chromium，直接复用本机 Edge |
| Python | 3.10 及以上 | 运行全部脚本 |
| Node.js | 18 及以上 | 仅在合成 PPT 时需要 |
| PPT 引擎 | `@tencent/slidep` | 合成 PPT 时需要 |
| 网络 | 可直连 BLNG | 若走系统代理，脚本已内置回环地址排除 |

### 2.2 依赖安装

Python 依赖安装到受管虚拟环境：

```bash
PY=/c/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe
"$PY" -m pip install browser-use websockets
```

> ⚠️ **必须使用上述虚拟环境解释器运行脚本**，不要使用系统自带的 `python`。系统 Python 缺少 `websockets` 模块，执行时会报错：
> `ModuleNotFoundError: No module named 'websockets'`
>
> 本文后续所有 `python xxx.py` 命令，均请理解为 `"$PY" xxx.py`。

确认 PPT 引擎可用：

```bash
node -e "console.log(require.resolve('@tencent/slidep/dist/index.js'))"
```

若提示找不到模块，请执行 `npm install -g @tencent/slidep` 安装。

### 2.3 文档信息

- **适用读者**：具备基本命令行操作能力的技术人员或运营人员
- **前置知识**：命令行基础、文本编辑器基本操作
- **涉及版本**：Python 3.13.12、Node.js 22.22.2、Microsoft Edge
- **预计阅读时间**：约 10 分钟；首次完整跑通约 15 分钟

---

## 三、Step 1：填写账号密码

凭据文件位于 `scripts/blng_session.py`。该文件交付时**账号密码为空**，需使用者自行填写。

打开后找到如下片段：

```python
# ============================================================
#  凭据配置 —— 使用前请填写你自己的 BLNG 账号
# ============================================================
# 方式一（推荐）：直接填写下面两行
EMAIL = ""
PASSWORD = ""
# 方式二：设置环境变量 BLNG_EMAIL / BLNG_PASSWORD（优先级高于上面的填写）
```

**方式一：直接填写**

把 `EMAIL` 与 `PASSWORD` 填成自己的 BLNG 账号：

```python
EMAIL = "你的账号@example.com"
PASSWORD = "你的密码"
```

**方式二：环境变量**

保持文件内为空，运行时注入：

```bash
export BLNG_EMAIL="你的账号@example.com"
export BLNG_PASSWORD="你的密码"
```

> ⚠️ 环境变量优先级**高于**文件内填写；两者同时设置时，以环境变量为准。
> ⚠️ 请勿将填好真实密码的 `blng_session.py` 提交到公开仓库或对外分享。

**预期结果**：文件中 `EMAIL` / `PASSWORD` 已填入有效值，或环境变量已设置。

---

## 四、Step 2：首次登录

登录会把认证态落盘为会话快照，之后跑批自动注入，**无需重复登录**。

```bash
cd <skill>/scripts
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  "$PY" blng_session.py login
```

**预期输出**：

```json
{ "ok": true, "url": "https://app.blng.ai/dashboard", "logged_in": true }
```

脚本执行过程：后台拉起 Edge（调试端口 9222，独立用户目录 `.edge-profile/`）→ 自动填写邮箱密码并提交 → 导出会话到 `scripts/.blng_session.json`。

检查登录态（不重新登录）：

```bash
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  "$PY" blng_session.py status
```

返回 `"logged_in": true` 即为就绪。

> ⚠️ 所有命令**必须**带上 `NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY=''` 前缀。系统代理会劫持本地调试端口，导致连接失败（502）。

---

## 五、Step 3：链路自检

首次使用建议先跑 3 张图，验证整条链路。

**第 1 步**：生成一份小的提示词清单（5 条）。

```bash
"$PY" gen_prompts.py 5 design_prompts.json
```

**预期输出**：`生成 5 条 -> design_prompts.json`

**第 2 步**：检查账号当前的活跃设计文件数。

```bash
"$PY" check_projects.py
```

**预期输出**：显示当前活跃设计文件数与方案上限（免费版上限为 3）。

**第 3 步**：跑 3 张图。

```bash
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  "$PY" blng_conversation.py --file design_prompts.json --name smoke --start 1 --end 3
```

**预期结果**：约 4 分钟后，到 `D:\Desktop\新建文件夹 (2)\设计图` 目录下查看，应出现：

```
001_design_001.png
002_design_002.png
003_design_003.png
```

出现这三张图，说明整条链路已打通。

---

## 六、Step 4：批量出图（核心步骤）

### 6.1 准备完整提示词清单

```bash
"$PY" gen_prompts.py 300 design_prompts.json
```

该脚本按「10 品类 × 10 宝石 × 3 金属」组合生成 300 条珠宝设计提示词。也可使用自己的清单，只需保持如下字段结构：

```json
[
  { "name": "design_001", "prompt": "an engagement ring featuring a round brilliant-cut diamond ..." }
]
```

### 6.2 切片跑批

按序号窗口分批推进。以下示例跑第 1 至第 50 张：

```bash
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  "$PY" blng_conversation.py \
    --file design_prompts.json \
    --name design_run \
    --start 1 --end 50
```

> **落盘目录已写死**为 `D:\Desktop\新建文件夹 (2)\设计图`，无需再传 `--out-dir`。

**预期输出**（节选）：

```
[1/50] (#1) design_001
   click[New Design] ✓
   生成中... ✓
   ✓ 已保存 001_design_001.png
...
[50/50] (#50) design_050
   ✓ 已保存 050_design_050.png
```

**预期结果**：`D:\Desktop\新建文件夹 (2)\设计图` 下累积 50 张图片，并生成 `manifest.json` 记录出图明细。

### 6.3 关于切片大小

受执行环境限制，**单次命令超过 10 分钟会被中断**。建议按以下档位推进：

| 单档张数 | 预计耗时 | 说明 |
|---|---|---|
| 25 | 约 32 分钟 | 稳妥档位 |
| 50 | 约 64 分钟 | 常用档位，接近上限 |

更大批量请按 50 一档递进：跑完 `1-50`，再跑 `51-100`，以此类推。

> ⚠️ **不要复用旧项目续跑**。免费档项目会被 BLNG 清理，深链会在数秒后跳回首页导致失败。每档请新开项目，让脚本从首页自动新建入口进入。

> 💡 目录内已存在且大于 1KB 的图片会自动跳过。因此**重复执行同一区间不会重复消耗额度**，中断后直接重跑该档即可。

---

## 七、Step 5：合成 PPT

```bash
"$PY" make_ppt.py --force
```

> **参数已写死默认**：读取目录 `D:\Desktop\新建文件夹 (2)\设计图`，输出文件 `D:\Desktop\新建文件夹 (2)\设计图集.pptx`。

**预期输出**：

```json
{ "ok": true, "slides": 50, "images": 50, "failed": [] }
```

**预期结果**：生成 `设计图集.pptx`，共 50 页，**每个页面放置一张图片**，页面版式为：白色背景、图片居中、右下角显示页码（格式如 `01/50`）。

脚本会在生成后自动校验页数与每页内嵌图片的 MD5，不通过则报错。

---

## 八、参数速查

### blng_conversation.py

| 参数 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `--file` | 是 | — | 提示词清单 JSON 路径 |
| `--name` | 否 | `conversation` | 任务名，用于日志与目录标识 |
| `--start` | 否 | `1` | 起始序号（含） |
| `--end` | 否 | 到清单末尾 | 结束序号（含） |
| `--out-dir` | 否 | `D:\Desktop\新建文件夹 (2)\设计图` | 图片落盘目录 |
| `--reuse-dir` | 否 | — | 显式复用输出目录 |
| `--reuse-url` | 否 | — | 复用项目 URL（仅同一次会话内有效） |

### make_ppt.py

| 参数 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `--dir` | 否 | `D:\Desktop\新建文件夹 (2)\设计图` | 图片目录 |
| `--out` | 否 | `D:\Desktop\新建文件夹 (2)\设计图集.pptx` | 输出 PPT 路径 |
| `--force` | 否 | 关闭 | 强制重建，覆盖已有 PPT |

### 路径覆盖方式

如需临时改用其他目录，可用命令行参数覆盖：

- 图片目录：`--out-dir "<其他路径>"`
- PPT 输入目录：`--dir "<其他路径>"`
- PPT 输出文件：`--out "<其他路径>.pptx"`

也可设置环境变量 `BLNG_OUT_DIR`（图片目录）与 `BLNG_PPT_OUT`（PPT 输出）。

---

## 九、关键约束与避坑（必读）

1. **必须排除回环代理**。所有联网命令都要加 `NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY=''` 前缀。

2. **单次命令 10 分钟上限**。大批量必须切片，否则会被中断。

3. **不要复用旧项目**。每档新开项目，中断后重跑同档即可（已完成的图会自动跳过）。

4. **免费版同时仅 3 个活跃设计文件**。跑批前可用 `check_projects.py` 核对；若已占满，先到网页端清理，或使用付费账号。

5. **会话有效期**。登录态中 accessToken 约 1 小时过期、refreshToken 约 30 天。脚本每次跑批前会自动检查：有效则复用，失效则用凭据重新登录。

6. **运行时文件包含凭证**。`scripts/.blng_session.json` 内含登录令牌，`scripts/.edge-profile/` 内含浏览器登录状态。二次分发前请删除这两个路径。

---

## 十、常见问题 FAQ

**Q1：执行脚本报错 `ModuleNotFoundError: No module named 'websockets'`？**

使用了错误的 Python 解释器。请改用受管虚拟环境的解释器：

```bash
/c/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe
```

**Q2：登录或跑批时报连接失败（502）？**

未排除系统代理。请在命令前加上 `NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY=''`。

**Q3：`status` 显示 `logged_in: false`？**

会话已失效。重新执行一次 `blng_session.py login` 即可。

**Q4：跑批中途中断了，需要从头再来吗？**

不需要。直接重跑同一档区间即可，已生成且大于 1KB 的图片会被自动跳过。

**Q5：合成 PPT 报错找不到 node 或引擎？**

请确认已安装 Node.js 18 以上版本及 `@tencent/slidep`。也可通过环境变量 `BLNG_NODE` 指定 node 路径。

**Q6：生成的图片有重复内容？**

脚本内置像素哈希去重，命中重复会自动重试。若重试后仍重复，属模型输出的偶发情况，可单独重跑该序号。

**Q7：可以修改落盘目录吗？**

可以。使用 `--out-dir` 参数覆盖，或设置环境变量 `BLNG_OUT_DIR`。

---

## 十一、目录结构说明

| 路径 | 用途 |
|---|---|
| `scripts/blng_session.py` | 凭据与会话管理，**使用前需填写账号密码** |
| `scripts/blng_conversation.py` | 主生成器，单对话批量出图 |
| `scripts/make_ppt.py` | 目录转 PPT，含 MD5 校验 |
| `scripts/gen_prompts.py` | 批量生成提示词清单 |
| `scripts/check_projects.py` | 检查活跃设计文件数 |
| `scripts/.blng_session.json` | 会话快照（含令牌，勿外传） |
| `scripts/.edge-profile/` | Edge 独立用户目录 |
| `D:\Desktop\新建文件夹 (2)\设计图` | 图片落盘目录（默认） |
| `D:\Desktop\新建文件夹 (2)\设计图集.pptx` | PPT 输出文件（默认） |
