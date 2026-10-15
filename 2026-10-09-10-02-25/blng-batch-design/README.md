# BLNG 批量出图 Skill

> 驱动 BLNG（app.blng.ai）在单个任务内批量生成珠宝 / 钻石 AI 设计图，按序落盘并自动合成「一图一页」演示文稿。

---

## 这个项目解决什么问题

BLNG 是一个在线珠宝与钻石 AI 设计平台，输入一段文字描述就能生成一张设计图。但网页端的交互方式并不适合批量作业：每生成一张都要重新提交描述，出图后还要手动下载、保存、命名。要凑齐几十张款式图，就得把这套动作重复几十遍。

本项目把这段重复劳动接管了。它通过浏览器自动化（Edge CDP）驱动 BLNG 网页端，在一个任务内连续生成多张设计图，按 `序号_款式名.png` 落盘到指定目录，最后一键合成一份「一张图片一页」的演示文稿。

**定位**：半自动产线，不是全无人值守服务。账号登录环节保留人工介入，批量生成、下载、命名、排版则全部自动完成。

---

## 核心能力

| 能力 | 状态 | 说明 |
|---|---|---|
| 单对话连续出图 | ✅ | 设计描述逐条自动提交，在同一任务内累积，不中断 |
| 按序命名落盘 | ✅ | 文件名形如 `001_款式名.png`，三位补零，天然按序号排序 |
| 断点续跑 | ✅ | 已存在且体积大于 1KB 的图片自动跳过，重复跑同一区间安全 |
| 失败自动重试 | ✅ | 检出重复内容时自动重跑该条，无需人工干预 |
| 一图一页演示文稿 | ✅ | 生成后校验页数与每页内嵌图片哈希值，防止图页错配 |
| 大批量一次跑完 | ❌ | 单次运行有时长上限，超量需分批推进 |
| 复用历史任务续跑 | ❌ | 平台会清理免费档项目，续跑必须新开任务 |

**速度参考**：实测约 76 秒 / 张。50 张约 1 小时，250 张约 5.3 小时。因此大批量任务必须**切片执行**。

---

## 环境要求

| 项目 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows | 依赖本机 Edge 的 CDP 调试端口 |
| 浏览器 | Microsoft Edge | 复用本机已安装的 Edge，无需 Chrome / Chromium |
| Python | 3.10 及以上 | 运行全部脚本，需包含 `browser-use` 与 `websockets` |
| Node.js | 18 及以上 | 仅在合成演示文稿时需要 |
| 演示文稿引擎 | `@tencent/slidep` | 合成演示文稿时调用 |
| 网络 | 可直连 BLNG | 若走系统代理，脚本已内置回环排除配置 |

> ⚠️ **代理注意**：系统代理会劫持 `localhost:9222` 导致 502。所有命令建议前置
> `NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY=''`。

---

## 快速开始

### 第一步：安装 Python 依赖

```bash
python -m pip install browser-use websockets
```

> ⚠️ 建议使用独立虚拟环境。若系统 Python 缺少 `websockets`，脚本会报
> `ModuleNotFoundError: No module named 'websockets'`。

### 第二步：填写账号

编辑 `scripts/blng_session.py`，把 `EMAIL` / `PASSWORD` 填成自己的 BLNG 账号：

```python
EMAIL = "your_account@example.com"
PASSWORD = "your_password"
```

也可以通过环境变量注入（优先级更高，不在代码文件中留痕）：

```bash
export BLNG_EMAIL="your_account@example.com"
export BLNG_PASSWORD="your_password"
```

### 第三步：首次登录

```bash
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  python scripts/blng_session.py login
```

登录成功后会话快照写入 `scripts/.blng_session.json`，后续运行自动复用。

### 第四步：准备设计描述清单

清单为 JSON 数组，每项含 `name` 与 `prompt` 两个字段。可自动生成：

```bash
python scripts/gen_prompts.py 300 scripts/design_prompts.json
```

也可以使用自有清单，只要保持字段结构一致。

### 第五步：批量出图

按序号区间切片推进，每批新建项目、全程停留在同一页面：

```bash
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  python scripts/blng_conversation.py \
    --file scripts/design_prompts.json \
    --name design_run \
    --start 1 --end 25
```

跑完一批后接下一批（`--start 26 --end 50`），依此类推。每批 25 张约耗时 25–40 分钟。

### 第六步：合成演示文稿

```bash
python scripts/make_ppt.py --force
```

脚本按自然序读取图片目录，一图一页写入演示文稿，并在生成后校验页数与每页内嵌图片哈希值。

---

## 目录结构

```
blng-batch-design/
├── SKILL.md                  # 主入口：能力边界、工作流、关键要点
├── README.md                 # 本文件
├── .gitignore                # 凭据与运行时产物忽略规则
├── references/
│   ├── setup.md              # 环境准备、凭据填写、首次登录、链路自检
│   └── pitfalls.md           # 20 条踩坑记录与规避方式
└── scripts/
    ├── blng_tool.py          # 浏览器自动化基座
    ├── blng_session.py       # 凭据与会话快照管理
    ├── blng_auto.py          # 登录 / 会话恢复辅助
    ├── blng_conversation.py  # 批量生成器（核心）
    ├── make_ppt.py           # 图片目录 → 一图一页演示文稿
    ├── gen_prompts.py        # 组合式生成设计描述清单
    └── check_projects.py     # 只读检查活跃项目数
```

