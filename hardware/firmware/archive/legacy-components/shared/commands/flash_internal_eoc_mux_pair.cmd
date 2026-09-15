@echo off
setlocal EnableExtensions

if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")
if "%~2"=="" (set "MODULE=1") else (set "MODULE=%~2")
if "%~3"=="" (set "MUX_US=100") else (set "MUX_US=%~3")

call "%~dp0flash_internal_eoc_mux_stm32.cmd" "%MUX_US%"
if errorlevel 1 exit /b 1
call "%~dp0upload_internal_fifo_dma_bridge.cmd" "%PORT%" "%MODULE%"
if errorlevel 1 exit /b 1

echo Stable internal-clock + EOC pair is running on Module %MODULE%.
echo MUX settle: %MUX_US% us.
echo Restore the stable pair with:
echo   "%~dp0flash_combined_pair.cmd" "%PORT%"
exit /b 0
