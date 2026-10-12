#!/usr/bin/env python3
"""分析线稿图，把画面切成若干"主体块"并输出像素级 bbox，供标注使用。

思路：线稿 = 浅纸底 + 深墨线。先按纸色亮度阈值二值化出墨迹，
再做形态学闭运算把断裂线条连成块，用连通域取 bbox，
最后按面积过滤 + 合并邻近块，输出候选主体区域。
坐标一律是原图像素整数，供 annotation.json 直接使用。
"""
import argparse
from pathlib import Path

import cv2
import numpy as np


def analyze(path: Path, dark_thr: int = 200, min_area: int = 2500, dilate: int = 9) -> list:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"无法读取 {path}")
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    ink = (gray < dark_thr).astype(np.uint8)
    # 闭运算把同一主体的断裂线条连起来
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate, dilate))
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, k)
    # 再膨胀一次，容忍主体内部的空白（如窗格、衣服褶皱）
    closed = cv2.dilate(closed, k, iterations=1)

    n, lab, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area:
            continue
        boxes.append({
            "x": int(x), "y": int(y), "w": int(bw), "h": int(bh),
            "area": int(area),
            "cx": int(x + bw / 2), "cy": int(y + bh / 2),
        })

    # 丢掉被大块包含的小块（大框内的碎块通常是同一个主体的内部结构）
    boxes.sort(key=lambda b: -b["area"])
    keep = []
    for b in boxes:
        contained = False
        for kp in keep:
            if (b["x"] >= kp["x"] - 4 and b["y"] >= kp["y"] - 4
                    and b["x"] + b["w"] <= kp["x"] + kp["w"] + 4
                    and b["y"] + b["h"] <= kp["y"] + kp["h"] + 4):
                contained = True
                break
        if not contained:
            keep.append(b)
    keep.sort(key=lambda b: (b["y"], b["x"]))
    return keep, (w, h)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--dark", type=int, default=200)
    ap.add_argument("--area", type=int, default=2500)
    ap.add_argument("--dilate", type=int, default=9)
    args = ap.parse_args()

    for f in args.files:
        p = Path(f)
        boxes, (w, h) = analyze(p, args.dark, args.area, args.dilate)
        print(f"\n=== {p.name}  canvas={w}x{h}  块数={len(boxes)}")
        for i, b in enumerate(boxes, 1):
            print(f"  [{i}] x={b['x']:4d} y={b['y']:4d} w={b['w']:4d} h={b['h']:4d}"
                  f"  area={b['area']:7d}  中心=({b['cx']},{b['cy']})")


if __name__ == "__main__":
    main()
