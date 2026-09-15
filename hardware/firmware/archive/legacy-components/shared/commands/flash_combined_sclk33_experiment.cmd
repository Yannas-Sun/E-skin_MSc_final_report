@echo off
setlocal EnableExtensions
set "ROOT=%~dp0..\.."
if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")
if "%~2"=="" (set "PROFILE=safe2p5") else (set "PROFILE=%~2")
if "%~3"=="" (set "VIEW=all") else (set "VIEW=%~3")
if "%~5"=="" (set "FSR_HZ=0") else (set "FSR_HZ=%~5")
if "%~6"=="" (set "ACC_HZ=0") else (set "ACC_HZ=%~6")

echo ============================================================
echo SCLK33 scan reproduction - isolated experiment
echo Port: %PORT%   Profile: %PROFILE%   GUI: %VIEW%
echo FSR update target: %FSR_HZ% Hz   ACC update target: %ACC_HZ% Hz
echo Stable command flash_combined_pair.cmd is not modified.
echo ============================================================

echo [STM32] Building and flashing the isolated SCLK33 experiment...
call "%~dp0original\flash_combined_sclk33_experiment.cmd" "%PROFILE%" "%~4" "%FSR_HZ%" "%ACC_HZ%"
if errorlevel 1 goto stm32_stage_failed

echo [Teensy] Building and uploading the existing combined USB bridge...
call "%~dp0upload_teensy_sketch.cmd" ^
  "%ROOT%\diagnostics\single-module-combined\teensy\ESKIN_COMBINED_BRIDGE" ^
  "%PORT%" "TEENSY_COMBINED_BRIDGE_SCLK33_EXPERIMENT"
if errorlevel 1 goto post_flash_failed

echo [GUI] Waiting for the Teensy USB serial port to reconnect...
timeout /t 2 /nobreak >nul
echo [GUI] Opening the combined monitor on %PORT%...
call "%~dp0original\start_combined_monitor.cmd" "%PORT%" "%VIEW%"
if errorlevel 1 goto post_flash_failed

echo.
echo [STATE] STM32 remains on SCLK33 experiment profile %PROFILE%.
echo [ROLLBACK] Restore normal firmware with:
echo   "%~dp0flash_combined_pair.cmd" "%PORT%"
exit /b 0

:stm32_stage_failed
set "FAILED_CODE=%ERRORLEVEL%"
if "%FAILED_CODE%"=="2" exit /b %FAILED_CODE%
if "%FAILED_CODE%"=="3" exit /b %FAILED_CODE%
echo.
echo [STATE] STM32 experiment flash did not complete; its state may be partial.
echo [ROLLBACK] Restore normal firmware with:
echo   "%~dp0flash_combined_pair.cmd" "%PORT%"
exit /b %FAILED_CODE%

:post_flash_failed
set "FAILED_CODE=%ERRORLEVEL%"
echo.
echo [STATE] STM32 is still running SCLK33 experiment profile %PROFILE%.
echo [ROLLBACK] Restore normal firmware with:
echo   "%~dp0flash_combined_pair.cmd" "%PORT%"
exit /b %FAILED_CODE%
