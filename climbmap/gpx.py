"""GPXファイルの解析。

軌跡（トラックポイント）と地名ウェイポイントを読み込み、
各スポットへの到着時刻（JST）を軌跡から推定する。

ヤマレコで地名を付与したGPXは、地名が <wpt> タグ、または
トラックポイントの name として入っているため、両方を拾う。
"""

from dataclasses import dataclass, field
import re

import gpxpy
import pandas as pd
import pytz

JST = pytz.timezone("Asia/Tokyo")

# 座標がこの距離（度）未満のスポットは同一とみなす（往復時の重複除去）
DUPLICATE_THRESHOLD_DEG = 0.0001


@dataclass
class Waypoint:
    """地名スポット（GPX上のウェイポイント）"""

    name: str
    lat: float          # GPX上の実際の座標（到着時刻の算出に使用済み）
    lon: float
    arrival_time: str = ""  # 'YYYY-MM-DD HH:MM:SS' (JST)
    visible: bool = True    # 地図に表示するか（GUIの一覧で切り替え）
    # マーカーをドラッグで動かしたときの表示用座標（回転前の座標系）。
    # Noneなら実際の座標に描画する。
    moved_lat: float | None = None
    moved_lon: float | None = None

    @property
    def plot_lat(self) -> float:
        """描画に使う緯度（移動していれば移動後）"""
        return self.lat if self.moved_lat is None else self.moved_lat

    @property
    def plot_lon(self) -> float:
        """描画に使う経度（移動していれば移動後）"""
        return self.lon if self.moved_lon is None else self.moved_lon

    @property
    def is_moved(self) -> bool:
        return self.moved_lat is not None or self.moved_lon is not None

    def reset_position(self):
        """マーカー位置をGPX上の実際の座標に戻す"""
        self.moved_lat = None
        self.moved_lon = None


@dataclass
class GpxData:
    """解析済みGPXデータ"""

    track: pd.DataFrame  # columns: latitude, longitude, elevation, time, time_jst_str
    waypoints: list[Waypoint] = field(default_factory=list)


def _clean_spot_name(name: str) -> str:
    """スポット名から [かな] などの角括弧部分を除去する"""
    return re.sub(r"\s*\[.*?\]", "", name).strip()


def _merge_duplicates_first(waypoints: list[Waypoint],
                            threshold: float = DUPLICATE_THRESHOLD_DEG) -> list[Waypoint]:
    """座標が近いスポットは最初の一つだけ残す（往復ルートで行きのみ採用）"""
    uniq: list[Waypoint] = []
    for wp in waypoints:
        is_dup = any(
            ((wp.lat - u.lat) ** 2 + (wp.lon - u.lon) ** 2) ** 0.5 < threshold
            for u in uniq
        )
        if not is_dup:
            uniq.append(wp)
    return uniq


def parse_gpx(gpx_path: str) -> GpxData:
    """GPXファイルを解析して軌跡とウェイポイント（到着時刻付き）を返す。

    Raises:
        ValueError: 軌跡ポイントが1つも含まれない場合
    """
    with open(gpx_path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append({
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                    "elevation": point.elevation,
                    "time": point.time,
                })

    if not points:
        raise ValueError("GPXに軌跡ポイントが含まれていません")

    df = pd.DataFrame(points)

    if df["time"].notna().any():
        df["time_jst"] = pd.to_datetime(df["time"]).dt.tz_convert(JST)
        df["time_jst_str"] = df["time_jst"].dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        df["time_jst_str"] = ""

    waypoints: list[Waypoint] = []

    # <wpt> タグ（ヤマレコの地名付与はここに入る）
    for wpt in gpx.waypoints:
        if wpt.name:
            waypoints.append(Waypoint(
                name=_clean_spot_name(wpt.name),
                lat=wpt.latitude,
                lon=wpt.longitude,
            ))

    # トラックポイント内の name 属性
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                if getattr(point, "name", None):
                    waypoints.append(Waypoint(
                        name=_clean_spot_name(point.name),
                        lat=point.latitude,
                        lon=point.longitude,
                    ))

    waypoints = _merge_duplicates_first(waypoints)

    # 各スポットの到着時刻 = 軌跡上で最も近いポイントの時刻
    for wp in waypoints:
        dist = ((df["latitude"] - wp.lat) ** 2 +
                (df["longitude"] - wp.lon) ** 2).pow(0.5)
        wp.arrival_time = df.loc[dist.idxmin(), "time_jst_str"]

    return GpxData(track=df, waypoints=waypoints)


def format_waypoint_times(waypoints: list[Waypoint]) -> str:
    """スポット到着時刻の一覧テキスト（動画説明欄などへのコピペ用）。

    非表示にしたスポットは含めない。
    """
    lines = []
    n = 0
    for wp in waypoints:
        if not wp.visible:
            continue
        n += 1
        time_str = wp.arrival_time[-8:] if wp.arrival_time else "--:--:--"
        lines.append(f"{n}. {wp.name}：{time_str}")
    return "\n".join(lines)
