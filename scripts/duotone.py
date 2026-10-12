#!/usr/bin/env python3
"""把线稿统一成"墨线 → 暖米黄纸"的双色调，彻底消除残留杂色。

为什么不用简单去色：出图给的暖米黄纸底本身就有色度，一刀切去色会把纸底
变成灰色，违反 skill 的"暖米黄旧纸 #F5EBD7、禁止纯白/禁止灰底"要求。

做法：以当前图的亮度为唯一依据，做一条从墨色到纸色的 ramp：
    暗部 -> 墨色 #3C3A38（替代纯黑，避免死黑）
    亮部 -> 纸色 #F5EBD7
所有像素只依赖亮度，因此任何残留的橙/蓝/红都会被拉回这条暖色轴上，
12 张图的色调也自动统一。gamma 用于提亮中间调，保持画面轻盈。
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image

INK = np.array([0x3C, 0x3A, 0x38], dtype=np.float64)   # 墨线
PAPER = np.array([0xF5, 0xEB, 0xD7], dtype=np.float64)  # 暖米黄纸


def duotone(path: Path, gamma: float = 0.92, black: float = 0.10, white: float = 0.97) -> None:
    img = Image.open(path).convert("RGB")
    a = np.array(img).astype(np.float64) / 255.0

    # 亮度 = Rec.709
    lum = a @ np.array([0.2126, 0.7152, 0.0722])

    # 归一化到 [black, white] 区间，gamma 调整中间调
    t = np.clip((lum - black) / max(white - black, 1e-6), 0, 1) ** gamma

    out = INK[None, None, :] + (PAPER - INK)[None, None, :] * t[..., None]
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(path)
    print(f"[ok] {path.name}  双色调 gamma={gamma} 范围=[{black},{white}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--gamma", type=float, default=0.92)
    ap.add_argument("--black", type=float, default=0.10)
    ap.add_argument("--white", type=float, default=0.97)
    args = ap.parse_args()
    for f in args.files:
        duotone(Path(f), args.gamma, args.black, args.white)
