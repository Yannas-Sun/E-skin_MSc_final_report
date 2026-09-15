@echo off
setlocal EnableExtensions

if "%~1"=="" goto usage

set "SKETCH=%~f1"
if "%~2"=="" (set "PORT=COM9") else (set "PORT=%~2")
if "%~3"=="" (set "BUILD_NAME=TEENSY_SKETCH") else (set "BUILD_NAME=%~3")
set "EXTRA_BUILD_DEFS=%~4"
set "FQBN=teensy:avr:teensy41"
set "ROOT=%~dp0..\.."
set "BUILD=%ROOT%\.arduino-build\%BUILD_NAME%"

if not exist "%SKETCH%" (
  echo ERROR: Sketch directory not found: "%SKETCH%"
  exit /b 2
)

set "ARDUINO_CLI=D:\study\programming\ArduinoCLI\arduino-cli.exe"
if exist "%ARDUINO_CLI%" goto cli_found

set "ARDUINO_CLI=arduino-cli.exe"
where "%ARDUINO_CLI%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: arduino-cli.exe was not found.
  echo Expected: D:\study\programming\ArduinoCLI\arduino-cli.exe
  exit /b 3
)

:cli_found
echo [1/2] Compiling Teensy 4.1 sketch...
if defined EXTRA_BUILD_DEFS goto compile_with_defs
"%ARDUINO_CLI%" compile --fqbn "%FQBN%" --build-path "%BUILD%" "%SKETCH%"
goto compile_done

:compile_with_defs
rem Teensy 1.62.0 does not reference compiler.cpp.extra_flags in its
rem recipe.cpp.o.pattern, so append compile-time selectors to build.flags.defs.
"%ARDUINO_CLI%" compile --fqbn "%FQBN%" --build-path "%BUILD%" ^
  --build-property "build.flags.defs=-D__IMXRT1062__ -DTEENSYDUINO=160 %EXTRA_BUILD_DEFS%" ^
  "%SKETCH%"

:compile_done
if errorlevel 1 exit /b 1

echo [2/2] Uploading Teensy 4.1 sketch through %PORT%...
"%ARDUINO_CLI%" upload --port "%PORT%" --fqbn "%FQBN%" --input-dir "%BUILD%"
if errorlevel 1 (
  echo Upload failed. If Teensy Loader is waiting, press the Teensy Program button once.
  exit /b 1
)

echo Teensy compile and upload complete.
exit /b 0

:usage
echo Usage: %~nx0 ^<sketch-directory^> [COM-port] [build-name] [extra-build-defs]
exit /b 2
