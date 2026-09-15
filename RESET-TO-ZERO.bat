@echo off
REM ============================================================
REM   MDC ERP - Reset to ZERO (start working with a clean system)
REM   Clears all transactions/demo data. Keeps users, settings,
REM   chart of accounts, service catalog, doctors, branches.
REM   A backup of the database is made automatically first.
REM ============================================================
cd /d "%~dp0"
echo.
echo   This will RESET the system to zero (a backup is made first).
echo   Keeps: users, settings, chart of accounts, services, doctors.
echo   Clears: patients, invoices, payments, ledger, stock, assets...
echo.
set /p CONFIRM=Type YES to continue:
if /I not "%CONFIRM%"=="YES" goto :cancel
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" reset_to_zero.py --yes
) else (
  python reset_to_zero.py --yes
)
echo.
echo   Done. Start the system with START-MDC-ERP.bat and log in.
pause
goto :eof
:cancel
echo Cancelled. Nothing changed.
pause
