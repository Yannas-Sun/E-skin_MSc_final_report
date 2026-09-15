@echo off
setlocal EnableExtensions

if "%~1"=="" goto usage
if "%~2"=="" goto usage

set "PORT=%~1"
set "MODULE=%~2"
if not "%MODULE%"=="0" if not "%MODULE%"=="1" if not "%MODULE%"=="2" if not "%MODULE%"=="3" (
  echo ERROR: module must be 0, 1, 2 or 3.
  exit /b 2
)

set "ROOT=%~dp0..\.."
set "SKETCH=%ROOT%\diagnostics\module-slot\module-slot-test"
set "BUILD=%ROOT%\.arduino-build\SCALABLITY_MODULE_%MODULE%"
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
echo [1/2] Compiling selectable Module %MODULE% bridge...
rem Teensy 1.62.0 does not reference compiler.cpp.extra_flags in its
rem recipe.cpp.o.pattern. Inject the selector through build.flags.defs,
rem while retaining the two Teensy core defines normally supplied there.
"%ARDUINO_CLI%" compile --fqbn "%FQBN%" --build-path "%BUILD%" ^
  --build-property "build.flags.defs=-D__IMXRT1062__ -DTEENSYDUINO=160 -DSCALABILITY_MODULE_ID=%MODULE%" ^
  "%SKETCH%"
if errorlevel 1 exit /b 1

echo [2/2] Uploading Module %MODULE% bridge through %PORT%...
"%ARDUINO_CLI%" upload --port "%PORT%" --fqbn "%FQBN%" --input-dir "%BUILD%"
if errorlevel 1 (
  echo Upload failed. If Teensy Loader is waiting, press the Teensy Program button once.
  exit /b 1
)

echo Scalablity Module %MODULE% bridge upload complete.
exit /b 0

:usage
echo Usage: %~nx0 ^<COM-port^> ^<module-id 0..3^>
exit /b 2
