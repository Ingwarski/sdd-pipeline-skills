@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
set "UPDATE_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %UPDATE_EXIT%
