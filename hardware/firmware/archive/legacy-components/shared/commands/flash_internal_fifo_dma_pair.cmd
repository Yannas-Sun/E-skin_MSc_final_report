@echo off
setlocal EnableExtensions

if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")
if "%~2"=="" (set "MODULE=1") else (set "MODULE=%~2")
if "%~3"=="" (set "GAP_US=37") else (set "GAP_US=%~3")
if "%~4"=="" (set "MUX_US=0") else (set "MUX_US=%~4")

call "%~dp0flash_internal_fifo_dma_stm32.cmd" "%GAP_US%" "%MUX_US%"
if errorlevel 1 exit /b 1
call "%~dp0upload_internal_fifo_dma_bridge.cmd" "%PORT%" "%MODULE%"
if errorlevel 1 exit /b 1

echo Internal-clock FIFO-DMA pair is running on Module %MODULE%.
echo Restore the stable pair with:
echo   "%~dp0flash_combined_pair.cmd" "%PORT%"
exit /b 0
