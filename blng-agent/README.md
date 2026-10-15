# BLNG Agent 浏览器自动化工具 · 完整版

给 Agent 提供 `https://app.blng.ai/` 的**登录态浏览器自动化**能力。
技术栈：**browser-use 0.13.11 + Edge 154 CDP + AWS Cognito 会话持久化**

---

## 一、快速开始

```bash
export PATH="/c/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts:$PATH"
cd /c/Users/Administrator/WorkBuddy/2026-10-09-10-02-25/blng-agent

# 1) 确保登录态（自动恢复或重登）
python blng_auto.py ensure

# 2) 登录态下抓取页面（含截图）
python blng_auto.py snapshot https://app.blng.ai/dashboard
```

**实测输出**（已验证）：
```json
{"success": true, "method": "restore", "url": "https://app.blng.ai/dashboard"}
```

---

## 二、文件清单

| 文件 | 作用 | 状态 |
|---|---|---|
| `blng_tool.py` | ★ CDP 轻量封装（doctor/start/snapshot） | ✅ 实测通过 |
| `blng_auto.py` | ★ **会话管理**（自动恢复登录态 + 重登兜底） | ✅ 实测通过 |
| `blng_session.py` | 登录 + 会话快照导出 | ✅ 实测通过 |
| `blng_login2.py` | 邮箱→密码登录流程 | ✅ 实测通过 |
| `blng_agent.py` | browser-use LLM Agent（需配 `.env`） | ⏳ 待配 Key |
| `.blng_session.json` | **Cognito 会话快照**（自动生成） | ✅ 已生成 |
| `.edge-profile/` | 独立浏览器 profile | ✅ |

---

## 三、登录架构（关键情报）

BLNG 使用 **AWS Cognito** 认证：

| 凭据 | 存储位置 | 有效期 |
|---|---|---|
| `accessToken` | localStorage | ~1 小时 |
| `idToken` | localStorage | ~1 小时 |
| `refreshToken` | localStorage | **~30 天** ← 关键 |
| cookies | 6 个（含 `cwr_u`/`cwr_s`） | 会话级 |

**持久化原理**：注入 refreshToken 后，SDK 会静默续期，**无需重复输密码**。

账号：`226****82@qq.com（已脱敏）` ｜ 密码：`Hq******!（已脱敏）`（**半角感叹号**，全角 `！` 会报 Incorrect）

---

## 四、核心 API

### `blng_auto.py`（推荐）

| 命令 | 说明 |
|---|---|
| `ensure` | 保证登录态：优先 `restore`，失败自动 `relogin` |
| `snapshot <url>` | 登录态下抓取标题/正文/截图 |

Python 内嵌调用：

```python
import asyncio
from blng_auto import ensure, snapshot_authed

print(asyncio.run(ensure()))                              # 确保登录
res = asyncio.run(snapshot_authed("https://app.blng.ai/dashboard"))
print(res["title"], res["url"])
```

### `blng_tool.py`（无登录态）

| 命令 | 说明 |
|---|---|
| `doctor` | 环境健康检查 |
| `start` | 启动 Edge CDP（幂等） |
| `snapshot <url>` | 匿名抓取 + 截图 |

---

## 五、已解决的环境障碍（血泪史）

| # | 障碍 | 真因 | 解法 |
|---|---|---|---|
| 1 | Chromium 内核下载失败 | Google 存储超时（198MB 卡 89MB，重试 3 次全挂） | 改用本机 **Edge 154** |
| 2 | CDP 返回 **502 Bad Gateway** | `HTTP_PROXY=127.0.0.1:58732` **劫持本地回环请求** | `NO_PROXY=localhost,127.0.0.1,::1` |
| 3 | Edge 启动即消失 | 沙箱回收脱离的子进程树 | 同会话内「启动→验证→执行」 |
| 4 | 会话不保持 | 认证态在 localStorage，非 cookie | 导出/注入 Cognito 凭据 |
| 5 | `'Runtime.evaluate' wasn't found` | 复用失效的 sessionId | `try_restore` 返回有效 sid 直接复用 |

---

## 六、可观测性

| 类型 | 位置 |
|---|---|
| 运行日志 | 控制台（时间戳+级别+模块） |
| 截图存证 | `screenshots/`（`snap_*` / `login_*` / `session_*` / `auth_*`） |
| 会话快照 | `.blng_session.json`（含 `saved_at` 时间戳） |
| 异常堆栈 | `log.exception` 完整输出 |

---

## 七、已知约束

1. **必须同会话执行**：沙箱回收脱离进程；生产环境应改为常驻 Edge 服务。
2. **Edge 路径硬编码**：`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
3. **代理排除是硬依赖**：新增网络调用前必须确保 `NO_PROXY` 含 `127.0.0.1`。
4. **密码区分全角/半角**：必须用半角 `!`。
5. **免费账号限制**：Starter 计划，Unlimited files / chat history / 4x upscale 需升级。

---

## 八、下一步可选方向

- [ ] 接入 `ai.zlskcn.com`（qwen3.6:128k）驱动 `blng_agent.py` 的 LLM 决策层
- [ ] 封装 `new_design()`：自动创建项目并提交生成提示词
- [ ] 批量下载生成结果（`My files` 资产抓取）
- [ ] Edge CDP 改为 Windows 服务常驻，消除重复启动开销
