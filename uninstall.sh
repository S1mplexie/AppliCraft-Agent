#!/usr/bin/env bash
# AppliCraft 本地部署版 —— 一键卸载（删除依赖 + 整个项目）
# 用法：bash uninstall.sh   （或 chmod +x uninstall.sh && ./uninstall.sh）
#
#   1) 结束占用 8000 端口的服务
#   2) 备份 backend/data 与 .env 到项目同级目录（DELETE 模式）
#   3) 删除 backend/.venv（全部 Python 依赖）、frontend/node_modules
#   4) 删除整个项目目录（含源码 / dist / knowledge / .git）
#
# 安全：必须手动输入 DELETE（备份）或 PURGE（不备份）才会执行。
# 不会动系统 Python 解释器、全局 pip 缓存或其它项目。
# 因为脚本要删除自己所在的目录，最后一步交给 /tmp 里的临时辅助
# 脚本延迟 2 秒后台执行。
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT=8000
PARENT="$(dirname "$ROOT")"
BACKUP=""

# 只在一个真正的 AppliCraft 项目目录里运行，避免误删任意文件夹。
if [ ! -f "$ROOT/start.sh" ] && [ ! -f "$ROOT/start.bat" ]; then
  echo "[ERROR] This folder does not look like AppliCraft: $ROOT"
  echo "        Nothing was changed."
  exit 1
fi
if [ "$ROOT" = "/" ] || [ -z "$ROOT" ]; then
  echo "[ERROR] Refusing to delete /. Nothing was changed."
  exit 1
fi

echo ""
echo "============================================================"
echo "  AppliCraft local edition - UNINSTALL"
echo "============================================================"
echo ""
echo "  This will PERMANENTLY DELETE the whole project folder:"
echo "    $ROOT"
echo ""
echo "  Including source code, frontend/dist, knowledge/, .git, .env,"
echo "  backend/.venv (all Python dependencies) and backend/data."
echo ""
echo "  Your personal data (SQLite DB, uploads, DOCX, API keys) is in:"
echo "    $ROOT/backend/data/"
echo ""
echo "  System Python, the global pip cache and other projects are NOT"
echo "  touched. The server on port $PORT will be stopped first."
echo ""
echo "------------------------------------------------------------"
echo "  Type DELETE  : back up your data, then delete everything"
echo "  Type PURGE   : delete everything WITHOUT any backup"
echo "  Anything else: cancel, nothing is changed"
echo "------------------------------------------------------------"
echo ""
printf "Your choice: "
read -r ANSWER || ANSWER=""
case "$ANSWER" in
  DELETE) MODE=backup ;;
  PURGE)  MODE=purge ;;
  *) echo ""; echo "Cancelled. Nothing was changed."; exit 0 ;;
esac

# ---------- 1) 备份个人数据（放在项目目录之外，否则会一起被删） ----------
echo ""
if [ "$MODE" = "backup" ]; then
  if [ -d "$ROOT/backend/data" ]; then
    BACKUP="$PARENT/AppliCraftLocal-backup"
    if [ -e "$BACKUP" ]; then
      BACKUP="$PARENT/AppliCraftLocal-backup-$(date +%Y%m%d-%H%M%S)-$$"
    fi
    echo "Backing up your data to:"
    echo "  $BACKUP"
    if ! mkdir -p "$BACKUP"; then
      echo "[ERROR] Cannot create backup folder - aborting, nothing was deleted."
      exit 1
    fi
    if ! cp -a "$ROOT/backend/data" "$BACKUP/backend-data"; then
      echo "[ERROR] Backup failed - aborting, nothing was deleted."
      exit 1
    fi
    if [ -f "$ROOT/.env" ]; then
      cp -a "$ROOT/.env" "$BACKUP/.env" 2>/dev/null || true
    fi
    echo "Backup OK."
  else
    echo "No backend/data found - nothing to back up."
  fi
else
  echo "*** WARNING: NO BACKUP. All data will be permanently lost. ***"
fi

# ---------- 2) 停止服务 ----------
echo ""
echo "Stopping AppliCraft server on port $PORT ..."
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti "tcp:$PORT" 2>/dev/null || true)"
else
  PIDS="$(pgrep -f 'uvicorn app.main:app' 2>/dev/null || true)"
fi
if [ -n "$PIDS" ]; then
  echo "  stopping PID(s): $PIDS"
  kill -9 $PIDS 2>/dev/null || true
fi
echo "Done."

# ---------- 3) 删除随项目安装的依赖 ----------
echo ""
echo "Removing bundled dependencies ..."
if [ -d "$ROOT/backend/.venv" ]; then
  echo "  backend/.venv"
  rm -rf "$ROOT/backend/.venv"
fi
if [ -d "$ROOT/frontend/node_modules" ]; then
  echo "  frontend/node_modules"
  rm -rf "$ROOT/frontend/node_modules"
fi
if [ -d "$ROOT/frontend/.vite" ]; then
  rm -rf "$ROOT/frontend/.vite"
fi
echo "Done."

# ---------- 4) 删除整个项目目录（延迟 + 脱离当前脚本） ----------
echo ""
echo "Deleting the whole project folder ..."
HELPER="$(mktemp "${TMPDIR:-/tmp}/applicraft-uninstall.XXXXXX.sh")" || {
  echo "[ERROR] Cannot create helper script - project folder is still here."
  exit 1
}
cat > "$HELPER" <<'HELPER_EOF'
#!/usr/bin/env bash
[ -n "$1" ] || exit 1
sleep 2
cd / || exit 1
rm -rf -- "$1"
if [ -e "$1" ]; then
  echo "[WARN] Some files could not be removed: $1"
  echo "       Close editors/terminals in that folder and delete it manually."
else
  echo "[OK] AppliCraft local edition has been removed."
fi
[ -n "$2" ] && echo "Backup kept at: $2"
rm -f -- "$0"
HELPER_EOF
chmod +x "$HELPER"
LOG="${TMPDIR:-/tmp}/applicraft-uninstall.log"
nohup bash "$HELPER" "$ROOT" "$BACKUP" > "$LOG" 2>&1 &
echo "The final deletion runs in the background (a script cannot delete"
echo "the folder it lives in while still running)."
echo "Log: $LOG"
if [ -n "$BACKUP" ]; then echo "Backup kept at: $BACKUP"; fi
exit 0
