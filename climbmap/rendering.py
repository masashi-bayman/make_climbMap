"""地図の描画（matplotlib Figure の生成）"""

import math
from dataclasses import dataclass, field

import matplotlib.patches as patches
from matplotlib.figure import Figure

from .geometry import rotate_points
from .gpx import GpxData

# YouTube縦動画の右側配置用: 720x1280px相当（6 x 10.67インチ, dpi=120）
FIGSIZE = (6, 10.67)
DPI = 120


@dataclass
class Arrow:
    """手動配置の方向矢印（プロット座標系）"""

    x: float
    y: float
    angle_deg: float = 0.0


@dataclass
class RenderSettings:
    """描画パラメータ"""

    angle_deg: float = 0.0      # 軌跡全体の回転角（度、反時計回り）
    top_margin: float = 2.5     # 各マージンは軌跡の高さ/幅に対する倍率
    bottom_margin: float = 2.5
    left_margin: float = 1.0
    right_margin: float = 1.0
    arrow: Arrow | None = None


@dataclass
class LabelItem:
    """描画済みの地名ラベル（ドラッグ調整用に artist を保持）"""

    name: str
    text: object          # matplotlib.text.Text
    line: object          # matplotlib.lines.Line2D（マーカーとラベルを結ぶ線）
    anchor_x: float       # マーカー位置（プロット座標）
    anchor_y: float
    arrival_time: str


@dataclass
class MapRender:
    """描画結果"""

    figure: Figure
    ax: object
    labels: list[LabelItem] = field(default_factory=list)


def render_map(data: GpxData,
               settings: RenderSettings,
               font: str | None = None,
               label_positions: dict[str, tuple[float, float]] | None = None) -> MapRender:
    """GPXデータから地図Figureを生成する。

    Args:
        data: 解析済みGPXデータ
        settings: 回転角・マージン・矢印の設定
        font: 日本語フォント名（Noneならmatplotlibデフォルト）
        label_positions: ラベル位置の上書き {地名: (x, y)}。
            ドラッグで調整した位置を再描画後も維持するために使う。
    """
    label_positions = label_positions or {}

    # 軌跡全体のバウンディングボックス中心で回転
    xs_rot, ys_rot, center = rotate_points(
        data.track["longitude"], data.track["latitude"], settings.angle_deg
    )

    # ウェイポイントも同じ中心で回転
    wp_rotated = []
    for wp in data.waypoints:
        wxs, wys, _ = rotate_points([wp.lon], [wp.lat],
                                    settings.angle_deg, center=center)
        wp_rotated.append((wp, wxs[0], wys[0]))

    min_x, max_x = min(xs_rot), max(xs_rot)
    min_y, max_y = min(ys_rot), max(ys_rot)
    x_range = max_x - min_x
    y_range = max_y - min_y

    pad_x = x_range * 0.3
    pad_y = y_range * 0.3

    x_min_display = min_x - pad_x * settings.left_margin
    x_max_display = max_x + pad_x * settings.right_margin
    y_min_display = min_y - pad_y * settings.bottom_margin
    y_max_display = max_y + pad_y * settings.top_margin

    fig = Figure(figsize=FIGSIZE, dpi=DPI)
    ax = fig.add_subplot(111)

    # 半透明の背景（動画に重ねたとき軌跡が見やすいように）
    background = patches.Rectangle(
        (x_min_display, y_min_display),
        x_max_display - x_min_display,
        y_max_display - y_min_display,
        linewidth=0, facecolor="dimgray", alpha=0.70, zorder=0,
    )
    ax.add_patch(background)

    # 軌跡
    ax.plot(xs_rot, ys_rot, color="white", linewidth=3, zorder=2)

    ax.set_xlim(x_min_display, x_max_display)
    ax.set_ylim(y_min_display, y_max_display)

    # ラベルのデフォルト位置は上余白のバンド。
    # 重なりを減らすため、X座標順で高い段・低い段に交互配置する。
    label_band_top = max_y + pad_y * (settings.top_margin - 0.5)
    label_band_step = pad_y * 0.7
    x_order = sorted(range(len(wp_rotated)), key=lambda i: wp_rotated[i][1])
    band_rank = {idx: rank for rank, idx in enumerate(x_order)}

    font_kwargs = {"fontname": font} if font else {}

    labels: list[LabelItem] = []
    for i, (wp, x, y) in enumerate(wp_rotated):
        # スポットのマーカー（丸）
        ax.scatter(x, y, s=200, marker="o",
                   c="deepskyblue", edgecolor="navy", zorder=3)

        default_y = label_band_top - (band_rank[i] % 2) * label_band_step
        label_x, label_y = label_positions.get(wp.name, (x, default_y))

        line = ax.plot([x, label_x], [y, label_y],
                       color="orange", linewidth=1, linestyle="--",
                       zorder=3.5)[0]

        text = ax.text(
            label_x, label_y, wp.name,
            color="orange", fontsize=14, fontweight="bold",
            ha="center", va="bottom", zorder=4,
            bbox=dict(facecolor="black", alpha=0.6, boxstyle="round,pad=0.3"),
            **font_kwargs,
        )

        labels.append(LabelItem(
            name=wp.name, text=text, line=line,
            anchor_x=x, anchor_y=y, arrival_time=wp.arrival_time,
        ))

    if settings.arrow is not None:
        _draw_arrow(ax, settings.arrow, x_range, y_range)

    ax.set_aspect("equal")
    ax.set_axis_off()
    fig.tight_layout()

    return MapRender(figure=fig, ax=ax, labels=labels)


def _draw_arrow(ax, arrow: Arrow, x_range: float, y_range: float):
    """進行方向などを示す手動矢印を描画する"""
    length = (x_range + y_range) * 0.02
    dx = length * math.cos(math.radians(arrow.angle_deg))
    dy = length * math.sin(math.radians(arrow.angle_deg))

    # 矢印の先端（白い三角形）
    head = patches.RegularPolygon(
        (arrow.x + dx * 0.7, arrow.y + dy * 0.7),
        3, radius=length * 0.4,
        orientation=math.radians(arrow.angle_deg + 30),
        facecolor="white", edgecolor="white", linewidth=2, zorder=6,
    )
    ax.add_patch(head)

    # 矢印の尾（線）
    ax.plot([arrow.x, arrow.x + dx * 0.6],
            [arrow.y, arrow.y + dy * 0.6],
            color="white", linewidth=3, zorder=5)


def save_png(render: MapRender, path: str):
    """透過PNGとして保存する（動画編集ソフトでの重ね合わせ用）"""
    render.figure.savefig(path, dpi=DPI, bbox_inches="tight", transparent=True)
