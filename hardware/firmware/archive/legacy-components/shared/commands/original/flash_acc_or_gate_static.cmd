@echo off
setlocal
set "ROOT=%~dp0..\..\.."
set "SCRIPT=%ROOT%\diagnostics\acc\stm32\acc-or-gate-static\flash_or_gate_static.ps1"
if "%~1"=="" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
) else if "%~2"=="" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Acc "%~1" -Mosi 1
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Acc "%~1" -Mosi "%~2"
)
exit /b %errorlevel%
