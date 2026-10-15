# 🎨 BLNG 批量出图 Skill — 珠宝/钻石 AI 设计图批量生产管线

> 驱动 [BLNG](https://app.blng.ai)（AI 珠宝设计平台）在单个对话内**连续批量生成**设计图，按序落盘、自动去重、一键合成「一图一页」演示文稿。
> 本仓库同时收录了该工具从 0 到 1 的**完整开发工作快照**（脚本 · 日志 · 产出图集 · 文档）。

![Platform](https://img.shields.io/badge/platform-Windows-blue) ![Python](https://img.shields.io/badge/python-3.10%2B-green) ![Node](https://img.shields.io/badge/node-18%2B-green) ![Automation](https://img.shields.io/badge/automation-Edge%20CDP-orange) ![Status](https://img.shields.io/badge/status-%E5%B7%B2%E9%AA%8C%E8%AF%81%E4%BA%A7%E7%BA%BF-brightgreen)

---

## 📖 这个项目解决什么问题

BLNG 是一个在线珠宝与钻石 AI 设计平台，输入文字描述即可生成设计图。但网页端**一次只能生成一张**，出图后还要手动下载、保存、命名——凑齐几十张款式图，就得把这套动作重复几十遍。

本项目把这段重复劳动自动化了：

```
提示词清单 (JSON)
      │
      ▼
┌─────────────────────────────┐
│  Edge CDP 浏览器自动化        │  登录 → New Design → 预设卡 2K
│  逐条提交 · 等待出图 · 拦截下载  │  .overlay 预览图截取（DOM 虚拟化对策）
└─────────────────────────────┘
      │
      ▼
图片按 001_款式名.png 落盘  ──断点续跑──▶  跳过已有，接着上次跑
      │
      ▼
make_ppt.py ──▶ 一图一页 PPTX（页数 + 内嵌图 MD5 双重校验）
```

**定位**：半自动产线——账号登录保留人工介入，批量生成、下载、命名、排版全部自动。

---

## ✨ 核心能力

| 能力 | 状态 | 说明 |
|---|---|---|
| 单对话连续出图 | ✅ | 提示词逐条自动提交，同一对话内累积，不中断 |
| 按序命名落盘 | ✅ | `{序号:03d}_{款式名}.png`，三位补零，百张以上也不错序 |
| 断点续跑 | ✅ | 已存在且 >1KB 的图自动跳过，重复执行同一区间安全 |
| 失败自动重试 | ✅ | 检出重复内容自动重跑该条，无需人工干预 |
| 一图一页 PPT | ✅ | 生成后校验页数与每页内嵌图片 MD5，防图页错配 |
| 免费版突破单日总量 | ✅ | 官方 FAQ 证实限制的是**并发**而非每日总量 |
| 复用历史项目续跑 | ❌ | 平台会清理免费档项目（约 30 分钟），续跑须新开项目 |

**速度参考**：实测均值 **76 秒/张** → 50 张 ≈ 1 小时，250 张 ≈ 5.3 小时。
单次工具调用有时长上限，大批量务必用 `--start/--end` **切片跑**。

---

## 🗂️ 仓库导航

```
📦 blng-batch-design
└── 📁           # 完整工作快照
    ├── 📁 blng-batch-design/        ⭐ 可分发 Skill（交付物）
    │   ├── SKILL.md                    能力边界 + 4 步工作流 + 7 条命门要点
    │   ├── README.md                   使用说明（环境 / 快速开始 / FAQ）
    │   ├── scripts/                    7 个自动化脚本
    │   │   ├── blng_conversation.py       批量生成主程序（断点续跑）
    │   │   ├── make_ppt.py                图片目录 → 一图一页 PPT + MD5 校验
    │   │   ├── blng_tool.py               浏览器自动化基座（CDP 封装）
    │   │   ├── blng_session.py            凭据与会话快照管理
    │   │   ├── blng_auto.py               登录 / 会话恢复辅助
    │   │   ├── gen_prompts.py             组合式提示词生成器（品类×宝石×金属）
    │   │   └── check_projects.py          免费版活跃项目数只读检查
    │   └── references/
    │       ├── setup.md                环境准备 · 凭据填写 · 链路自检
    │       └── pitfalls.md             ⚠️ 20 条踩坑手册（必读）
    │
    ├── 📁 blng-agent/               开发工作区（管线演进全程）
    │   ├── blng_*.py / diag*.py        各阶段脚本与诊断工具
    │   ├── conversations/              中国结 8 图 · 篮球 8 图（原始归档）
    │   ├── outputs/                    篮球 8 图集 · 珍珠项链 2 图
    │   ├── diamond/                    钻石 3 图 + manifest
    │   └── 篮球图片集/                 8 图 + slides DSL + 61MB 成品 PPTX
    │
    ├── 📄 4 份 Word 说明书           从详细版到极简版四级文档
    ├── 📄 GITHUB-发布信息.md         仓库描述 / Topics / Release 文案
    ├── 📁 output/                    文档生成流水线产物（stage1→stage3）
    └── 📁 .workbuddy/memory/         📅 工作日志（2026-10-09 / 10-14）
```

---

## 🚀 快速开始（3 分钟版）

完整步骤见 [`blng-batch-design/README.md`](blng-batch-design/README.md)，这里是最短路径：

```bash
# 1. 安装依赖（建议独立 venv）
python -m pip install browser-use websockets

# 2. 填入你的 BLNG 账号（编辑 scripts/blng_session.py，或用环境变量）
export BLNG_EMAIL="you@example.com" BLNG_PASSWORD="***"

# 3. 首次登录（一次即可，会话约 30 天有效）
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  python scripts/blng_session.py login

# 4. 生成 300 条珠宝提示词清单
python scripts/gen_prompts.py 300 scripts/design_prompts.json

# 5. 切片跑批（每批 25 张，约 30-40 分钟；重复执行安全）
python scripts/blng_conversation.py --file scripts/design_prompts.json \
  --name design_run --start 1 --end 25

# 6. 合成一图一页 PPT（自动校验页数 + 图片 MD5）
python scripts/make_ppt.py --force
```

> ⚠️ 环境要求：**Windows + 本机 Edge**（CDP 调试端口）、Python 3.10+、Node 18+（仅合成 PPT 时）。
> 系统代理会劫持 `localhost:9222` 导致 502，所有命令需按上方前置 `NO_PROXY`。

---

## 🖼️ 产出图集

| 图集 | 数量 | 说明 |
|---|---|---|
| [篮球主题](blng-agent/outputs/basketball_2026-10-09/) | 8 张 | 2048×2048，MD5 全部唯一，逐张视觉核验 |
| [中国结](blng-agent/conversations/chinese_knot_2026-10-09_153316/) | 8 张 | 单对话连续生成，7 分 16 秒完成 |
| [钻石](blng-agent/diamond/2026-10-09/) | 3 张 | 批次管线验证（含重试机制实测） |
| [篮球图片集 PPTX](blng-agent/篮球图片集/篮球图片集.pptx) | 8 页 | 一图一页，嵌入图 MD5 逐页匹配 |

---

## 📚 文档一览

| 文档 | 定位 | 适合谁 |
|---|---|---|
| [`BLNG批量出图使用方法.docx`](BLNG批量出图使用方法.docx) | 极简版（828 字，纯文字） | 只想知道「怎么用」的人 |
| [`BLNG批量出图Skill使用教程.docx`](BLNG批量出图Skill使用教程.docx) | 对 WorkBuddy 说什么的教材 | WorkBuddy 用户 |
| [`BLNG批量出图Skill使用说明.docx`](BLNG批量出图Skill使用说明.docx) | 标准说明（含表格与参数） | 日常使用者 |
| [`BLNG批量出图Skill使用说明_详细版.docx`](BLNG批量出图Skill使用说明_详细版.docx) | 完整版（22KB，全参数） | 深度使用 / 二次开发 |

---

## 🔑 关键实现要点（踩坑浓缩）

这些是管线的命门，**改动代码前务必理解**（完整 20 条见 [pitfalls.md](blng-batch-design/references/pitfalls.md)）：

1. **必须走本机 Edge + CDP**，不用托管 Chromium（Chromium 下载在国内经常超时）
2. **必须排除回环代理**，否则 CDP 端口被劫持报 502
3. **导航只点「New Design → 预设卡 Square 2K」**，预设卡点击即关闭弹窗，后续按钮不存在
4. **取图唯一可靠来源是 `.overlay` 预览图**——编辑区 DOM 虚拟化，"取最后一张 img" 会拿到旧图
5. **React 受控输入必须用原生 setter** 触发，直接赋 `value` 无效
6. **不要复用旧项目续跑**——免费档项目约 30 分钟即被清理，深链 4-5 秒后跳回 dashboard
7. **自动化产出的"成功"不可信**——必须 MD5/像素哈希 + 视觉抽查双重校验

---

## 🔒 脱敏与安全说明

本仓库由真实工作快照**脱敏后发布**：

- ✂️ 移除：BLNG 账号密码（13 处替换为占位符）、Cognito 会话令牌（refreshToken）、浏览器 Cookie 目录（`.edge-profile/`）、含账号信息的页面截图
- ✂️ 移除：约 1.5GB 浏览器缓存与媒体缓存
- ✅ 保留：全部脚本、日志、图集、文档与工作记录
- Skill 包本身（`blng-batch-design/`）凭据字段默认为空，使用方自行填写

---

## 📅 版本与记录

| 日期 | 里程碑 |
|---|---|
| 2026-10-09 | 浏览器自动化打通 → 登录 → 单图生成 → 批量管线 → 单对话连续出图 → 篮球 8 图 + PPT |
| 2026-10-14 | 50 张单任务实测（0 失败 / 0 重复，76s/张）→ Skill 固化打包 → 4 级说明书 → GitHub 整理 |

## 📄 许可

内部工具，暂未指定开源许可。如需对外发布请先补充 LICENSE。

---

<div align="center">

**⭐ 如果这个项目对你有帮助，欢迎点个 Star**

Made with ❤️ by [@ggq-eng](https://github.com/ggq-eng) · Powered by WorkBuddy

</div>
