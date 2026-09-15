@echo off
setlocal EnableExtensions

if "%~1"=="" (set "PROFILE=safe2p5") else (set "PROFILE=%~1")
if "%~3"=="" (set "FSR_HZ=0") else (set "FSR_HZ=%~3")
if "%~4"=="" (set "ACC_HZ=0") else (set "ACC_HZ=%~4")

if /I "%PROFILE%"=="safe2p5" goto profile_safe2p5
if /I "%PROFILE%"=="legacy10_settle100" goto profile_legacy10_settle100
if /I "%PROFILE%"=="legacy10" goto profile_legacy10
if /I "%PROFILE%"=="legacy10_refint" goto profile_legacy10_refint
if /I "%PROFILE%"=="refint5" goto profile_refint5
if /I "%PROFILE%"=="refint7p5" goto profile_refint7p5
if /I "%PROFILE%"=="refint9p375" goto profile_refint9p375
if /I "%PROFILE%"=="refint8p75" goto profile_refint8p75
if /I "%PROFILE%"=="refint8p125" goto profile_refint8p125
if /I "%PROFILE%"=="refint8" goto profile_refint8
if /I "%PROFILE%"=="refint6p25" goto profile_refint6p25
if /I "%PROFILE%"=="refint5p625" goto profile_refint5p625
if /I "%PROFILE%"=="refint4p8125" goto profile_refint4p8125
if /I "%PROFILE%"=="refint4p75" goto profile_refint4p75
if /I "%PROFILE%"=="refint4p5" goto profile_refint4p5
if /I "%PROFILE%"=="refint4" goto profile_refint4
if /I "%PROFILE%"=="refint2p5" goto profile_refint2p5

echo ERROR: Unknown SCLK33 profile "%PROFILE%".
echo Valid profiles: safe2p5, legacy10_settle100, legacy10, legacy10_refint,
echo                 refint9p375, refint8p75, refint8p125, refint8, refint7p5,
echo                 refint6p25, refint5p625, refint5,
echo                 refint4p8125, refint4p75, refint4p5, refint4, refint2p5
exit /b 2

:profile_safe2p5
set "PROFILE=safe2p5"
goto profile_ok

:profile_legacy10_settle100
set "PROFILE=legacy10_settle100"
goto profile_ok

:profile_legacy10
set "PROFILE=legacy10"
goto profile_ok

:profile_legacy10_refint
set "PROFILE=legacy10_refint"
goto profile_ok

:profile_refint5
set "PROFILE=refint5"
goto profile_ok

:profile_refint7p5
set "PROFILE=refint7p5"
goto profile_ok

:profile_refint9p375
set "PROFILE=refint9p375"
goto profile_ok

:profile_refint8p75
set "PROFILE=refint8p75"
goto profile_ok

:profile_refint8p125
set "PROFILE=refint8p125"
goto profile_ok

:profile_refint8
set "PROFILE=refint8"
goto profile_ok

:profile_refint6p25
set "PROFILE=refint6p25"
goto profile_ok

:profile_refint5p625
set "PROFILE=refint5p625"
goto profile_ok

:profile_refint4p8125
set "PROFILE=refint4p8125"
goto profile_ok

:profile_refint4p75
set "PROFILE=refint4p75"
goto profile_ok

:profile_refint4p5
set "PROFILE=refint4p5"
goto profile_ok

:profile_refint4
set "PROFILE=refint4"
goto profile_ok

:profile_refint2p5
set "PROFILE=refint2p5"
goto profile_ok

:profile_ok
if /I "%PROFILE%"=="safe2p5" goto profile_authorized
if /I "%~2"=="I_ACCEPT_OUT_OF_SPEC_10MHZ" goto profile_authorized

echo ERROR: %PROFILE% is an experimental SCLK-conversion profile.
echo ERROR: Some profiles exceed the MAX11633 4.8 MHz documented limit.
echo To run it deliberately, add: I_ACCEPT_OUT_OF_SPEC_10MHZ
exit /b 3

:profile_authorized
set "PATH=D:\study\programming\ArmGnuToolchain\bin;D:\study\programming\Ninja;D:\study\programming\CMake\bin;%PATH%"
set "ROOT=%~dp0..\..\.."
set "SOURCE=%ROOT%\research\scan-rate\stm32\combined-system-sclk33"
set "TOOLCHAIN=%ROOT%\active\four-module-full-scan\stm32\combined-system\cmake\gcc-arm-none-eabi.cmake"
set "BUILD=D:\study\programming\builds\ESKIN_COMBINED_SCLK33_%PROFILE%"
set "PROBE_UID=LU_2022_8888"

echo [SCLK33 experiment] Profile: %PROFILE%
echo [SCLK33 experiment] FSR target: %FSR_HZ% Hz  ACC target: %ACC_HZ% Hz
if /I "%PROFILE%"=="legacy10" (
  echo WARNING: legacy10 uses 10 MHz ADC SCLK and zero explicit MUX delay.
  echo WARNING: This reproduces the old timing but exceeds the ADC specification.
)
if /I "%PROFILE%"=="legacy10_refint" (
  echo WARNING: legacy10_refint exactly reproduces the original 0x78 setup,
  echo WARNING: 10 MHz ADC SCLK, and zero explicit MUX delay.
)
if /I "%PROFILE%"=="legacy10_settle100" (
  echo WARNING: legacy10_settle100 uses 10 MHz ADC SCLK and exceeds the ADC specification.
)

echo [1/3] Configuring isolated STM32 experiment build...
cmake --fresh -S "%SOURCE%" -B "%BUILD%" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DSCLK33_PROFILE=%PROFILE% ^
  -DSCLK33_FSR_HZ=%FSR_HZ% ^
  -DSCLK33_ACC_HZ=%ACC_HZ% ^
  -DCMAKE_TOOLCHAIN_FILE="%TOOLCHAIN%"
if errorlevel 1 exit /b 1

echo [2/3] Building isolated STM32 experiment...
cmake --build "%BUILD%" -j 4
if errorlevel 1 exit /b 1

echo [3/3] Flashing STM32 SCLK33 experiment through DAPLink at 10 kHz...
pyocd flash -W -u %PROBE_UID% -t stm32g474cetx -f 10k -M under-reset ^
  -O reset_type=hw -e sector "%BUILD%\ESKIN_STM32_SCLK33_EXPERIMENT.elf"
if errorlevel 1 exit /b 1
pyocd reset -W -u %PROBE_UID% -t stm32g474cetx -f 10k -M under-reset -m hw
exit /b %errorlevel%
