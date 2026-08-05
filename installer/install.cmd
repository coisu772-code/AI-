@echo off
setlocal
title AI Video Channel Production - Unified Installer
echo AI Video Channel Production v0.10.1-rc.1
echo Includes the Windows PowerShell 5.1 no-BOM JSONL file-relay health fix.
echo Verifying every locked release asset before installation...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-AIVideoChannelProduction.ps1" -AssetRoot "%~dp0" -InstallMode Auto
if errorlevel 1 (
  echo Installation failed. Review the message above.
  pause
  exit /b 1
)
echo Installation completed. Restart Codex and create a new task.
pause
