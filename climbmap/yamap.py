"""YAMAPのチェックポイント一覧からウェイポイントを作る。

YAMAPの活動日記にあるチェックポイント（コースタイム）欄をコピーして
貼り付けたテキストを解析し、各スポットの通過時刻を取り出す。
その時刻でGPXの軌跡を検索して座標を決めるため、
ヤマレコで地名を付与しなくても地名入りの地図が作れる。

貼り付けテキストの例::

    11:47
    28
    12:15
    23
    滝
    落ヶ滝
    ›
    12:38
    12:39
    17
    滝
    落ヶ滝
    ›

`›` がスポットの区切り。1ブロックの中身は
「時刻（到着）／時刻（出発）／数値／カテゴリ／スポット名」の並びで、
数値や出発時刻は無い場合もある。
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .gpx import JST, Waypoint

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
NUM_RE = re.compile(r"^[\d.,]+$")
# スポット名の後ろに付くリンク矢印（ブロックの区切り）
ARROW_CHARS = {"›", "〉", ">", "＞", "»", "→"}

# 軌跡の時刻とこれ以上離れている場合は警告する（分）
DEFAULT_MAX_GAP_MINUTES = 30


@dataclass
class Checkpoint:
    """貼り付けテキストから読み取ったチェックポイント"""

    name: str
    time: str = ""       # "HH:MM"（読み取れなければ空）
    category: str = ""   # 山頂 / 滝 / 登山口 など


def _split_blocks(text: str) -> list[list[str]]:
    """テキストを矢印で区切ってブロックに分ける"""
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line in ARROW_CHARS:
            blocks.append(current)
            current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _normalize_time(text: str) -> str:
    m = TIME_RE.match(text)
    hour, minute = int(m.group(1)), int(m.group(2))
    return f"{hour:02d}:{minute:02d}"


def parse_checkpoints(text: str) -> list[Checkpoint]:
    """貼り付けテキストからチェックポイントの一覧を取り出す"""
    checkpoints: list[Checkpoint] = []

    for block in _split_blocks(text):
        times: list[tuple[int, str]] = []   # (行番号, "HH:MM")
        num_positions: list[int] = []
        texts: list[str] = []

        for i, line in enumerate(block):
            if TIME_RE.match(line):
                times.append((i, _normalize_time(line)))
            elif NUM_RE.match(line):
                num_positions.append(i)
            else:
                texts.append(line)

        if not texts:
            # 名前が無いブロック（山行の開始・終了時刻など）は読み飛ばす
            continue

        # 2つの時刻の間に数値（所要時間）が挟まる場合、
        # 前の時刻は「ひとつ前の地点を出発した時刻」なので取り除く
        if len(times) >= 2:
            if any(times[0][0] < pos < times[1][0] for pos in num_positions):
                times = times[1:]

        checkpoints.append(Checkpoint(
            name=texts[-1],                      # 最後のテキストがスポット名
            time=times[0][1] if times else "",   # 残った先頭が到着時刻
            category=texts[-2] if len(texts) >= 2 else "",
        ))

    return checkpoints


def build_waypoints(data, checkpoints: list[Checkpoint],
                    max_gap_minutes: float = DEFAULT_MAX_GAP_MINUTES
                    ) -> tuple[list[Waypoint], list[str]]:
    """チェックポイントの時刻でGPXの軌跡を検索し、ウェイポイントを作る。

    Args:
        data: 解析済みGPXデータ（時刻付きの軌跡が必要）
        checkpoints: 貼り付けテキストから読み取ったチェックポイント
        max_gap_minutes: 軌跡の時刻とこれ以上離れていたら警告する分数

    Returns:
        (作成したウェイポイント, 警告メッセージの一覧)

    Raises:
        ValueError: 軌跡に時刻が入っていない場合
    """
    df = data.track
    if "time_jst" not in df.columns or df["time_jst"].isna().all():
        raise ValueError(
            "GPXの軌跡に時刻が入っていないため、時刻からスポットを作成できません")

    track_times = df["time_jst"]
    base_date = track_times.iloc[0].date()

    waypoints: list[Waypoint] = []
    warnings: list[str] = []
    previous = None

    for cp in checkpoints:
        if not cp.time:
            warnings.append(f"「{cp.name}」は時刻が読み取れなかったため作成しません")
            continue

        hour, minute = (int(v) for v in cp.time.split(":"))
        moment = JST.localize(datetime(
            base_date.year, base_date.month, base_date.day, hour, minute))
        # 前のスポットより前の時刻になる場合は日をまたいだとみなす（泊まりの山行）
        while previous is not None and moment < previous:
            moment += timedelta(days=1)
        previous = moment

        gaps = (track_times - moment).abs()
        idx = gaps.idxmin()
        gap_minutes = gaps.loc[idx].total_seconds() / 60

        if gap_minutes > max_gap_minutes:
            warnings.append(
                f"「{cp.name}」({cp.time}) は軌跡の時刻から"
                f"{gap_minutes:.0f}分離れています")

        waypoints.append(Waypoint(
            name=cp.name,
            lat=df.loc[idx, "latitude"],
            lon=df.loc[idx, "longitude"],
            arrival_time=moment.strftime("%Y-%m-%d %H:%M:%S"),
        ))

    return waypoints, warnings
