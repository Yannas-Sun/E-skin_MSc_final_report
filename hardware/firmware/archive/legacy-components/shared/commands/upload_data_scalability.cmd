@echo off
setlocal EnableExtensions

if "%~1"=="" goto usage
if "%~2"=="" goto usage
if "%~3"=="" goto usage

set "PORT=%~1"
set "MODULE=%~2"
set "MODE=%~3"
if not "%MODULE%"=="0" if not "%MODULE%"=="1" if not "%MODULE%"=="2" if not "%MODULE%"=="3" (
  echo ERROR: module must be 0, 1, 2 or 3.
  exit /b 2
)
if /I "%MODE%"=="FULL" set "MODE_ID=0"
if /I "%MODE%"=="DELTA" set "MODE_ID=1"
if /I "%MODE%"=="SPATIAL" set "MODE_ID=2"
if not defined MODE_ID (
  echo ERROR: mode must be FULL, DELTA or SPATIAL.
  exit /b 2
)

set "FIRMWARE_ROOT=%~dp0..\.."
set "SKETCH=%FIRMWARE_ROOT%\research\data-scalability\teensy"
set "BUILD=%FIRMWARE_ROOT%\.arduino-build\DATA_SCALABILITY_%MODULE%_%MODE_ID%"
set "FQBN=teensy:avr:teensy41"
set "ARDUINO_CLI=D:\study\programming\ArduinoCLI\arduino-cli.exe"
if exist "%ARDUINO_CLI%" goto cli_found
set "ARDUINO_CLI=arduino-cli.exe"
where "%ARDUINO_CLI%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: arduino-cli.exe was not found.
  exit /b 3
)

:cli_found
echo [1/2] Compiling data scalability bridge: module %MODULE%, mode %MODE%...
"%ARDUINO_CLI%" compile --fqbn "%FQBN%" --build-path "%BUILD%" ^
  --build-property "build.flags.defs=-D__IMXRT1062__ -DTEENSYDUINO=160 -DSCALABILITY_MODULE_ID=%MODULE% -DDATA_SCALABILITY_DEFAULT_MODE=%MODE_ID%" ^
  "%SKETCH%"
if errorlevel 1 exit /b 1

echo [2/2] Uploading through %PORT%...
"%ARDUINO_CLI%" upload --port "%PORT%" --fqbn "%FQBN%" --input-dir "%BUILD%"
if errorlevel 1 (
  echo Upload failed. Press the Teensy Program button once if the loader is waiting.
  exit /b 1
)

echo Data scalability bridge upload complete: %MODE% / module %MODULE%.
exit /b 0

:usage
echo Usage: %~nx0 ^<COM-port^> ^<module-id 0..3^> ^<FULL^|DELTA^|SPATIAL^>
exit /b 2
