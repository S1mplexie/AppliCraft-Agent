#!/usr/bin/env bash
# AppliCraft local edition - one-click start (no Docker).
# Usage: bash start.sh   (or chmod +x start.sh && ./start.sh)
set -e

# Work from backend/ so `uvicorn app.main:app` and relative paths
# (knowledge/, data/, frontend/dist) resolve correctly.
cd "$(dirname "$0")/backend"

# Find a real Python 3.10+ interpreter (not just a name on PATH).
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      PY="$c"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo ""
  echo "[ERROR] Python 3.10 or newer is required but was not found."
  echo "        Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
  echo "        macOS:         brew install python@3.12"
  echo "        Or download:   https://www.python.org/downloads/"
  exit 1
fi

echo "Using Python: $("$PY" --version 2>&1) ($(command -v "$PY"))"

VPY=".venv/bin/python"
# An existing .venv created on another machine (or a failed run) is unusable.
if [ ! -x "$VPY" ] || ! "$VPY" -c 'import sys' >/dev/null 2>&1; then
  if [ -d ".venv" ]; then
    echo "Removing an incomplete or unusable .venv ..."
    rm -rf ".venv"
  fi
  echo "Creating virtual environment .venv ..."
  if ! "$PY" -m venv .venv; then
    echo ""
    echo "[ERROR] Failed to create the virtual environment."
    echo "        On Debian/Ubuntu this usually means python3-venv is missing:"
    echo "          sudo apt install python3-venv python3-pip"
    echo "        Then run this script again."
    rm -rf ".venv"
    exit 1
  fi
fi

if [ ! -x "$VPY" ]; then
  echo "[ERROR] .venv/bin/python is missing; delete .venv and retry."
  exit 1
fi

echo "Installing dependencies (first run is slower; later runs use cache)..."
if ! "$VPY" -m pip install -q -r requirements.txt; then
  echo ""
  echo "[ERROR] Dependency installation failed (no internet / proxy / disk full?)."
  echo "        Check the error above, then run this script again."
  exit 1
fi

echo ""
echo "==================================================="
echo "  AppliCraft local edition is starting"
echo "  Open in browser:  http://localhost:8000"
echo "  First time:  Settings - My LLM API, enter your own Key"
echo "  Data location:  backend/data/ on this machine (back it up)"
echo "  Stop server:  press Ctrl+C"
echo "==================================================="
exec "$VPY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
