@echo off
rem アプリ起動: run.bat [GPXファイル]
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo venvが見つかりません。先に setup.bat を実行してください。
    pause
    exit /b 1
)

.venv\Scripts\python main.py %*
