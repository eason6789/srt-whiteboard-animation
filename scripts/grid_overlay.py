#!/usr/bin/env python3
"""给线稿叠加 0.0~1.0 的归一化坐标网格，用于精确校准annotation 的 region。

用法：python grid_overlay.py <图片> <输出>
读图时可直接读出主体所在的网格位置，换算成像素写入标注。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GRID = 20# 每格 5% = 0.05


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    img = Image.open(src).convert("RGB")
    w, h = img.size
    ov = img.copy()
    d = ImageDraw.Draw(ov)

    # CJK 字体
    fp = ""
    for c in ("/System/Library/Fonts/PingFang.ttc",
              "/System/Library/Fonts/STHeiti Light.ttc",
              "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "C:/Windows/Fonts/msyh.ttc"):
        if Path(c).exists():
            fp = c
            break
    font = ImageFont.truetype(fp, 20) if fp else ImageFont.load_default()

    for i in range(GRID + 1):
        p = i / GRID
        x, y = int(p * w), int(p * h)
        major = i % 5 == 0
        col = (220, 40, 40) if major else (90, 140, 200)
        d.line([(x, 0), (x, h)], fill=col, width=2 if major else 1)
        d.line([(0, y), (w, y)], fill=col, width=2 if major else 1)
        if major:
            d.text((x + 4, 4), f"{p:.2f}", fill=(200, 20, 20), font=font,
                   stroke_width=3, stroke_fill=(255, 255, 255))
            d.text((4, y + 4), f"{p:.2f}", fill=(200, 20, 20), font=font,
                   stroke_width=3, stroke_fill=(255, 255, 255))

    ov.save(out)
    print(f"[ok] {out.name}  {w}x{h}  网格每格 0.05")


if __name__ == "__main__":
    main()
