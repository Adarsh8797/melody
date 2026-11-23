@echo off
title Melody Backend Server
color 0A
cd /d "%~dp0"

echo ============================================
echo    Starting Melody Backend Server
echo ============================================
echo.
echo Working directory: %CD%
echo.

REM Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] venv not found!
    echo Expected: %CD%\venv\Scripts\python.exe
    echo.
    echo Please run: python -m venv venv
    pause
    exit /b 1
)

echo [OK] venv found
echo.
echo Starting server...
echo.

REM Start the server
venv\Scripts\python.exe main.py

REM If server crashes, show error
if errorlevel 1 (
    echo.
    echo ============================================
    echo    Server CRASHED with error!
    echo ============================================
    pause
)