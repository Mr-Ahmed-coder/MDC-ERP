@echo off
title MDC ERP - NETWORK (Wi-Fi)
cd /d "%~dp0"
color 0B

echo.
echo   ==================================================
echo      MDC ERP  -  NETWORK MODE (Wi-Fi / offline internet)
echo   ==================================================
echo.

REM ---- Python check ----
python --version >nul 2>&1
if errorlevel 1 (
  color 0C
  echo   [!] Python lama helin. Download: https://www.python.org/downloads/  ^(Add Python to PATH^)
  pause & exit /b
)

REM ---- first-time setup ----
if not exist "venv\Scripts\activate.bat" (
  echo   Diyaarinta koowaad... / First-time setup...
  python -m venv venv
  call venv\Scripts\activate.bat
  python -m pip install --upgrade pip -q
  pip install -q -r requirements.txt
) else ( call venv\Scripts\activate.bat )

set DEMOFLAG=
if not exist "erp.db" set DEMOFLAG=--demo

REM ---- find this computer's Wi-Fi IP address ----
set IPADDR=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=* delims= " %%b in ("%%a") do set IPADDR=%%b
)

echo.
echo   ==================================================
echo      WUU SHAQEYNAYAA / RUNNING
echo.
echo      Kombiyuutarkan / this computer:  http://127.0.0.1:5000
echo.
echo      TALEEFANKA / PHONES ^& other devices ^(same Wi-Fi^):
echo         http://%IPADDR%:5000
echo.
echo      Login:  admin  /  password set during initialization
echo      STOP:   close this window  or  CTRL+C
echo   ==================================================
echo.

start "" /min cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5000"

REM ---- run in NETWORK mode (reachable from other devices) ----
python run.py --online %DEMOFLAG% %*
echo.
echo   Nidaamku wuu joogsaday / stopped.
pause
