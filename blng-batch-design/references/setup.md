# 环境准备与首次登录

本 skill 把 BLNG（`https://app.blng.ai`）的批量出图管线固化下来。使用前需要一次性的环境准备和账号登录，之后即可反复跑批。

---

## 一、前置条件

| 项 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows | 依赖本机 Edge 的 CDP 调试端口 |
| 浏览器 | Microsoft Edge | 无需 Chrome/Chromium，直接复用本机 Edge |
| Python | 3.10+ | 建议用受管环境 `~/.workbuddy/binaries/python/envs/default` |
| Node | 18+ | 仅 `make_ppt.py` 合成 PPT 时需要 |
| PPT 引擎 | `@tencent/slidep` | 合成 PPT 时需要，装在 node 的 `lib/node_modules/` 下 |
| 网络 | 可直连 BLNG | 若走系统代理，脚本已内置 `NO_PROXY` 排除回环地址 |

安装 Python 依赖：

```bash
PY="$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
"$PY" -m pip install browser-use websockets
```

> ⚠️ **必须用这个 venv 解释器运行脚本**，不要用系统 `python`。
> 系统 Python 缺 `websockets`，会报 `ModuleNotFoundError: No module named 'websockets'`。
> 前文所有 `python xxx.py` 命令，请理解为 `"$PY" xxx.py`。

确认 PPT 引擎可用：

```bash
node -e "console.log(require.resolve('@tencent/slidep/dist/index.js'))"
```

若报找不到模块，在 node 安装目录下安装（或在 `make_ppt.py` 运行时用 `BLNG_NODE` 指向已装好引擎的 node）：

```bash
npm install -g @tencent/slidep
```

> `make_ppt.py` 会自动在 node 同级的 `lib/node_modules/` 与 `node_modules/` 下寻找引擎；也可用环境变量 `BLNG_NODE` 指定 node 路径。

---

## 二、填写账号密码（关键步骤）

凭据文件：`scripts/blng_session.py`

打开后找到这一段：

```python
# ============================================================
#  凭据配置 —— 使用前请填写你自己的 BLNG 账号
# ============================================================
# 方式一（推荐）：直接填写下面两行
EMAIL = ""
PASSWORD = ""
# 方式二：设置环境变量 BLNG_EMAIL / BLNG_PASSWORD（优先级高于上面的填写）
```

**方式一：直接填写（推荐给个人长期使用）**

把 `EMAIL` 和 `PASSWORD` 两行填成自己的 BLNG 账号：

```python
EMAIL = "your_account@example.com"
PASSWORD = "your_password"
```

**方式二：环境变量（推荐给多人共用、避免把密码写进文件）**

保持 `EMAIL`/`PASSWORD` 为空，改为在运行前注入：

```bash
export BLNG_EMAIL="your_account@example.com"
export BLNG_PASSWORD="your_password"
```

> ⚠️ 环境变量优先级 **高于** 文件内填写。若两者都设置，以环境变量为准。
> ⚠️ 切勿把填好真实密码的 `blng_session.py` 提交到任何公开仓库或分享出去。

---

## 三、首次登录（只需一次）

登录会把认证态（AWS Cognito 的 token + localStorage）落盘成会话快照，后续跑批自动注入，不必反复登录。

```bash
cd <skill>/scripts
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  python blng_session.py login
```

成功后会：

1. 后台拉起 Edge（调试端口 9222，独立用户目录 `.edge-profile/`）；
2. 自动填邮箱/密码并提交；
3. 导出会话到 `scripts/.blng_session.json`；
4. 输出 `{"ok": true, ...}`。

检查登录态（不重新登录）：

```bash
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  python blng_session.py status
```

返回 `"logged_in": true` 即已就绪。

---

## 四、第一条链路自检

登录成功后，跑一个 3 张图的小任务验证整条链路：

```bash
# 1) 生成提示词清单（5 条）
python gen_prompts.py 5 design_prompts.json

# 2) 检查当前账号的活跃设计文件数（免费版上限 3）
python check_projects.py

# 3) 跑 3 张（落盘目录已写死，无需 --out-dir）
NO_PROXY='localhost,127.0.0.1,::1,0.0.0.0' HTTP_PROXY='' HTTPS_PROXY='' \
  python blng_conversation.py --file design_prompts.json --name smoke \
    --start 1 --end 3
```

到 `D:\Desktop\新建文件夹 (2)\设计图` 里看到 `001_*.png`、`002_*.png`、`003_*.png` 即链路打通。

---

## 五、会话失效与恢复

- accessToken 约 1 小时过期，refreshToken 约 30 天。脚本每次跑批前会 `ensure()`：有效则复用，失效则用凭据重新登录。
- 若 `status` 返回 `logged_in: false`，直接重跑一次 `login` 即可。
- Edge 用户目录固定在 `scripts/.edge-profile/`，删掉它会连会话一起清空，需重新登录。
- 同一时间只应有一个进程占用调试端口 9222；重复启动会复用已有 Edge 实例。

---

## 六、目录约定

**默认路径（已写死在脚本里）**

| 项 | 路径 |
|---|---|
| 图片落盘目录 | `D:\Desktop\新建文件夹 (2)\设计图` |
| PPT 输出文件 | `D:\Desktop\新建文件夹 (2)\设计图集.pptx` |

覆盖方式：命令行传 `--out-dir` / `--dir` / `--out`，或设环境变量 `BLNG_OUT_DIR` / `BLNG_PPT_OUT`。

**运行期文件**

| 路径 | 用途 |
|---|---|
| `scripts/.blng_session.json` | 会话快照（含 token，勿外传） |
| `scripts/.edge-profile/` | Edge 独立用户目录 |
| `scripts/design_prompts.json` | 默认提示词清单 |
| `scripts/screenshots/` | 调试截图目录（`SHOT_DIR`） |
| `<落盘目录>/manifest.json` | 出图记录（用于断点续跑去重） |

下一步见 `SKILL.md` 的「批量出图工作流」，排坑见 `pitfalls.md`。
