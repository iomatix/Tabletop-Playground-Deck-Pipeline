@echo off
setlocal
title TTPG Deck Pipeline Launcher
cd /d "%~dp0"

echo [1/3] Checking Python environment...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found in the PATH variable.
    echo Install Python 3.10+ from python.org and make sure to check "Add python.exe to PATH".
    pause
    exit /b 1
)

echo [2/3] Verifying and installing dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] A problem occurred while installing packages from requirements.txt.
    pause
    exit /b 1
)

echo [3/3] Launching NiceGUI interface...
python gui_app.py

pause
