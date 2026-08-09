"""アプリ設定の保存・読み込み。

ユーザーごとの設定（外部サイトのリンク先など）を
ホームディレクトリの ~/.climbmap/settings.json に保存する。
"""

import json
import os

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".climbmap")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

# リンクの初期値はトップページ。ログイン済みならマイページ相当に飛ぶ。
# 自分の活動日記のURLなどに差し替えられる。
DEFAULTS = {
    "yamap_url": "https://yamap.com/",
    "yamareco_url": "https://www.yamareco.com/",
}


def load_settings() -> dict:
    """設定を読み込む。ファイルが無い・壊れている場合は初期値を返す。"""
    settings = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            settings.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, json.JSONDecodeError):
        pass
    return settings


def save_settings(settings: dict):
    """設定を保存する。失敗しても例外は投げない（保存先が書けない環境向け）。"""
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
