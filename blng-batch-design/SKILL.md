---
name: blng-batch-design
description: 驱动 BLNG（app.blng.ai）在单个对话内批量生成珠宝/钻石 AI 设计图并按序落盘、自动合成一图一页 PPT。当用户要求「批量出图」「一次对话生成 N 张设计图」「把设计图存到某目录并生成 PPT」，或提到 BLNG、珠宝设计图、款式图批量产出时使用。适用场景：电商选品图、款式库扩充、设计灵感批量出稿、详情页素材生产。
agent_created: true
---

# BLNG 批量珠宝设计出图管线

## 概览

本 skill 通过 Edge CDP 驱动 BLNG 网页端，在**一个对话任务内连续生成多张**设计图，按 `序号_款式名.png` 落盘到指定目录，最后合成一份「一张图片一页」的 PPT。整条链路为半自动：账号登录一次、期间人工可介入，其余提交提示词、等待出图、下载归档、合成 PPT 全自动。

**能力边界（务必先读）**：

| 能力 | 状态 | 说明 |
|---|---|---|
| 单对话连续出图 | ✅ | 提示词逐条提交，同一对话内累积 |
| 按序命名落盘 | ✅ | `{序号:03d}_{款式名}.png` |
| 断点续跑 | ✅ | 跳过已存在且 >1KB 的文件 |
| 一图一页 PPT | ✅ | 含张数与内嵌图片 MD5 双重校验 |
| 免费版突破单日总量 | ❌ | 免费版**无每日上限**，但**同时仅 3 个活跃设计文件** |
| 跨对话/复用旧项目续跑 | ❌ | BLNG 会清理免费档旧项目，续跑必须新开项目 |

> 速度参考：约 **76–95 秒/张**。50 张 ≈ 1 小时，250 张 ≈ 5.3 小时。
> 因此大批量务必用 `--start/--end` **切片跑**，规避单次工具调用 10 分钟超时。

---

## 首次使用

**必须先完成凭据填写与登录**，详见 [`references/setup.md`](references/setup.md)。核心就一步：编辑 `scripts/blng_session.py`，把 `EMAIL` / `PASSWORD` 填成自己的 BLNG 账号（或改用 `BLNG_EMAIL` / `BLNG_PASSWORD` 环境变量），然后跑一次：

```bash
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  python scripts/blng_session.py login
```

> 凭据默认为**空**，交付时不含任何真实账号密码，需使用方自行填写。

---

## 批量出图工作流

### 步骤 1 — 准备提示词清单

清单为 JSON 数组，每项 `{"name": ..., "prompt": ...}`。可用脚本批量生成珠宝类提示词：

```bash
python scripts/gen_prompts.py 300 scripts/design_prompts.json
```

也可用用户自己的清单，只要保持字段结构一致。

### 步骤 2 — 确认账号容量

免费版同时仅允许 3 个活跃设计文件，跑批前先核对：

```bash
python scripts/check_projects.py
```

若已占用满，先到网页端清理，或改用付费档账号。

### 步骤 3 — 切片跑批（核心）

**每批新建项目、留在本页、不跨对话**。按序号窗口推进：

```bash
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  python scripts/blng_conversation.py \
    --file scripts/design_prompts.json \
    --name design_run \
    --start 1 --end 25
```

> **落盘目录已写死**为 `D:\Desktop\新建文件夹 (2)\设计图`，无需再传 `--out-dir`。
> 需要临时改到别处，才用 `--out-dir "<其他路径>"` 覆盖，或设环境变量 `BLNG_OUT_DIR`。

| 参数 | 说明 |
|---|---|
| `--file` | 提示词清单 JSON（必填） |
| `--name` | 任务名，用于日志与目录标识 |
| `--start` / `--end` | 序号窗口（1-based，含端点），用于切片 |
| `--out-dir` | 落盘目录，**默认已写死** `D:\Desktop\新建文件夹 (2)\设计图` |
| `--reuse-dir` | 显式复用输出目录（优先级高于默认，一般不用） |
| `--reuse-url` | 复用已有项目 URL（**仅同一次会话内有效**） |

