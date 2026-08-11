@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\start.bat"
exit /b %ERRORLEVEL%
