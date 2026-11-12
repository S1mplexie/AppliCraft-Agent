@echo off
setlocal EnableExtensions DisableDelayedExpansion

REM ============================================================
REM  AppliCraft 本地部署版 —— 一键卸载（删除依赖 + 整个项目）
REM  用法：双击本文件
REM    1) 结束占用 8000 端口的服务
REM    2) 备份 backend\data 与 .env 到项目同级目录（DELETE 模式）
REM    3) 删除 backend\.venv（全部 Python 依赖）、frontend\node_modules
REM    4) 删除整个项目目录（含源码 / dist / knowledge / .git）
REM  安全：必须手动输入 DELETE（备份）或 PURGE（不备份）才会执行。
REM  不会动系统 Python 解释器、全局 pip 缓存或其它项目。
REM  因为脚本要删除自己所在的目录，最后一步交给 %TEMP% 里的
REM  临时辅助脚本延迟 2 秒执行。
REM  屏幕输出统一用 ASCII，避免 cmd 代码页造成中文乱码。
REM ============================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PORT=8000"
set "BACKUP="

REM 只在一个真正的 AppliCraft 项目目录里运行，避免误删任意文件夹。
if not exist "%ROOT%\start.bat" if not exist "%ROOT%\start.sh" (
  echo.
  echo [ERROR] This folder does not look like AppliCraft:
  echo         %ROOT%
  echo         Nothing was changed.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   AppliCraft local edition - UNINSTALL
echo ============================================================
echo.
echo   This will PERMANENTLY DELETE the whole project folder:
echo     %ROOT%
echo.
echo   Including source code, frontend\dist, knowledge\, .git, .env,
echo   backend\.venv (all Python dependencies) and backend\data.
echo.
echo   Your personal data (SQLite DB, uploads, DOCX, API keys) is in:
echo     %ROOT%\backend\data\
echo.
echo   System Python, the global pip cache and other projects are NOT
echo   touched. The server on port %PORT% will be stopped first.
echo.
echo ------------------------------------------------------------
echo   Type DELETE  : back up your data, then delete everything
echo   Type PURGE   : delete everything WITHOUT any backup
echo   Anything else: cancel, nothing is changed
echo ------------------------------------------------------------
echo.
set "ANSWER="
set /p "ANSWER=Your choice: "
if /i "%ANSWER%"=="DELETE" goto :do_backup
if /i "%ANSWER%"=="PURGE" goto :no_backup
echo.
echo Cancelled. Nothing was changed.
echo.
pause
exit /b 0

:do_backup
echo.
if not exist "%ROOT%\backend\data\" (
  echo No backend\data found - nothing to back up.
  goto :stop_service
)
for %%I in ("%ROOT%\..") do set "PARENT=%%~fI"
set "BACKUP=%PARENT%\AppliCraftLocal-backup"
if exist "%BACKUP%" set "BACKUP=%PARENT%\AppliCraftLocal-backup-%RANDOM%"
echo Backing up your data to:
echo   %BACKUP%
robocopy "%ROOT%\backend\data" "%BACKUP%\backend-data" /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul 2>&1
if errorlevel 8 (
  echo.
  echo [ERROR] Backup failed - aborting, nothing was deleted.
  echo         Free some disk space or choose another location, then retry.
  echo.
  pause
  exit /b 1
)
if exist "%ROOT%\.env" copy /y "%ROOT%\.env" "%BACKUP%\.env" >nul 2>&1
echo Backup OK.
echo.
goto :stop_service

:no_backup
echo.
echo *** WARNING: NO BACKUP. All data will be permanently lost. ***
echo.
goto :stop_service

:stop_service
echo Stopping AppliCraft server on port %PORT% ...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /C:":%PORT% " ^| findstr /C:"LISTENING"') do (
    if not "%%a"=="" taskkill /PID %%a /F /T >nul 2>&1
)
echo Done.

:remove_deps
echo.
echo Removing bundled dependencies ...
if exist "%ROOT%\backend\.venv\" (
  echo   backend\.venv
  rmdir /s /q "%ROOT%\backend\.venv" >nul 2>&1
  if exist "%ROOT%\backend\.venv\" goto :locked
)
if exist "%ROOT%\frontend\node_modules\" (
  echo   frontend\node_modules
  rmdir /s /q "%ROOT%\frontend\node_modules" >nul 2>&1
)
if exist "%ROOT%\frontend\.vite\" rmdir /s /q "%ROOT%\frontend\.vite" >nul 2>&1
echo Done.

:remove_all
echo.
echo Deleting the whole project folder ...
set "AC_ROOT=%ROOT%"
set "AC_BACKUP=%BACKUP%"
set "HELPER=%TEMP%\applicraft_uninstall_%RANDOM%%RANDOM%.bat"

>  "%HELPER%" echo @echo off
>> "%HELPER%" echo title AppliCraft Uninstall
>> "%HELPER%" echo timeout /t 2 /nobreak ^>nul
>> "%HELPER%" echo cd /d "%%TEMP%%"
>> "%HELPER%" echo rd /s /q "%%AC_ROOT%%" 2^>nul
>> "%HELPER%" echo if exist "%%AC_ROOT%%" ^(
>> "%HELPER%" echo   echo [WARN] Some files could not be removed.
>> "%HELPER%" echo   echo        Close editors/terminals in that folder and delete it manually:
>> "%HELPER%" echo   echo        %%AC_ROOT%%
>> "%HELPER%" echo ^) else ^(
>> "%HELPER%" echo   echo [OK] AppliCraft local edition has been removed.
>> "%HELPER%" echo ^)
>> "%HELPER%" echo if defined AC_BACKUP echo Backup kept at: %%AC_BACKUP%%
>> "%HELPER%" echo echo.
>> "%HELPER%" echo pause
>> "%HELPER%" echo del "%%~f0" ^>nul 2^>^&1

cd /d "%TEMP%"
start "AppliCraft Uninstall" /D "%TEMP%" "%HELPER%"
echo.
echo The final deletion runs in a separate window (a script cannot
echo delete the folder that contains it while it is still running).
if defined BACKUP echo Backup kept at: %BACKUP%
echo.
exit /b 0

:locked
echo.
echo [ERROR] backend\.venv is still in use. Close the server window,
echo         editor or terminal using it, then run this file again.
echo         Nothing else was deleted.
echo.
pause
exit /b 1
