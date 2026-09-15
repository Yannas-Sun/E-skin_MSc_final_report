@echo off
call "%~dp0original\flash_combined.cmd" %*
exit /b %errorlevel%
