@echo off
rem Opens the NanoAurora client. The first run sets up its own Python environment.
setlocal
set "VENV=%LOCALAPPDATA%\NanoAurora\client-venv"
if exist "%VENV%\Scripts\pythonw.exe" goto :run

echo Setting up the NanoAurora client. This happens once and takes a minute...
py -3 -m venv "%VENV%" 2>nul || python -m venv "%VENV%" || goto :fail
"%VENV%\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check "flet[desktop]==1.0.1" "websockets>=13" || goto :fail
rem The first launch downloads Flet's window runtime; run it here so the progress shows.
"%VENV%\Scripts\python.exe" "%~dp0src\main.py"
exit /b 0

:run
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0src\main.py"
exit /b 0

:fail
echo.
echo Setup failed. The client needs Python 3.10 or newer: https://www.python.org/downloads/
pause
exit /b 1
