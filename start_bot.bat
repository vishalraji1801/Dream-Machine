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
    echo Authentication failed. Press any key to exit.
    pause >nul
    exit /b 1
)

echo.
echo Starting bot...
echo.
.venv\Scripts\python.exe main.py

echo.
echo Bot stopped. Press any key to close.
pause >nul