---

## 脚本说明

| 脚本 | 用途 | 运行方式 |
|---|---|---|
| `blng_tool.py` | 页面导航、元素取值、截图、状态快照 | `python scripts/blng_tool.py snapshot` |
| `blng_session.py` | 凭据与会话快照管理 | `python scripts/blng_session.py login` |
| `blng_auto.py` | 登录 / 会话恢复 | 被其他脚本 import |
| `blng_conversation.py` | **批量生成器** | 见「第五步」 |
| `make_ppt.py` | 目录 → 一图一页演示文稿 | `python scripts/make_ppt.py --force` |
| `gen_prompts.py` | 组合式生成提示词清单 | `python scripts/gen_prompts.py 300 out.json` |
| `check_projects.py` | 只读检查活跃设计文件数 | `python scripts/check_projects.py` |

---

## 可配置项

| 环境变量 | 作用 | 默认值 |
|---|---|---|
| `BLNG_EMAIL` | 账号（优先级高于脚本内配置） | 空 |
| `BLNG_PASSWORD` | 密码（优先级高于脚本内配置） | 空 |
| `BLNG_OUT_DIR` | 图片落盘目录 | `D:\Desktop\新建文件夹 (2)\设计图` |
| `BLNG_PPT_OUT` | 演示文稿输出路径 | `D:\Desktop\新建文件夹 (2)\设计图集.pptx` |
| `BLNG_NODE` | Node.js 可执行文件路径 | 自动探测 |
| `BLNG_EDGE` | Edge 可执行文件路径 | 自动探测 |

> 落盘路径也可以直接通过命令行参数临时覆盖：`blng_conversation.py --out-dir "<路径>"`。

---

## 关键实现要点

改动代码前建议先理解以下几条：

1. **必须走 Edge CDP，不走托管 Chromium** — 本机 Edge + 独立用户目录 `.edge-profile/` 是唯一稳定路径。
2. **必须排除回环代理** — 系统代理会劫持 `localhost:9222` 导致 502。
3. **导航路径固定为「New Design → 点预设卡 `Square 2K 2048×2048px`」** — 不要走 Square → 2K → Start 那套，点预设卡会直接关掉弹窗，后续按钮根本不存在。
4. **取图的唯一可靠来源是 `.overlay` 预览图** — BLNG 编辑区 DOM 虚拟化，同一时刻只挂载 1–2 个 `<img>`。
5. **React 受控输入必须用原生 setter 触发** — 直接赋值 `value` 无效，需配合 `input` / `change` 事件派发。
6. **不要复用旧项目续跑** — 免费档项目会被 BLNG 清理，深链会在 4–5 秒后跳回 `/dashboard`。
7. **单次运行有时长上限** — 长跑会被终止，只能靠 `--start/--end` 切片。

更多踩坑记录见 [`references/pitfalls.md`](references/pitfalls.md)。

---

## 常见问题

**图片保存在哪里？**
默认保存在 `D:\Desktop\新建文件夹 (2)\设计图`，演示文稿与图片目录同级。可用 `--out-dir` 或 `BLNG_OUT_DIR` 变更。

**中途中断了要重新开始吗？**
不需要。重新启动后会跳过已经产出的图片，接着上次进度继续。

**同一批任务可以重复执行吗？**
可以。已存在且体积正常的图片会自动跳过，不会重复产出，也不额外消耗平台额度。

**生成结果会有重复吗？**
偶有发生，工具会检出重复内容并自动重跑该条。

**一次跑多少张合适？**
建议每批 25–50 张。这个区间既能保证在单次运行时长上限内完成，也便于中途检查产出质量。

---

## 安全说明

- ⚠️ 本仓库**不含任何真实账号密码**，`scripts/blng_session.py` 的凭据字段默认为空，需使用方自行填写。
- ⚠️ 运行后会生成 `scripts/.blng_session.json`（含 refreshToken，有效期约 30 天）与 `scripts/.edge-profile/`（浏览器用户目录）。**这两项已在 `.gitignore` 中排除，请勿提交或外发。**
- 若需二次分发，提交前请确认工作区干净：

```bash
git status --ignored
```

---

## 已知限制

- 免费版账号同时最多保留 3 个活跃设计项目，跑批前需先清理。
- 免费档项目存放一段时间后会被平台清理，已开跑的任务不要跨天续跑。
- 生成速度约 76 秒 / 张，产出总量不受限但耗时随张数线性增长。
- 当前仅支持 Windows（依赖本机 Edge 的调试端口）。

---

## 许可

本项目为内部工具，暂未指定开源许可。如需对外发布，请先补充 LICENSE 文件。
