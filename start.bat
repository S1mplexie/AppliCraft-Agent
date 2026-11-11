@echo off
REM AppliCraft 本地部署版 —— 纯 Python 启动，无需 Docker / 容器。
REM 用法：双击 start.bat，或在命令行执行 start.bat
cd /d "%~dp0backend"

if not exist ".venv" (
  echo 创建虚拟环境 .venv ...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo 安装依赖（首次较慢，之后会走缓存）...
pip install -q -r requirements.txt

echo.
echo ===================================================
echo  AppliCraft 本地版已启动
echo  浏览器打开：  http://localhost:8000
echo  首次使用：  设置 - 我的大模型 API，填入你自己的 Key
echo  数据位置：  本机 backend\data\（请自行备份）
echo  停止服务：  在窗口按 Ctrl+C
echo ===================================================
uvicorn app.main:app --host 0.0.0.0 --port 8000
