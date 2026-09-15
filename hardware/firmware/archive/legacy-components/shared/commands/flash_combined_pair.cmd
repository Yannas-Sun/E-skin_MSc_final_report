@echo off
setlocal
set "ROOT=%~dp0..\.."
if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")

echo [STM32] Building and flashing the combined acquisition firmware...
call "%~dp0original\flash_combined.cmd"
if errorlevel 1 exit /b 1

echo [Teensy] Building and uploading the combined USB bridge...
call "%~dp0upload_teensy_sketch.cmd" ^
  "%ROOT%\diagnostics\single-module-combined\teensy\ESKIN_COMBINED_BRIDGE" ^
  "%PORT%" "TEENSY_COMBINED_BRIDGE"
if errorlevel 1 exit /b 1

echo [GUI] Waiting for the Teensy USB serial port to reconnect...
timeout /t 2 /nobreak >nul
echo [GUI] Opening the combined monitor on %PORT%...
call "%~dp0original\start_combined_monitor.cmd" "%PORT%" all
exit /b %errorlevel%
