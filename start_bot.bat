@echo off
title Trading Bot V1
cd /d "%~dp0"

echo.
echo =========================================
echo  Trading Bot V1 — Starting...
echo =========================================
echo.

.venv\Scripts\python.exe auth.py
if errorlevel 1 (
    echo.
    echo Bot not started ^(auth failed or market closed — see message above^).
    echo Press any key to exit.
    pause >nul
    exit /b 1
)

:run
echo.
echo Starting bot...
echo.
.venv\Scripts\python.exe main.py
if errorlevel 1 (
    echo.
    echo Bot CRASHED — restarting in 15 seconds... ^(Ctrl+C to abort^)
    timeout /t 15 /nobreak >nul
    goto run
)

echo.
echo Bot stopped cleanly. Press any key to close.
pause >nul
