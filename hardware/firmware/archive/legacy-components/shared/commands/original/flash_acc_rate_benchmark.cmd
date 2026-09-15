@echo off
setlocal EnableExtensions

if "%~1"=="" (set "MODE=hr1344") else (set "MODE=%~1")
if /I "%MODE%"=="hr1344" (set "PROFILE=acc_hr1344") else if /I "%MODE%"=="lp5376" (set "PROFILE=acc_lp5376") else goto invalid_mode

set "PATH=D:\study\programming\ArmGnuToolchain\bin;D:\study\programming\Ninja;D:\study\programming\CMake\bin;%PATH%"
set "ROOT=%~dp0..\..\.."
set "SOURCE=%ROOT%\research\scan-rate\stm32\combined-system-sclk33"
set "TOOLCHAIN=%ROOT%\active\four-module-full-scan\stm32\combined-system\cmake\gcc-arm-none-eabi.cmake"
set "BUILD=D:\study\programming\builds\ESKIN_ACC_RATE_%MODE%"
set "ELF=%BUILD%\ESKIN_STM32_SCLK33_EXPERIMENT.elf"
set "NM=D:\study\programming\ArmGnuToolchain\bin\arm-none-eabi-nm.exe"
set "PROBE_UID=LU_2022_8888"
for /f %%I in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
set "RESULT=%ROOT%\docs\test_results\%STAMP%_acc_rate_%MODE%.json"

echo [ACC rate] Mode: %MODE%  Profile: %PROFILE%
echo [1/4] Configuring isolated benchmark...
cmake --fresh -S "%SOURCE%" -B "%BUILD%" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DSCLK33_PROFILE=%PROFILE% ^
  -DCMAKE_TOOLCHAIN_FILE="%TOOLCHAIN%"
if errorlevel 1 exit /b 1

echo [2/4] Building isolated benchmark...
cmake --build "%BUILD%" -j 4
if errorlevel 1 exit /b 1

echo [3/4] Flashing STM32 through DAPLink at 10 kHz...
pyocd flash -W -u %PROBE_UID% -t stm32g474cetx -f 10k -M under-reset ^
  -O reset_type=hw -e sector "%ELF%"
if errorlevel 1 exit /b 1
pyocd reset -W -u %PROBE_UID% -t stm32g474cetx -f 10k -M under-reset -m hw
if errorlevel 1 exit /b 1

echo [4/4] Waiting for and reading the one-second SRAM snapshot...
powershell.exe -NoProfile -Command "Start-Sleep -Seconds 4"
D:\app\python\python.exe "%ROOT%\research\scan-rate\tools\read_acc_rate_snapshot.py" ^
  --elf "%ELF%" --nm "%NM%" --probe %PROBE_UID% --wait-seconds 8 ^
  --output "%RESULT%"
if errorlevel 1 exit /b 1

echo [STATE] STM32 remains on the isolated ACC benchmark image.
echo [ROLLBACK] Restore the previous combined experiment with:
echo   "%~dp0..\flash_combined_sclk33_experiment.cmd" COM9 refint7p5 all I_ACCEPT_OUT_OF_SPEC_10MHZ
exit /b 0

:invalid_mode
echo ERROR: Unknown ACC benchmark mode "%MODE%".
echo Valid modes: hr1344, lp5376
exit /b 2
