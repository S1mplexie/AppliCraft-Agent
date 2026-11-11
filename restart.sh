#!/usr/bin/env bash
# AppliCraft 本地部署版 —— 一键重启服务（无 Docker）。
# 用法：  bash restart.sh
set -u

DIR="$(cd "$(dirname "$0")" && pwd)/backend"
cd "$DIR"
PORT=8000

echo "Stopping any AppliCraft server on port $PORT ..."
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti tcp:$PORT 2>/dev/null || true)"
else
  PIDS="$(pgrep -f 'uvicorn app.main:app' 2>/dev/null || true)"
fi
if [ -n "$PIDS" ]; then
  echo "  killing PID(s): $PIDS"
  kill -9 $PIDS 2>/dev/null || true
fi

# 轮询等待端口真正释放（最多约 10 秒）
echo "Waiting for port $PORT to be released ..."
WAITED=0
while :; do
  if command -v lsof >/dev/null 2>&1; then
    REMAIN="$(lsof -ti tcp:$PORT 2>/dev/null || true)"
  else
    REMAIN="$(pgrep -f 'uvicorn app.main:app' 2>/dev/null || true)"
  fi
  [ -z "$REMAIN" ] && break
  WAITED=$((WAITED + 1))
  if [ "$WAITED" -ge 10 ]; then
    echo "  (port still busy after ${WAITED}s; proceeding anyway)"
    break
  fi
  sleep 1
done

echo "Starting AppliCraft server (background) ..."
# 后台启动，日志写入 backend/nohup.out；服务进程与当前 shell 解耦。
nohup bash "$DIR/../start.sh" > "$DIR/nohup.out" 2>&1 &
echo "Done. Open http://localhost:8000   (logs: $DIR/nohup.out)"
