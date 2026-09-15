@echo off
setlocal
set "ROOT=%~dp0..\..\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\diagnostics\acc\stm32\acc-sck-slow\flash_acc_sck_slow.ps1"
exit /b %errorlevel%
