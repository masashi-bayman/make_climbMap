@echo off
rem 初回セットアップ: venvを作成して依存パッケージをインストールする
cd /d "%~dp0"

if not exist .venv (
    echo venvを作成しています...
    python -m venv .venv
    if errorlevel 1 (
        echo エラー: venvの作成に失敗しました。Pythonがインストールされているか確認してください。
        pause
        exit /b 1
    )
)

echo 依存パッケージをインストールしています...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
    echo エラー: パッケージのインストールに失敗しました。
    pause
    exit /b 1
)

echo.
echo セットアップ完了！ run.bat でアプリを起動できます。
pause
