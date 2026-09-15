@echo off
call "%~dp0original\flash_stm32_project.cmd" %*
exit /b %errorlevel%
