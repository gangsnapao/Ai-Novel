#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
BACKEND_PORT=8000
FRONTEND_PORT=5174
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"

is_port_ready() {
  local port="$1"
  lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1
}

listener_summary() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | tail -n +2 || true
}

escape_for_applescript() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

open_terminal_window() {
  local command="$1"
  local escaped
  escaped="$(escape_for_applescript "$command")"
  osascript <<EOF >/dev/null
tell application "Terminal"
  activate
  do script "$escaped"
end tell
EOF
}

if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  echo "未找到后端 Python 运行时：$BACKEND_DIR/.venv/bin/python"
  exit 1
fi

if [[ ! -x "$FRONTEND_DIR/node_modules/.bin/vite" ]]; then
  echo "未找到前端依赖，请先安装 frontend/node_modules。"
  exit 1
fi

backend_conflict="$(listener_summary "$BACKEND_PORT")"
frontend_conflict="$(listener_summary "$FRONTEND_PORT")"

if [[ -n "$backend_conflict" ]] && [[ "$backend_conflict" != *uvicorn* ]]; then
  echo "端口 $BACKEND_PORT 被其他进程占用："
  echo "$backend_conflict"
  exit 1
fi

if [[ -n "$frontend_conflict" ]] && [[ "$frontend_conflict" != *vite* ]]; then
  echo "端口 $FRONTEND_PORT 被其他进程占用："
  echo "$frontend_conflict"
  exit 1
fi

if is_port_ready "$BACKEND_PORT" && is_port_ready "$FRONTEND_PORT"; then
  echo "Ai-Novel 本地版已在运行，正在打开：$FRONTEND_URL"
  open "$FRONTEND_URL"
  exit 0
fi

if ! is_port_ready "$BACKEND_PORT"; then
  backend_command=$(cat <<EOF
clear
echo "[AiNovelFastAPI] 启动 Ai-Novel backend"
cd "$BACKEND_DIR"
./.venv/bin/python -m uvicorn app.main:app --reload --workers 1 --host 127.0.0.1 --port $BACKEND_PORT
exit_code=\$?
echo ""
echo "backend 已退出，exit code: \$exit_code"
echo "按回车关闭窗口..."
read
exit \$exit_code
EOF
)
  open_terminal_window "$backend_command"
fi

if ! is_port_ready "$FRONTEND_PORT"; then
  frontend_command=$(cat <<EOF
clear
echo "[AiNovelVite] 启动 Ai-Novel frontend"
cd "$FRONTEND_DIR"
npm run dev -- --host 127.0.0.1 --port $FRONTEND_PORT
exit_code=\$?
echo ""
echo "frontend 已退出，exit code: \$exit_code"
echo "按回车关闭窗口..."
read
exit \$exit_code
EOF
)
  open_terminal_window "$frontend_command"
fi

echo "正在等待 Ai-Novel 本地服务就绪..."
for _ in {1..120}; do
  if is_port_ready "$BACKEND_PORT" && is_port_ready "$FRONTEND_PORT"; then
    echo "启动成功，正在打开：$FRONTEND_URL"
    open "$FRONTEND_URL"
    exit 0
  fi
  sleep 1
done

echo "等待超时，请检查新打开的 Terminal 窗口输出。"
exit 1
