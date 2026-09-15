@echo off
setlocal EnableExtensions

if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")
if "%~2"=="" (set "VIEW=all") else (set "VIEW=%~2")
if "%~3"=="" (set "BAUD=2000000") else (set "BAUD=%~3")
if "%~4"=="" (set "MODULE=0") else (set "MODULE=%~4")

set "FIRMWARE_ROOT=%~dp0..\.."
for %%I in ("%FIRMWARE_ROOT%\..\..\..") do set "PROJECT_ROOT=%%~fI"
set "MONITOR=%PROJECT_ROOT%\docs\Final\Calibration scalability\script\Main\data_scalability_monitor.py"
if not exist "%MONITOR%" (
  echo ERROR: data scalability parser not found:
  echo "%MONITOR%"
  exit /b 2
)

echo Starting data scalability monitor on %PORT% (%VIEW%), module %MODULE%...
python -u "%MONITOR%" --port "%PORT%" --view "%VIEW%" --baud "%BAUD%" --module "%MODULE%"
exit /b %errorlevel%
