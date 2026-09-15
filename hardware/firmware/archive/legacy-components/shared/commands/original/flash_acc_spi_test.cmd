@echo off
setlocal
set "ROOT=%~dp0..\..\.."
set "SCRIPT=%ROOT%\diagnostics\acc\stm32\acc-spi-array\flash_selected_acc.ps1"
if "%~1"=="" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Acc "%~1"
)
exit /b %errorlevel%
