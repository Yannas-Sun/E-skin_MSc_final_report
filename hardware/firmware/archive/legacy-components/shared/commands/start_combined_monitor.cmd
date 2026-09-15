@echo off
call "%~dp0original\start_combined_monitor.cmd" %*
exit /b %errorlevel%
