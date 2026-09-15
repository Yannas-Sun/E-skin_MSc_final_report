@echo off
setlocal EnableExtensions

if "%~1"=="" (set "MODE=FULL") else (set "MODE=%~1")
if /I "%MODE%"=="FULL" set "MODE_ID=0"
if /I "%MODE%"=="DELTA" set "MODE_ID=1"
if /I "%MODE%"=="SPATIAL" set "MODE_ID=2"
if not defined MODE_ID (
  echo ERROR: mode must be FULL, DELTA or SPATIAL.
  exit /b 2
)

set "PATH=D:\study\programming\ArmGnuToolchain\bin;D:\study\programming\Ninja;D:\study\programming\CMake\bin;%PATH%"
set "ROOT=%~dp0..\.."
set "SOURCE=%ROOT%\research\data-scalability\stm32"
set "BUILD=D:\study\programming\builds\ESKIN_DATA_SCALABILITY_%MODE_ID%"
set "PROBE_UID=LU_2022_8888"

echo [1/3] Configuring data scalability STM32 firmware: %MODE%...
cmake --fresh -S "%SOURCE%" -B "%BUILD%" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_TOOLCHAIN_FILE="%SOURCE%\cmake\gcc-arm-none-eabi.cmake" ^
  -DDATA_SCALABILITY_DEFAULT_MODE=%MODE_ID%
if errorlevel 1 exit /b 1

echo [2/3] Building...
cmake --build "%BUILD%" -j 4
if errorlevel 1 exit /b 1

echo [3/3] Flashing STM32 through DAPLink...
pyocd flash -W -u %PROBE_UID% -t stm32g474cetx -f 1M -M halt -e sector "%BUILD%\ESKIN_STM32.elf"
if errorlevel 1 (
  echo ERROR: STM32 flash failed. Check SWDIO, SWCLK, GND and target voltage.
  echo If the target is locked or cannot halt, connect nRESET and retry with under-reset.
  exit /b 1
)
echo Flash completed: %MODE%. STM32 was reset by pyOCD after programming.
endlocal
exit /b 0
