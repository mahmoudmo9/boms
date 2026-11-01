@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (echo Python 3.10+ is required. & pause & exit /b 1)
)
echo [2/3] Installing / checking dependencies...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (echo Could not install requirements. Check your internet connection. & pause & exit /b 1)
echo [3/3] Launching...
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
