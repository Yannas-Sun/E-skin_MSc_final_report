@echo off
setlocal
set "ROOT=%~dp0..\.."
if "%~1"=="" (set "PORT=COM9") else (set "PORT=%~1")
for %%I in ("%ROOT%\..\..\..") do set "PROJECT_ROOT=%%~fI"
set "GUI=%PROJECT_ROOT%\docs\Final\data scalability\script\four-module-fsr-monitor.py"
if not exist "%GUI%" (
  echo ERROR: data scalability GUI not found:
  echo "%GUI%"
  exit /b 2
)
python -u "%GUI%" --port "%PORT%"
exit /b %errorlevel%