25 张约 25–40 分钟；更大批量按 25 或 50 一档递进，每档跑完再起下一档。
目录内已存在且 >1KB 的图会自动跳过，因此**重复跑同一区间是安全的**。

### 步骤 4 — 合成 PPT

```bash
python scripts/make_ppt.py --force
```

> `--dir` 与 `--out` **均已写死默认**：
> 读图目录 `D:\Desktop\新建文件夹 (2)\设计图`，输出 `D:\Desktop\新建文件夹 (2)\设计图集.pptx`。
> `--force` 表示覆盖重建（改了图片或想重排页码时加）。
> 需要改路径才用 `--dir` / `--out` 覆盖，或设 `BLNG_OUT_DIR` / `BLNG_PPT_OUT`。

脚本会按自然序读取目录内全部图片，一图一页写入，并在生成后**校验页数与每页内嵌图片 MD5**，不通过则报错。

---

## 关键实现要点

以下几条是本管线的命门，改动前务必理解：

1. **必须走 Edge CDP，不走托管 Chromium。** 本机 Edge + 独立用户目录 `.edge-profile/` 是唯一稳定路径。

2. **必须排除回环代理。** 系统代理会劫持 `localhost:9222` 导致 502。所有命令前置：
   `NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY=''`

3. **导航路径固定为「New Design → 点预设卡 `Square 2K 2048×2048px`」。** 不要走 Square → 2K → Start 那套，点预设卡会直接关掉弹窗，后续按钮根本不存在。

4. **取图的唯一可靠来源是 `.overlay` 预览图。** BLNG 编辑区 DOM 虚拟化，同一时刻只挂载 1–2 个 `<img>`；新一轮成品会以 `class` 含 `overlay` 的 `<img>` 出现。脚本以此为主策略，像素哈希与 src 差异仅作兜底。

5. **React 受控输入**必须用原生 setter 触发：
   `Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set` + dispatch `input`/`change`，直接赋 `value` 无效。

6. **不要复用旧项目续跑。** 免费档项目会被 BLNG 清理，深链会在 4–5 秒后跳回 `/dashboard`。正确做法是每批新开项目并留在页内。

7. **单次工具调用 10 分钟上限。** 长跑会被 SIGTERM，只能靠 `--start/--end` 切片。

更多踩坑记录（共 19 条，含沙箱回收子进程、PPT 引擎路径、假告警辨析等）见 [`references/pitfalls.md`](references/pitfalls.md)。

---

## 资源清单

### scripts/

| 脚本 | 作用 | 运行方式 |
|---|---|---|
| `blng_tool.py` | 浏览器自动化基座（导航/取值/eval/截图/快照） | `python blng_tool.py <start\|snapshot\|doctor>` |
| `blng_session.py` | 凭据 + 会话快照管理 | `python blng_session.py <login\|status>`；**使用前填账号密码** |
| `blng_auto.py` | 登录/会话恢复辅助 | 被其他脚本 import |
| `blng_conversation.py` | **主生成器**，单对话批量出图 | 见步骤 3 |
| `make_ppt.py` | 目录 → 一图一页 PPT（含 MD5 校验） | `python make_ppt.py --dir .. --out ..` |
| `gen_prompts.py` | 组合式生成珠宝提示词清单 | `python gen_prompts.py <N> <out.json>` |
| `check_projects.py` | 只读检查活跃设计文件数 | `python check_projects.py` |

### references/

| 文件 | 内容 |
|---|---|
| `setup.md` | 环境准备、凭据填写、首次登录、链路自检 |
| `pitfalls.md` | 19 条踩坑记录与规避方式 |

### assets/

空。本 skill 不依赖外部资源文件；PPT 由引擎即时合成。
