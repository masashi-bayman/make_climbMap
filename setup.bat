@echo off
rem First-time setup: create venv and install dependencies
cd /d "%~dp0"

if not exist .venv (
    echo Creating venv...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: failed to create venv. Please check that Python is installed.
        pause
        exit /b 1
    )
)

echo Installing dependencies...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo Setup complete! Run run.bat to start the app.
pause
