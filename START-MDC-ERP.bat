@echo off
title Modern Diagnostic Center ERP
cd /d "%~dp0"
color 0A

echo.
echo   ==================================================
echo      MODERN DIAGNOSTIC CENTER - ERP
echo   ==================================================
echo.

REM ---------- 1. Check Python ----------
python --version >nul 2>&1
if errorlevel 1 (
  color 0C
  echo   [!] Python lama helin / Python not found.
  echo.
  echo       Ka soo deji / Download:  https://www.python.org/downloads/
  echo       MUHIIM: markaad rakibayso, calaamadee "Add Python to PATH".
  echo.
  pause
  exit /b
)

REM ---------- 2. First-time setup (only once) ----------
if not exist "venv\Scripts\activate.bat" (
  echo   Diyaarinta koowaad... / First-time setup ^(daqiiqado ayey qaadan kartaa^)...
  echo   Fadlan sug / Please wait...
  python -m venv venv
  call venv\Scripts\activate.bat
  python -m pip install --upgrade pip -q
  pip install -q -r requirements.txt
  REM optional PACS/DICOM support — best-effort, never blocks startup
  pip install -q -r requirements-optional.txt 2>nul
  echo   Diyaar / Setup complete.
) else (
  call venv\Scripts\activate.bat
)

REM ---------- 3. Load demo data only on the very first run ----------
set DEMOFLAG=
if not exist "erp.db" set DEMOFLAG=--demo

echo.
echo   ==================================================
echo      WUU SHAQEYNAYAA / RUNNING
echo.
echo      Browser:  http://127.0.0.1:5000
echo      Login:    admin  /  password set during initialization
echo.
echo      Si aad u JOOJISO / To STOP: close this window
echo                                  or press CTRL+C
echo   ==================================================
echo.

REM ---------- 4. Open the browser automatically (after the server starts) ----------
start "" /min cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5000"

REM ---------- 5. Start the ERP ----------
python run.py %DEMOFLAG% %*

echo.
echo   Nidaamku wuu joogsaday / The system has stopped.
pause
