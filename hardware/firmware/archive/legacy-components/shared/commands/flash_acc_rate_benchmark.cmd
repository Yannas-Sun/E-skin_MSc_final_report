@echo off
setlocal EnableExtensions
call "%~dp0original\flash_acc_rate_benchmark.cmd" "%~1"
exit /b %errorlevel%
