#!/usr/bin/env bash
# ===================================================================
# start_edge_cdp.sh —— 启动带 CDP 调试端口的 Edge 实例
# ===================================================================
# 背景:
#   1. 本机无 Chrome，browser-use 自带 Chromium 因网络下不动；
#      只有 Edge (C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe)
#   2. 系统设置了 HTTP_PROXY=http://127.0.0.1:58732，会劫持本地 CDP 请求
#   3. 独立 profile 目录，避免污染用户日常浏览器数据
# ===================================================================
set -u

EDGE="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
PORT=9222
PROFILE_DIR="C:\\Users\\Administrator\\WorkBuddy\\2026-10-09-10-02-25\\blng-agent\\.edge-profile"

# 1) 若端口已监听，直接复用（幂等）
if curl -s --noproxy '*' --max-time 3 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "✓ CDP 端口 ${PORT} 已在监听，复用现有实例"
  exit 0
fi

# 2) 启动 Edge
echo "启动 Edge (CDP :${PORT})..."
"$EDGE" \
  --remote-debugging-port=${PORT} \
  --user-data-dir="${PROFILE_DIR}" \
  --no-first-run \
  --no-default-browser-check \
  --disable-features=msEdgeSidebarV2 \
  about:blank >/dev/null 2>&1 &

# 3) 轮询等待端口就绪（最多 30s）
for i in $(seq 1 30); do
  if curl -s --noproxy '*' --max-time 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    echo "✓ Edge CDP 就绪 (:${PORT})，耗时 ${i}s"
    exit 0
  fi
  sleep 1
done

echo "✗ Edge CDP 启动失败，请检查 msedge.exe 路径或端口占用" >&2
exit 1
