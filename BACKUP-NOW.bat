@echo off
REM ============================================================
REM   MDC ERP - Backup NOW (manual, one-click)
REM   Writes a JSON backup AND a raw .db snapshot into
REM   instance\backups\  (the app also backs up automatically
REM   every day while running).
REM ============================================================
cd /d "%~dp0"
echo Creating a backup...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "from mdc_erp import create_app; from mdc_erp.core.autobackup import write_backup; app=create_app(); p=write_backup(app, reason='manual'); print('Saved:', p)"
) else (
  python -c "from mdc_erp import create_app; from mdc_erp.core.autobackup import write_backup; app=create_app(); p=write_backup(app, reason='manual'); print('Saved:', p)"
)
echo.
echo Backups are in the  instance\backups  folder.
pause
