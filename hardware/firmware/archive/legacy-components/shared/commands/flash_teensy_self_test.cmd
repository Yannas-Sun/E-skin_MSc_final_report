@echo off
setlocal
set "ROOT=%~dp0..\.."
if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")

call "%~dp0upload_teensy_sketch.cmd" ^
  "%ROOT%\diagnostics\teensy-self-test\TEENSY_SELF_TEST" "%PORT%" "TEENSY_SELF_TEST"
if errorlevel 1 exit /b 1

echo [Monitor] Opening the Teensy self-test output...
call "%~dp0monitor_teensy_serial.cmd" "%PORT%" 115200
exit /b %errorlevel%
