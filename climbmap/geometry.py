"""座標回転ユーティリティ"""

import math


def rotate_points(xs, ys, angle_deg, center=None):
    """点列を指定角度（度・反時計回り）で回転する。

    Args:
        xs, ys: 座標のイテラブル
        angle_deg: 回転角（度、反時計回り）
        center: 回転中心 (cx, cy)。None の場合は点列のバウンディングボックス中心。

    Returns:
        (xs_rotated, ys_rotated, (cx, cy))
    """
    xs = list(xs)
    ys = list(ys)

    if center is None:
        cx = (max(xs) + min(xs)) / 2
        cy = (max(ys) + min(ys)) / 2
    else:
        cx, cy = center

    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    xs2 = []
    ys2 = []
    for x, y in zip(xs, ys):
        dx = x - cx
        dy = y - cy
        xs2.append(dx * cos_a - dy * sin_a + cx)
        ys2.append(dx * sin_a + dy * cos_a + cy)
    return xs2, ys2, (cx, cy)
