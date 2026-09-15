@echo off
REM Creates a Desktop shortcut named "MDC ERP" that launches the system.
cd /d "%~dp0"
set TARGET=%~dp0START-MDC-ERP.bat
set SHORTCUT=%USERPROFILE%\Desktop\MDC ERP.lnk
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT%'); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,171'; $s.Description='Modern Diagnostic Center ERP'; $s.Save()"
echo.
echo  Shortcut "MDC ERP" waa la sameeyay Desktop-ka / created on your Desktop.
echo  Hadda Desktop-ka double-click "MDC ERP" si aad u furto.
echo.
pause
