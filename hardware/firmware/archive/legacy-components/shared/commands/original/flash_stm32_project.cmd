@echo off
setlocal EnableExtensions
set "PATH=D:\study\programming\ArmGnuToolchain\bin;D:\study\programming\Ninja;D:\study\programming\CMake\bin;%PATH%"
set "ROOT=%~dp0..\..\.."
set "PROBE_UID=LU_2022_8888"
set "BUILD_TYPE=Debug"
set "FSR_NO_AUTO_RESET=0"

if /i "%~1"=="fsr1" (
  set "PROJECT=diagnostics\fsr\stm32\fsr1"
  set "BUILD_NAME=ESKIN_FSR1"
  set "BUILD_TYPE=Release"
  set "FSR_NO_AUTO_RESET=1"
)
if /i "%~1"=="fsr2" (
  set "PROJECT=diagnostics\fsr\stm32\fsr2"
  set "BUILD_NAME=ESKIN_FSR2"
  set "FSR_NO_AUTO_RESET=1"
)
if /i "%~1"=="fsr1-adc" (
  set "PROJECT=diagnostics\fsr\stm32\fsr1-adc-channel"
  set "BUILD_NAME=ESKIN_FSR1_ADC_CHANNEL"
)
if /i "%~1"=="acc-whoami" (
  set "PROJECT=diagnostics\acc\stm32\acc-a1-a5-whoami"
  set "BUILD_NAME=ESKIN_ACC_A1_A5_WHOAMI"
)
if /i "%~1"=="spi-pattern" (
  set "PROJECT=diagnostics\host-spi\spi-pattern-test\ESKIN_STM32_PATTERN"
  set "BUILD_NAME=ESKIN_SPI_PATTERN"
)

if not defined PROJECT goto usage
set "SOURCE=%ROOT%\%PROJECT%"
set "BUILD=D:\study\programming\builds\%BUILD_NAME%"

cmake --fresh -S "%SOURCE%" -B "%BUILD%" -G Ninja -DCMAKE_BUILD_TYPE=%BUILD_TYPE% -DCMAKE_TOOLCHAIN_FILE="%SOURCE%\cmake\gcc-arm-none-eabi.cmake"
if errorlevel 1 exit /b 1
cmake --build "%BUILD%" -j 4
if errorlevel 1 exit /b 1
if "%FSR_NO_AUTO_RESET%"=="1" goto flash_fsr_no_reset

pyocd flash -W -u %PROBE_UID% -t stm32g474cetx -f 10k -M under-reset -O reset_type=hw -e sector "%BUILD%\ESKIN_STM32.elf"
if errorlevel 1 exit /b 1
pyocd reset -W -u %PROBE_UID% -t stm32g474cetx -f 10k -M under-reset -m hw
exit /b %errorlevel%

:flash_fsr_no_reset
echo [3/3] Flashing FSR STM32 at 1 MHz without automatic reset...
pyocd flash -W -u %PROBE_UID% -t stm32g474cetx -f 1M -M under-reset --no-reset -e sector "%BUILD%\ESKIN_STM32.elf"
if errorlevel 1 exit /b 1
echo Flash completed. Manually reset or power-cycle the STM32 before runtime testing.
exit /b 0

:usage
echo Usage: %~nx0 ^<fsr1^|fsr2^|fsr1-adc^|acc-whoami^|spi-pattern^>
exit /b 2
