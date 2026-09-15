@echo off
setlocal
if "%~1"=="" goto usage
set "PORT=%~1"
if "%~2"=="" (set "DEFAULT_SCAN_HZ=200") else (set "DEFAULT_SCAN_HZ=%~2")

call "%~dp0upload_scalablity_four_module.cmd" "%PORT%" "%DEFAULT_SCAN_HZ%"
if errorlevel 1 exit /b 1

echo [GUI] Waiting for the Teensy USB serial port to reconnect...
timeout /t 2 /nobreak >nul
call "%~dp0start_scalablity_four_module.cmd" "%PORT%"
exit /b %errorlevel%

:usage
echo Usage: %~nx0 ^<COM-port^> [default-scan-hz 0..1000]
exit /b 2
