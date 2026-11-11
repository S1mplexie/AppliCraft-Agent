@echo off
setlocal
cd /d "%~dp0backend"

REM Locate Python (Windows usually has "python"; fall back to "py" launcher)
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY goto :nopython

echo Using Python:
%PY% --version

REM Create virtual environment if missing
if exist ".venv" goto :havevenv
echo.
echo Creating virtual environment .venv ...
%PY% -m venv .venv
if errorlevel 1 goto :venverr
:havevenv

set "VPY=.venv\Scripts\python.exe"
if exist "%VPY%" goto :havevpy
goto :vpyerr
:havevpy

REM Install dependencies
echo.
echo Installing dependencies (first run is slower; later runs use cache)...
"%VPY%" -m pip install --upgrade pip >nul 2>&1
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :piperr

REM Start the server
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
echo Server stopped. To restart, double-click this file again.
pause
goto :eof

:nopython
echo [ERROR] Python was not found. Please install Python 3.10 or newer and make
echo          sure to tick "Add python.exe to PATH" during setup, then re-open.
echo          Download: https://www.python.org/downloads/
echo.
pause
exit /b 1

:venverr
echo [ERROR] Failed to create the virtual environment.
pause
exit /b 1

:vpyerr
echo [ERROR] Virtual environment is incomplete (missing .venv\Scripts\python.exe).
pause
exit /b 1

:piperr
echo.
echo [ERROR] Dependency installation failed. Common causes: no internet,
echo         a corporate proxy is blocking, or the network is unstable.
echo         Check your connection and double-click this file again to retry.
echo         If it still fails, send me the error shown above.
echo.
pause
exit /b 1
