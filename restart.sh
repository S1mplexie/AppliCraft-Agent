#!/usr/bin/env bash
# AppliCraft 本地部署版 —— 一键重启服务（无 Docker）。
# 用法：  bash restart.sh
set -e

DIR="$(cd "$(dirname "$0")" && pwd)/backend"
cd "$DIR"

echo "Stopping existing AppliCraft server on port 8000 ..."
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti tcp:8000 2>/dev/null || true)"
else
  PIDS="$(pgrep -f 'uvicorn app.main:app' 2>/dev/null || true)"
fi
if [ -n "$PIDS" ]; then
  # 结束监听进程（及其可能的主进程）
  kill $PIDS 2>/dev/null || true
  sleep 2
fi

echo "Starting AppliCraft server (background) ..."
# 后台启动，日志写入 backend/nohup.out；服务进程与当前 shell 解耦。
nohup bash "$DIR/../start.sh" > "$DIR/nohup.out" 2>&1 &
echo "Done. Open http://localhost:8000   (logs: $DIR/nohup.out)"
