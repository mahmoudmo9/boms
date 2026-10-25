@echo off
rem Runs backup.ps1 with Windows PowerShell 5.1, independent of the execution policy.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup.ps1" %*
set BOMS_EXIT=%ERRORLEVEL%
pause
exit /b %BOMS_EXIT%
