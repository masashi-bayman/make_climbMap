@echo off
rem Start the app: run.bat [GPX file]
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo venv not found. Please run setup.bat first.
    pause
    exit /b 1
)

.venv\Scripts\python main.py %*
