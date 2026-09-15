@echo off
title Modern Diagnostic Center ERP
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  echo  [!] Python lama helin. Download: https://www.python.org/downloads/  ^(Add Python to PATH^)
  pause & exit /b
)
if not exist "venv\Scripts\activate.bat" (
  echo  First-time setup...
  python -m venv venv
  call venv\Scripts\activate.bat
  pip install -q -r requirements.txt
) else ( call venv\Scripts\activate.bat )
set DEMOFLAG=
if not exist "erp.db" set DEMOFLAG=--demo
start "" http://127.0.0.1:5000
python run.py %DEMOFLAG% %*
pause
