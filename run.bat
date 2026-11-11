@echo off
chcp 65001 >nul
title brainmem
set "BM=%~dp0"
if not exist "%BM%.venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run: python deploy.py --repair
  pause >nul
  exit /b 1
)
"%BM%.venv\Scripts\python.exe" "%BM%launcher.py"
echo.
echo Done. Press any key to close...
pause >nul
