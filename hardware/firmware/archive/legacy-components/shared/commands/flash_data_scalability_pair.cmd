@echo off
setlocal
if "%~1"=="" goto usage
if "%~2"=="" goto usage
if "%~3"=="" goto usage

set "PORT=%~1"
set "MODULE=%~2"
set "MODE=%~3"

echo [STM32] Building and flashing data scalability firmware: %MODE%...
call "%~dp0flash_data_scalability.cmd" "%MODE%"
if errorlevel 1 exit /b 1

echo [Teensy] Building and uploading module %MODULE% bridge: %MODE%...
call "%~dp0upload_data_scalability.cmd" "%PORT%" "%MODULE%" "%MODE%"
if errorlevel 1 exit /b 1

if "%~4"=="" goto complete
echo [GUI] Starting data scalability parser (%~4)...
call "%~dp0start_data_scalability_monitor.cmd" "%PORT%" "%~4" "2000000" "%MODULE%"

:complete
echo Data scalability pair is ready: module %MODULE%, mode %MODE%.
endlocal
exit /b 0

:usage
echo Usage: %~nx0 ^<COM-port^> ^<module-id 0..3^> ^<FULL^|DELTA^|SPATIAL^> [all^|fsr1^|fsr2^|acc]
exit /b 2
