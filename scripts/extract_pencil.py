#!/usr/bin/env python3
"""从 drawing-hand.png 中分离出"只有铅笔"的素材，去掉写实的手。

思路：
1) 铅笔杆是**极暗的饱和红色**（R-G≈30~55、V<175）；皮肤是高亮低饱和。
   颜色阈值得到多个连通域，其中**只有最大的一块沿对角线是笔杆**，
   其余都是皮肤反光/指甲边缘噪点。用"面积 + 细长度 + 位置"筛出笔杆域。
2) 笔杆被手遮挡了中段。铅笔是刚体直线，故沿主轴把笔杆补成完整直杆，
   末端按锥形收窄成笔尖。
3) 补出来的像素取笔杆实测颜色，并做轻度平滑（去掉原图颗粒噪点）。
4) 最后按线稿双色调着色（墨 #3C3A38 → 纸 #F5EBD7），与场景风格统一。
5) 打印笔尖锚点，供渲染时传 --tip-anchor-x/y。
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

INK = np.array([0x3C, 0x3A, 0x38], dtype=np.float64)
PAPER = np.array([0xF5, 0xEB, 0xD7], dtype=np.float64)


def pick_rod(m: np.ndarray) -> np.ndarray:
    """在多个连通域中挑出"笔杆"：面积大、细长、斜跨画面左上→中部。"""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    best, best_score = None, -1e18
    for i in range(1, n):
        x, y, w, h, area = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                            stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT],
                            stats[i, cv2.CC_STAT_AREA])
        if area < 3000:
            continue
        # 细长度：斜向长条的 bbox 面积/实际面积 比值大；用对角跨度当长度
        diag = float(np.hypot(w, h))
        elong = diag / max(w, 1)
        # 触角：笔杆应从画面左上附近起始
        touches_topleft = 1.0 if (x <= w * 0.25 and y <= h * 0.15) else 0.0
        score = area + 6000 * elong + 9000 * touches_topleft
        if score > best_score:
            best_score, best = score, i
    if best is None:
        raise SystemExit("未找到笔杆连通域")
    return (lab == best).astype(np.uint8)


def extract(src: Path, dst: Path) -> None:
    raw = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise SystemExit(f"无法读取 {src}")
    ys, xs = np.where(raw[:, :, 3] > 128)
    bgr = raw[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()
    sh, sw = bgr.shape[:2]

    sub = bgr.astype(np.int16)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    S, V = hsv[:, :, 1].astype(np.int16), hsv[:, :, 2].astype(np.int16)
    B, G, R = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]

    cand = ((R - G) >= 25) & (V >= 25) & (V <= 170) & (S >= 65) & (R >= 50)
    cand = cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    rod = pick_rod(cand)

    ys2, xs2 = np.where(rod > 0)
    pts = np.stack([xs2, ys2], 1).astype(np.float64)
    mu = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - mu, full_matrices=False)
    axis, perp = vt[0], vt[1]
    if axis[1] < 0:                       # 让轴指向"右上→左下"，即笔尖朝左下
        axis, perp = -axis, -perp
    proj = (pts - mu) @ axis
    perp_d = (pts - mu) @ perp

    # 半宽：用中位数绝对偏差，抗离群（皮肤残留、笔杆边缘）
    half = float(np.median(np.abs(perp_d))) * 1.25
    half = max(5.0, min(half, 22.0))

    p_lo, p_hi = proj.min(), proj.max()
    origin = mu + axis * p_lo
    rod_rgb = np.array([bgr[..., 2][rod > 0].mean(),
                        bgr[..., 1][rod > 0].mean(),
                        bgr[..., 0][rod > 0].mean()], np.float64)
    # 笔尖是一段渐深到尖的锥形
    tip_len = max(18.0, half * 5.0)

    canvas = np.zeros((sh, sw, 3), np.float64)
    fill = np.zeros((sh, sw), np.uint8)
    steps = int(p_hi - p_lo) + 1
    for i in range(steps):
        s = i
        # 宽度：主体恒定，末端 tip_len 内线性收窄为0
        if s > p_hi - p_lo - tip_len:
            w = half * max(0.0, (p_hi - p_lo - s) / tip_len)
        else:
            w = half
        if w < 0.6:
            continue
        c = origin + axis * s
        for t in np.linspace(-w, w, max(2, int(w * 2) + 1)):
            q = c + perp * t
            qx, qy = int(round(q[0])), int(round(q[1]))
            if 0 <= qx < sw and 0 <= qy < sh:
                # 笔尖附近逐渐变暗（像 graphite 芯）
                shade = 1.0 - 0.45 * max(0.0, (s - (p_hi - p_lo - tip_len)) / tip_len)
                canvas[qy, qx] = rod_rgb * shade
                fill[qy, qx] = 255

    # 轻度平滑，去掉原图颗粒
    canvas = cv2.GaussianBlur(canvas, (3, 3), 0)
    alpha_out = cv2.GaussianBlur(fill, (5, 5), 0)

    ys3, xs3 = np.where(alpha_out > 40)
    pad = 14
    ax0, ay0 = max(0, xs3.min() - pad), max(0, ys3.min() - pad)
    ax1 = min(sw, xs3.max() + 1 + pad)
    ay1 = min(sh, ys3.max() + 1 + pad)
    canvas = canvas[ay0:ay1, ax0:ax1]
    alpha_out = alpha_out[ay0:ay1, ax0:ax1]

    # 双色调（保持 BGR）
    lum = canvas @ np.array([0.114, 0.587, 0.299])
    t = np.clip((lum - 20) / 140.0, 0, 1) ** 0.78
    toned = INK[None, None, :] + (PAPER - INK)[None, None, :] * t[..., None]
    rgba = np.dstack([toned, alpha_out.astype(np.float64)])
    Image.fromarray(rgba.clip(0, 255).astype(np.uint8)).save(dst)

    tip = origin + axis * p_hi
    tip_out = ((tip[0] - ax0) / max(1, ax1 - ax0 - 1),
               (tip[1] - ay0) / max(1, ay1 - ay0 - 1))
    tail_out = ((origin[0] - ax0) / max(1, ax1 - ax0 - 1),
                (origin[1] - ay0) / max(1, ay1 - ay0 - 1))
    print(f"[ok] {dst.name}  尺寸 {ax1-ax0}x{ay1-ay0}  半宽 {half:.1f}px")
    print(f"    笔尾 anchor ({tail_out[0]:.3f}, {tail_out[1]:.3f})")
    print(f"    ★ 笔尖 tip_anchor_x = {tip_out[0]:.4f}")
    print(f"    ★ 笔尖 tip_anchor_y = {tip_out[1]:.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    a = ap.parse_args()
    extract(Path(a.src), Path(a.dst))
