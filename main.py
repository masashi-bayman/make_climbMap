"""登山マップ作成アプリの起動スクリプト。

使い方:
    python main.py            # GUIを起動してからGPXを開く
    python main.py 山行.gpx   # 起動と同時にGPXを読み込む
"""

from climbmap.app import main

if __name__ == "__main__":
    main()
