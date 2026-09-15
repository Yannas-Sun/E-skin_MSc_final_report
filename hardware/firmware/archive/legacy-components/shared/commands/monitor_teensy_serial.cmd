@echo off
setlocal EnableExtensions

if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")
if "%~2"=="" (set "BAUD=115200") else (set "BAUD=%~2")

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
echo Waiting for %PORT% to reconnect...
timeout /t 2 /nobreak >nul
echo Opening %PORT% at %BAUD% baud. Press Ctrl+C to stop the monitor.
"%ARDUINO_CLI%" monitor --port "%PORT%" --config "baudrate=%BAUD%"
exit /b %errorlevel%
