@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call Run_Windows.bat
if not exist ".venv\Scripts\python.exe" exit /b 1
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --onedir --name SetadSuite ^
  --collect-all playwright --collect-all bs4 --collect-all docxtpl ^
  --paths inquiries --add-data "assets;assets" --add-data "inquiries;inquiries" ^
  --hidden-import app --hidden-import engine --hidden-import ui_kit --hidden-import ui_preview --hidden-import docx --hidden-import openpyxl --hidden-import py7zr --hidden-import rarfile main.py
if errorlevel 1 (echo EXE build failed. & pause & exit /b 1)
echo Build complete: dist\SetadSuite\SetadSuite.exe
pause
