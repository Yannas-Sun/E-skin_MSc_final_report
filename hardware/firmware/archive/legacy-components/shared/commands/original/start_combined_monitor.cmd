@echo off
setlocal
set "ROOT=%~dp0..\..\.."
if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")
if "%~2"=="" (set "VIEW=all") else (set "VIEW=%~2")
python -u "%ROOT%\diagnostics\single-module-combined\teensy\ESKIN_COMBINED_BRIDGE\live_combined_monitor.py" --port "%PORT%" --view "%VIEW%"
exit /b %errorlevel%
