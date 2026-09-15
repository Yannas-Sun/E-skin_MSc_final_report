@echo off
setlocal EnableExtensions

if "%~1"=="" (set "PROBE_UID=LU_2022_8888") else (set "PROBE_UID=%~1")
if "%~2"=="" (set "SWD_SPEED=1M") else (set "SWD_SPEED=%~2")

echo Erasing the complete STM32 flash on probe %PROBE_UID% at %SWD_SPEED%...
pyocd erase -W -u %PROBE_UID% -t stm32g474cetx -f %SWD_SPEED% -M under-reset --mass
if errorlevel 1 (
  echo STM32 erase failed. Retry with 100k or 10k, and check SWDIO, SWCLK, GND and VTref.
  endlocal
  exit /b 1
)

echo Complete STM32 flash erase finished.
endlocal
exit /b 0
