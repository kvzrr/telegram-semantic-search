@echo off
title Telegram Semantic Search - Launcher
color 0A

echo ===================================================
echo   Telegram Semantic Search: Starting...
echo ===================================================
echo.

:: 1. Check Python
echo [1/4] Checking environment...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.10+ and check "Add Python to PATH".
    pause
    exit /b
)

:: 2. Change directory to script location
cd /d "%~dp0"

:: 3. Virtual Environment setup
if not exist "venv\" (
    echo [2/4] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        pause
        exit /b
    )
    
    echo [3/4] Installing dependencies...
    echo This may take up to 10 minutes, please wait...
    call venv\Scripts\activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    echo [2/4] Virtual environment found.
    echo [3/4] Activating...
    call venv\Scripts\activate
)

:: 4. Run Application
echo [4/4] Launching UI in browser...
echo ---------------------------------------------------
echo APP IS RUNNING. 
echo DO NOT CLOSE THIS WINDOW.
echo ---------------------------------------------------
echo.

:: Run streamlit from source folder
streamlit run source/app.py

if errorlevel 1 (
    echo.
    echo [ERROR] Application crashed.
    pause
)
