@echo off
setlocal EnableExtensions

if "%~1"=="" (set "PROBE_UID=LU_2022_8888") else (set "PROBE_UID=%~1")
if "%~2"=="" (set "SWD_SPEED=1M") else (set "SWD_SPEED=%~2")

set "PATH=D:\study\programming\ArmGnuToolchain\bin;D:\study\programming\Ninja;D:\study\programming\CMake\bin;%PATH%"
set "ROOT=%~dp0..\.."
set "SOURCE=%ROOT%\active\four-module-full-scan\stm32\combined-system"
set "BUILD=D:\study\programming\builds\ESKIN_COMBINED_SYSTEM"

echo [1/3] Configuring active four-module FSR-only STM32 firmware...
cmake --fresh -S "%SOURCE%" -B "%BUILD%" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE="%SOURCE%\cmake\gcc-arm-none-eabi.cmake"
if errorlevel 1 exit /b 1

echo [2/3] Building active four-module FSR-only STM32 firmware...
cmake --build "%BUILD%" -j 4
if errorlevel 1 exit /b 1

echo [3/3] Flashing active 1044-byte protocol to probe %PROBE_UID% at %SWD_SPEED%...
pyocd flash -W -u %PROBE_UID% -t stm32g474cetx -f %SWD_SPEED% -M under-reset -e sector "%BUILD%\ESKIN_STM32.elf"
if errorlevel 1 exit /b 1

echo Active STM32 flash complete. Reset or power-cycle this module before testing.
echo Repeat this command for each STM32 module/probe, then upload the active Teensy bridge.
endlocal
exit /b 0
