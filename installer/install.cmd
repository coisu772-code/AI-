@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-AIVideoChannelProduction.ps1" -RuntimeMode Online
if errorlevel 1 (
  echo Installation failed. Review the message above.
  pause
  exit /b 1
)
echo Installation completed. Restart Codex and create a new task.
pause
