@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
set "YANTU_EXIT=%ERRORLEVEL%"

if not "%YANTU_EXIT%"=="0" (
  echo.
  echo Yantu failed to start. Review the messages above.
  echo Exit code: %YANTU_EXIT%
  pause
)

exit /b %YANTU_EXIT%
