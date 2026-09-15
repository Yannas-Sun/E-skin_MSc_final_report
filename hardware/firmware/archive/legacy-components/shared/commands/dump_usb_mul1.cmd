@echo off
setlocal EnableExtensions

if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")
if "%~2"=="" (set "SECONDS=10") else (set "SECONDS=%~2")
if "%~3"=="" (set "BAUD=2000000") else (set "BAUD=%~3")

set "ROOT=%~dp0..\.."
python -u "%ROOT%\active\four-module-full-scan\tools\dump_usb_stream.py" --port "%PORT%" --seconds "%SECONDS%" --baud "%BAUD%"
exit /b %errorlevel%
