@echo off
REM ============================================================
REM   MDC ERP - Restore database from a snapshot
REM   STOP the server first (close START-MDC-ERP window).
REM   Backs up the current database, then restores your choice.
REM ============================================================
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" restore_backup.py
) else (
  python restore_backup.py
)
pause
