@echo off
setlocal
cd /d "%~dp0backend"

REM ============================================================
REM  AppliCraft 本地部署版 —— 一键重启服务（无 Docker）
REM  用法：双击本文件即可
REM    1) 找到占用 8000 端口的进程并强制结束（含子进程 /T）
REM    2) 轮询等待端口真正释放（最多约 10 秒）
REM    3) 在新窗口重新运行 start.bat 启动服务，本窗口随后关闭
REM  若当前没有服务在运行，则等价于「启动」
REM ============================================================

set PORT=8000
echo Stopping any AppliCraft server on port %PORT% ...

set "KILLED=0"
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| find ":%PORT%" 2^>nul') do (
    if not "%%a"=="" (
        echo   killing PID %%a
        taskkill /PID %%a /F /T >nul 2>&1
        set "KILLED=1"
    )
)
if "%KILLED%"=="0" echo   (no process found on port %PORT%)

echo Waiting for port %PORT% to be released ...
set WAITED=0
:waitloop
netstat -ano 2>nul | find ":%PORT%" >nul 2>&1
if errorlevel 1 goto portfree
if %WAITED%==10 goto portfree
timeout /t 1 >nul
set /a WAITED+=1
goto waitloop
:portfree

echo Starting AppliCraft server ...
start "" "%~dp0start.bat"
exit /b
