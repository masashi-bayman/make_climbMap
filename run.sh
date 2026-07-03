#!/usr/bin/env bash
# アプリ起動: ./run.sh [GPXファイル]
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "venvが見つかりません。先に ./setup.sh を実行してください。"
    exit 1
fi

exec .venv/bin/python main.py "$@"
