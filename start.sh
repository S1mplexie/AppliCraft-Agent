#!/usr/bin/env bash
# AppliCraft 本地部署版 —— 纯 Python 启动，无需 Docker / 容器。
# 用法：  bash start.sh   （或 chmod +x start.sh 后 ./start.sh）
set -e

# 切换到后端目录，保证 `uvicorn app.main:app` 能找到 app 包，
# 且配置里的相对路径（knowledge/、data/、frontend/dist）都能正确解析。
cd "$(dirname "$0")/backend"

# 首次运行创建虚拟环境（已存在则跳过）。
if [ ! -d ".venv" ]; then
  echo "创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "安装依赖（首次较慢，之后会走缓存）..."
pip install -q -r requirements.txt

echo ""
echo "==================================================="
echo "  AppliCraft 本地版已启动"
echo "  浏览器打开：  http://localhost:8000"
echo "  首次使用：  设置 → 我的大模型 API，填入你自己的 Key"
echo "  数据位置：  本机 backend/data/（请自行备份）"
echo "  停止服务：  在终端按 Ctrl+C"
echo "==================================================="
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
