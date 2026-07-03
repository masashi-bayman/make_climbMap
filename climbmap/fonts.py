"""日本語フォントの自動検出（Windows / macOS / Linux 対応）"""

from matplotlib import font_manager

# 優先順にチェックする日本語フォント名
_CANDIDATES = [
    "Yu Gothic",          # Windows 8.1+
    "MS Gothic",          # Windows
    "Meiryo",             # Windows
    "Hiragino Sans",      # macOS
    "Hiragino Kaku Gothic ProN",  # macOS
    "Noto Sans CJK JP",   # Linux
    "Noto Sans JP",
    "IPAexGothic",        # Linux
    "IPAGothic",
    "TakaoGothic",
    "VL Gothic",
]


def find_japanese_font() -> str | None:
    """インストール済みの日本語フォント名を返す。見つからなければ None。"""
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CANDIDATES:
        if name in available:
            return name
    return None


def setup_japanese_font() -> str | None:
    """matplotlibのデフォルトフォントに日本語フォントを設定する。

    Returns:
        設定したフォント名。見つからなければ None（豆腐文字になる可能性あり）。
    """
    import matplotlib
    name = find_japanese_font()
    if name:
        matplotlib.rcParams["font.family"] = name
    return name
