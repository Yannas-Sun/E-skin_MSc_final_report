@echo off
setlocal EnableExtensions

if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")
if "%~2"=="" (set "MODULE=1") else (set "MODULE=%~2")
if not "%MODULE%"=="0" if not "%MODULE%"=="1" if not "%MODULE%"=="2" if not "%MODULE%"=="3" (
  echo ERROR: module must be 0, 1, 2 or 3.
  exit /b 2
)

set "ROOT=%~dp0..\.."
set "SKETCH=%ROOT%\research\scan-rate\teensy\internal_fifo_dma_bridge"
set "COMMON_BRIDGE=%ROOT%\diagnostics\single-module-combined\teensy\ESKIN_COMBINED_BRIDGE"
set "BUILD=%ROOT%\.arduino-build\INTERNAL_FIFO_DMA_MODULE_%MODULE%"
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
echo [1/2] Compiling internal FIFO-DMA bridge for Module %MODULE%...
"%ARDUINO_CLI%" compile --fqbn "%FQBN%" --build-path "%BUILD%" ^
  --build-property "build.flags.defs=-D__IMXRT1062__ -DTEENSYDUINO=160 -DSCALABILITY_MODULE_ID=%MODULE% -I%COMMON_BRIDGE%" ^
  "%SKETCH%"
if errorlevel 1 exit /b 1

echo [2/2] Uploading bridge through %PORT%...
"%ARDUINO_CLI%" upload --port "%PORT%" --fqbn "%FQBN%" --input-dir "%BUILD%"
if errorlevel 1 (
  echo Upload failed. If Teensy Loader is waiting, press Program once.
  exit /b 1
)
exit /b 0
