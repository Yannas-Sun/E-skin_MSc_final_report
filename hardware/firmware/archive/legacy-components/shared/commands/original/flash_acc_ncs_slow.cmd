@echo off
setlocal
set "ROOT=%~dp0..\..\.."
set "SCRIPT=%ROOT%\diagnostics\acc\stm32\acc-ncs-slow\flash_acc_ncs_slow.ps1"
if "%~1"=="" (set "ACC=3") else (set "ACC=%~1")
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Acc "%ACC%"
exit /b %errorlevel%
