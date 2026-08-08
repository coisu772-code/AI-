@echo off
setlocal
title AI Video Channel Production - Unified Installer
echo AI Video Channel Production v0.11.0-rc.4
echo Includes the Windows PowerShell 5.1 no-BOM JSONL file-relay health fix.
echo Choose the program folder and the user data folder once.
echo Large sources, documents, audio, images, workshop files and videos use the selected user data folder.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-AIVideoChannelProductionInstall.ps1" -AssetRoot "%~dp0" -InstallMode Auto
if errorlevel 1 (
  echo Installation failed. Review the message above.
  pause
  exit /b 1
)
echo Installation completed. Restart Codex and create a new task.
pause
