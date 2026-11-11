@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0backend"
if errorlevel 1 goto :cdfail

REM ============================================================
REM  AppliCraft local edition - one-click start (no Docker).
REM  Double-click this file: create .venv, install deps, start server.
REM
REM  NOTE: "where python" is NOT a reliable Python check on Windows.
REM  Windows ships a Microsoft Store alias at
REM  %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe which answers
REM  "where" but is not Python and cannot run anything. We actually
REM  execute each candidate, read sys.executable / version, and reject
REM  that alias. All messages here are plain ASCII on purpose.
REM ============================================================

set "PY="
set "PYCMD="
set "TMPF=%TEMP%\applicraft_pyprobe.txt"

REM 1) Official installer's Python launcher (not affected by Store aliases)
call :probe "py -3"
if defined PY goto :pyok
call :probe "py"
if defined PY goto :pyok

REM 2) Real interpreters on PATH, skipping the Store alias
for /f "delims=" %%W in ('where python 2^>nul') do call :probepath "%%W"
if defined PY goto :pyok
for /f "delims=" %%W in ('where python3 2^>nul') do call :probepath "%%W"
if defined PY goto :pyok

REM 3) Last resort: bare command names
call :probe "python"
if defined PY goto :pyok
call :probe "python3"
if defined PY goto :pyok
goto :nopython

REM ---- Probe a command such as "py -3" or "python" ----
:probe
set "PYC=%~1"
set "PEXE="
set "PVER="
%PYC% -c "import sys;print(sys.executable)" > "%TMPF%" 2>nul
if errorlevel 1 exit /b 1
for /f "usebackq delims=" %%P in ("%TMPF%") do set "PEXE=%%P"
if not defined PEXE exit /b 1
if not "%PEXE:WindowsApps=%"=="%PEXE%" exit /b 1
if not exist "%PEXE%" exit /b 1
%PYC% -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" > "%TMPF%" 2>nul
if errorlevel 1 exit /b 1
for /f "usebackq delims=" %%V in ("%TMPF%") do set "PVER=%%V"
if not defined PVER exit /b 1
if %PVER% LSS 310 exit /b 1
set "PY=%PEXE%"
set "PYCMD=%PYC%"
exit /b 0

REM ---- Probe an absolute interpreter path ----
:probepath
if defined PY exit /b 0
set "PEXE=%~1"
if not "%PEXE:WindowsApps=%"=="%PEXE%" exit /b 1
if not exist "%PEXE%" exit /b 1
set "PVER="
"%PEXE%" -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" > "%TMPF%" 2>nul
if errorlevel 1 exit /b 1
for /f "usebackq delims=" %%V in ("%TMPF%") do set "PVER=%%V"
if not defined PVER exit /b 1
if %PVER% LSS 310 exit /b 1
set "PY=%PEXE%"
set "PYCMD=%PEXE%"
exit /b 0

:pyok
del "%TMPF%" >nul 2>&1
echo.
echo Using Python: %PYCMD%
echo          Path: %PY%
"%PY%" --version
if errorlevel 1 goto :pybroken

set "VPY=.venv\Scripts\python.exe"
REM A .venv copied from another machine is unusable - verify it can run.
if not exist "%VPY%" goto :needvenv
"%VPY%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto :havevenv
echo.
echo [WARN] Existing .venv cannot run on this machine - recreating it...

:needvenv
if exist ".venv" rmdir /s /q ".venv" >nul 2>&1
if exist ".venv" goto :venvlocked
echo.
echo Creating virtual environment .venv ...
"%PY%" -m venv .venv
if errorlevel 1 goto :venverr
if not exist "%VPY%" goto :venverr

:havevenv
echo.
echo Installing dependencies (first run is slower; later runs use cache)...
"%VPY%" -m pip install --upgrade pip >nul 2>&1
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :piperr

echo.
echo ===================================================
echo  AppliCraft local edition is starting
echo  Open in browser:  http://localhost:8000
echo  First time:  Settings - My LLM API, enter your own Key
echo  Data location:  backend\data\ on this machine (back it up)
echo  Stop server:  press Ctrl+C in this window, then close it
echo ===================================================
"%VPY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo Server stopped.
goto :eof

:cdfail
echo.
echo [ERROR] Cannot enter the backend folder.
echo         Make sure you extracted the whole ZIP before running this file.
echo.
pause
exit /b 1

:nopython
del "%TMPF%" >nul 2>&1
echo.
echo [ERROR] No usable Python 3.10+ was found on this computer.
echo.
echo         AppliCraft needs Python 3.10 or newer. It is the only thing
echo         you need to install by hand (Docker / Node / DB not needed).
echo.
echo         Important: a "python" under
echo           %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe
echo         is a Microsoft Store shortcut, NOT Python. It cannot run this
echo         project even though "where python" may list it.
echo.
echo         Fix:
echo           1) Install Python 3.10+ from https://www.python.org/downloads/
echo           2) During setup, tick "Add python.exe to PATH".
echo           3) Re-open this file after setup finishes.
echo         Optional: Settings ^> Apps ^> Advanced app settings ^>
echo                  App execution aliases ^> turn OFF python.exe / python3.exe.
echo.
pause
exit /b 1

:pybroken
echo.
echo [ERROR] The selected Python cannot be executed: "%PY%"
echo         Reinstall Python 3.10+ and run this file again.
echo.
pause
exit /b 1

:venvlocked
echo.
echo [ERROR] Cannot remove the old .venv folder.
echo         Close any program using it (terminal, editor, running server),
echo         then double-click this file again.
echo.
pause
exit /b 1

:venverr
echo.
echo [ERROR] Failed to create the virtual environment.
echo         Interpreter : "%PY%"
echo         Folder      : %CD%
echo.
echo         To see the real error, run this in a Command Prompt here:
echo           "%PY%" -m venv .venv
echo.
echo         Common causes:
echo           1) Python is a Microsoft Store alias or lacks the venv module.
echo           2) No write permission / antivirus / Controlled folder access.
echo           3) The project sits on a synced or read-only drive.
echo.
echo         The incomplete .venv has been removed; the next run will retry.
rmdir /s /q ".venv" >nul 2>&1
pause
exit /b 1

:piperr
echo.
echo [ERROR] Dependency installation failed. Common causes: no internet,
echo         a corporate proxy, or the network is unstable.
echo         Check your connection and double-click this file again to retry.
echo         If it still fails, send me the error shown above.
echo.
pause
exit /b 1
