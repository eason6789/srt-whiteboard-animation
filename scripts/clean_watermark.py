#!/usr/bin/env python3
"""清除生成图右下角的 "AI生成" 水印。

水印固定在右下角，且该角落本来就是空白纸面，所以做法是：
1) 找到该角落的边界（默认画布 90% 之后的矩形块）；
2) 用附近的干净纸色实心回填；
3) 若实心色与原纸色仍有轻微色差，再做一次轻微羽化过渡。
不改画布尺寸、不动画面主体。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def paper_near(img: Image.Image, x: int, y: int, r: int = 15) -> tuple:
    """取 (x,y) 邻域内出现最多的颜色作为纸色。"""
    box = (max(0, x - r), max(0, y - r),
           min(img.width, x + r), min(img.height, y + r))
    arr = np.array(img.convert("RGB").crop(box)).reshape(-1, 3)
    colors, counts = np.unique(arr, axis=0, return_counts=True)
    return tuple(int(v) for v in colors[counts.argmax()])


def clean(path: Path, fx: float = 0.895, fy: float = 0.895) -> None:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    a = np.array(img).astype(float)

    x0, y0 = int(w * fx), int(h * fy)
    # 参考点取角落左上方的干净纸面
    fill = np.array(paper_near(img, x0 - 80, y0 - 80), dtype=float)

    block = a[y0:, x0:]
    # 角落本来就是空白纸面，直接整块实心回填最干净；
    # 只在左/上边缘留一小段羽化带，避免与原纸色产生可见直边。
    band = 18
    wgt = np.zeros(block.shape[:2], dtype=float)
    wgt[:, :] = 1.0
    gx = np.linspace(0, 1, block.shape[1])[None, :]
    gy = np.linspace(0, 1, block.shape[0])[:, None]
    edge = np.clip(np.minimum(gx * block.shape[1] / band,
                               gy * block.shape[0] / band), 0, 1)
    wgt = wgt * edge  # 左/上边缘渐入，其余为1（完全覆盖）
    wgt = wgt[..., None]
    a[y0:, x0:] = block * (1 - wgt) + fill[None, None, :] * wgt

    Image.fromarray(a.clip(0, 255).astype(np.uint8)).save(path)
    print(f"[ok] {path.name}  {w}x{h}  回填块 x>={x0} y>={y0}  纸色={tuple(int(v) for v in fill)}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        clean(Path(p))
