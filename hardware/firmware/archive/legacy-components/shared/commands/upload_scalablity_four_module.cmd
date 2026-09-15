@echo off
setlocal EnableExtensions

if "%~1"=="" goto usage

set "PORT=%~1"
if "%~2"=="" (set "DEFAULT_SCAN_HZ=200") else (set "DEFAULT_SCAN_HZ=%~2")
set /a VALIDATED_SCAN_HZ=DEFAULT_SCAN_HZ 2>nul
if not "%VALIDATED_SCAN_HZ%"=="%DEFAULT_SCAN_HZ%" goto invalid_scan_hz
if %VALIDATED_SCAN_HZ% LSS 0 goto invalid_scan_hz
if %VALIDATED_SCAN_HZ% GTR 1000 goto invalid_scan_hz
set "ROOT=%~dp0..\.."
set "SKETCH=%ROOT%\active\four-module-full-scan\teensy\four_module"
set "BUILD_NAME=SCALABLITY_FOUR_MODULE_%VALIDATED_SCAN_HZ%HZ"
set "BUILD_DEFS=-DESKIN_DEFAULT_SCAN_HZ=%VALIDATED_SCAN_HZ%"

echo [Teensy] Building and uploading four-module bridge through %PORT%...
echo [Teensy] Startup default scan rate: %VALIDATED_SCAN_HZ% Hz
call "%~dp0upload_teensy_sketch.cmd" "%SKETCH%" "%PORT%" "%BUILD_NAME%" "%BUILD_DEFS%"
if errorlevel 1 exit /b 1

echo Four-module bridge upload complete. Startup default: %VALIDATED_SCAN_HZ% Hz.
exit /b 0

:invalid_scan_hz
echo ERROR: default-scan-hz must be an integer from 0 to 1000.
exit /b 2

:usage
echo Usage: %~nx0 ^<COM-port^> [default-scan-hz 0..1000]
exit /b 2
