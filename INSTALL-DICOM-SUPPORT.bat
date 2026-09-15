@echo off
title MDC ERP - Install DICOM Support
cd /d "%~dp0"
color 0B
echo.
echo   Installing PACS / DICOM support (pydicom, numpy, Pillow)...
echo.
if not exist "venv\Scripts\activate.bat" (
  echo   [!] Setup not found. Run START-MDC-ERP.bat first.
  pause
  exit /b
)
call venv\Scripts\activate.bat
pip install -r requirements-optional.txt
echo.
echo   Done. Restart the ERP to enable DICOM import.
pause
