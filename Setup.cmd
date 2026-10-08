@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Setup-tools.ps1"
if errorlevel 1 (
    echo.
    echo Setup failed. Check the error above and retry.
    pause
    exit /b 1
)
echo.
echo Tools are ready. Run Start.cmd or WuwaRu.exe.
pause
