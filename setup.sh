#!/usr/bin/env bash
# 初回セットアップ: venvを作成して依存パッケージをインストールする
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "venvを作成しています..."
    python3 -m venv .venv
fi

echo "依存パッケージをインストールしています..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo
echo "セットアップ完了！ ./run.sh でアプリを起動できます。"
