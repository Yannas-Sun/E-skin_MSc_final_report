@echo off
setlocal EnableExtensions

if "%~1"=="" (set "MUX_US=100") else (set "MUX_US=%~1")

set "ROOT=%~dp0..\.."
set "SOURCE=%ROOT%\research\scan-rate\stm32\combined-system-sclk33"
set "TOOLCHAIN=%ROOT%\active\four-module-full-scan\stm32\combined-system\cmake\gcc-arm-none-eabi.cmake"
set "BUILD=%ROOT%\.cmake-build\STABLE_INTERNAL_EOC_MUX_%MUX_US%"
set "ELF=%BUILD%\ESKIN_STM32_SCLK33_EXPERIMENT.elf"
set "PROBE_UID=LU_2022_8888"
set "PATH=D:\study\programming\ArmGnuToolchain\bin;D:\study\programming\Ninja;D:\study\programming\CMake\bin;%PATH%"

echo ============================================================
echo Stable internal-clock + EOC MUX-settle experiment
echo MUX settle: %MUX_US% us
echo Stable acquisition strategy is retained; only MUX timing changes.
echo ============================================================

echo [1/3] Configuring isolated STM32 build...
cmake --fresh -S "%SOURCE%" -B "%BUILD%" -G Ninja ^
  -DCMAKE_MAKE_PROGRAM=D:/study/programming/Ninja/ninja.exe ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DSCLK33_PROFILE=stable_internal_eoc_mux_sweep ^
  -DSTABLE_EOC_MUX_SETTLE_US=%MUX_US% ^
  -DSCLK33_FSR_HZ=0 ^
  -DSCLK33_ACC_HZ=0 ^
  -DCMAKE_TOOLCHAIN_FILE="%TOOLCHAIN%"
if errorlevel 1 exit /b 1

echo [2/3] Building isolated STM32 image...
cmake --build "%BUILD%" -j 4
if errorlevel 1 exit /b 1

echo [3/3] Flashing Module STM32 through DAPLink...
pyocd flash -W -u %PROBE_UID% -t stm32g474cetx -f 1M -M under-reset ^
  -O reset_type=hw -e sector "%ELF%"
if errorlevel 1 exit /b 1
pyocd reset -W -u %PROBE_UID% -t stm32g474cetx -f 1M -M under-reset -m hw
exit /b %errorlevel%
