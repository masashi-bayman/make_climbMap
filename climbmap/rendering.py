"""地図の描画（matplotlib Figure の生成）"""

import math
from dataclasses import dataclass, field

import matplotlib.patches as patches
import matplotlib.patheffects as path_effects
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
    top_margin: float = 2.5     # 初期表示の余白（軌跡の高さ/幅に対する倍率）
    bottom_margin: float = 2.5
    left_margin: float = 1.0
    right_margin: float = 1.0
    arrow: Arrow | None = None
    # 表示範囲 (x_min, x_max, y_min, y_max)。None なら余白から自動計算。
    # GUIのドラッグ移動・ホイール拡縮で調整した範囲を再描画後も維持するために使う。
    view: tuple[float, float, float, float] | None = None
    show_compass: bool = False  # 方位記号（N）を左下に表示するか


@dataclass
class LabelItem:
    """描画済みの地名ラベル（ドラッグ調整用に artist を保持）"""

    index: int            # data.waypoints 内でのインデックス
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
               label_positions: dict[int, tuple[float, float]] | None = None) -> MapRender:
    """GPXデータから地図Figureを生成する。

    Args:
        data: 解析済みGPXデータ（visible=False のスポットは描画しない）
        settings: 回転角・マージン・矢印の設定
        font: 日本語フォント名（Noneならmatplotlibデフォルト）
        label_positions: ラベル位置の上書き {waypointインデックス: (x, y)}。
            ドラッグで調整した位置を再描画後も維持するために使う。
    """
    label_positions = label_positions or {}

    # 軌跡全体のバウンディングボックス中心で回転
    xs_rot, ys_rot, center = rotate_points(
        data.track["longitude"], data.track["latitude"], settings.angle_deg
    )

    # 表示対象のウェイポイントを同じ中心で回転（元のインデックスを保持）
    wp_rotated = []
    for idx, wp in enumerate(data.waypoints):
        if not wp.visible:
            continue
        wxs, wys, _ = rotate_points([wp.lon], [wp.lat],
                                    settings.angle_deg, center=center)
        wp_rotated.append((idx, wp, wxs[0], wys[0]))

    min_x, max_x = min(xs_rot), max(xs_rot)
    min_y, max_y = min(ys_rot), max(ys_rot)
    x_range = max_x - min_x
    y_range = max_y - min_y

    pad_x = x_range * 0.3
    pad_y = y_range * 0.3

    if settings.view is not None:
        x_min_display, x_max_display, y_min_display, y_max_display = settings.view
    else:
        x_min_display = min_x - pad_x * settings.left_margin
        x_max_display = max_x + pad_x * settings.right_margin
        y_min_display = min_y - pad_y * settings.bottom_margin
        y_max_display = max_y + pad_y * settings.top_margin

    fig = Figure(figsize=FIGSIZE, dpi=DPI)
    ax = fig.add_subplot(111)

    # 半透明の背景（動画に重ねたとき軌跡が見やすいように）。
    # Axes座標系で描くことで、ドラッグ移動・拡縮後も常に画面全体を覆う。
    background = patches.Rectangle(
        (0, 0), 1, 1, transform=ax.transAxes,
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
    x_order = sorted(range(len(wp_rotated)), key=lambda i: wp_rotated[i][2])
    band_rank = {i: rank for rank, i in enumerate(x_order)}

    font_kwargs = {"fontname": font} if font else {}

    labels: list[LabelItem] = []
    for i, (idx, wp, x, y) in enumerate(wp_rotated):
        # スポットのマーカー（丸）
        ax.scatter(x, y, s=200, marker="o",
                   c="deepskyblue", edgecolor="navy", zorder=3)

        default_y = label_band_top - (band_rank[i] % 2) * label_band_step
        label_x, label_y = label_positions.get(idx, (x, default_y))

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
            index=idx, name=wp.name, text=text, line=line,
            anchor_x=x, anchor_y=y, arrival_time=wp.arrival_time,
        ))

    if settings.arrow is not None:
        _draw_arrow(ax, settings.arrow, x_range, y_range)

    if settings.show_compass:
        _draw_compass(ax, settings.angle_deg)

    ax.set_aspect("equal")
    ax.set_axis_off()
    fig.tight_layout()

    return MapRender(figure=fig, ax=ax, labels=labels)


def _draw_compass(ax, angle_deg: float):
    """地図左下に方位記号（N矢印）を描く。

    地図をangle_deg回転させて描いているため、北の向きも同じだけ回る。
    位置はAxes座標系（左下固定）、矢印の長さはポイント単位なので、
    ドラッグ移動・拡縮の影響を受けない。
    """
    t = math.radians(angle_deg)
    # 元の座標系の北 (0, 1) を回転した方向
    dx, dy = -math.sin(t), math.cos(t)
    anchor = (0.08, 0.06)  # Axes座標（左下からの割合）
    length = 26            # ポイント

    ax.annotate(
        "", xy=anchor, xycoords="axes fraction",
        xytext=(-length * dx, -length * dy), textcoords="offset points",
        arrowprops=dict(arrowstyle="-|>", color="white",
                        linewidth=2.5, mutation_scale=18),
        zorder=7, annotation_clip=False,
    )
    n_text = ax.annotate(
        "N", xy=anchor, xycoords="axes fraction",
        xytext=(13 * dx, 13 * dy), textcoords="offset points",
        color="white", fontsize=13, fontweight="bold",
        ha="center", va="center", zorder=7, annotation_clip=False,
    )
    n_text.set_path_effects(
        [path_effects.withStroke(linewidth=3, foreground="black")])


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
