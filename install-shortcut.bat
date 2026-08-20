@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-shortcut.ps1"
if errorlevel 1 (
  echo.
  echo 创建快捷方式失败，请检查上方提示。
  pause
  exit /b 1
)
echo.
echo 可以从桌面双击“Yantu 研途”启动。
pause
