@echo off
setlocal
cd /d "%~dp0backend"

REM 一键重启 AppliCraft 本地服务：
REM   1) 按端口 8000 找到正在运行的进程并强制结束（无论是否由 start.bat 启动）；
REM   2) 等待端口释放；
REM   3) 在新窗口重新运行 start.bat 启动服务，本窗口随后关闭。
REM 若当前没有服务在运行，则等价于「启动」。

echo Stopping existing AppliCraft server on port 8000 ...
powershell -NoProfile -Command "try { (Get-NetTCPConnection -LocalPort 8000 -ErrorAction Stop).OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } } catch {}"

REM 等待端口释放（Windows 偶发 TIME_WAIT）
timeout /t 3 >nul

echo Starting AppliCraft server ...
start "" "%~dp0start.bat"
exit /b
