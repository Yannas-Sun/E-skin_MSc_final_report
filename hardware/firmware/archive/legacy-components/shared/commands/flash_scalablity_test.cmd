@echo off
setlocal

if "%~1"=="" goto usage
if "%~2"=="" goto usage

set "PORT=%~1"
set "MODULE=%~2"
if "%~3"=="" (set "VIEW=all") else (set "VIEW=%~3")
set "ROOT=%~dp0..\.."

echo [Teensy] Uploading selectable scalability Module %MODULE% bridge...
call "%~dp0upload_scalablity_test.cmd" "%PORT%" "%MODULE%"
if errorlevel 1 exit /b 1

echo [GUI] Waiting for the Teensy USB serial port to reconnect...
timeout /t 2 /nobreak >nul
echo [GUI] Opening the existing combined monitor on %PORT%...
call "%~dp0original\start_combined_monitor.cmd" "%PORT%" "%VIEW%"
exit /b %errorlevel%

:usage
echo Usage: %~nx0 ^<COM-port^> ^<module-id 0..3^> [all^|fsr1^|fsr2^|acc]
exit /b 2
