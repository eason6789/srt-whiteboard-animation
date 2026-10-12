#!/usr/bin/env python3
"""生成项目脚手架：config.json + 目录结构。

用法：
    python scripts/make_project.py --name my-video --dir <父目录> --text-file story.txt
    python scripts/make_project.py --name my-video --dir . --text "第一句。第二句。第三句。"
    python scripts/make_project.py --name my-video --dir . --srt story.srt

分句规则（重要，决定配音与字幕的对应）：
- 纯文本按中文标点切分：。！？；…  → 每句一幕
- 保留原文一字不增删；字幕直接用原句
- 若某句要独立成字幕但读音需换气，用 "speak" 字段覆盖（仅影响 TTS，不影响字幕）
"""
import argparse
import json
import re
from pathlib import Path

SPLIT = re.compile(r'(?<=[。！？；…])')


def from_text(t: str):
    parts = [p.strip() for p in SPLIT.split(t) if p.strip()]
    return [{"id": i + 1, "text": p} for i, p in enumerate(parts)]


def from_srt(p: Path):
    """从 SRT 提取字幕文本（按序号去重、去掉时间轴行）。"""
    txt = p.read_text(encoding="utf-8", errors="ignore")
    out = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        if lines[0].isdigit() or "-->" in lines[0]:
            lines = lines[1:]
        content = "".join(l for l in lines if "-->" not in l)
        if content.strip():
            out.append({"id": len(out) + 1, "text": content.strip()})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="项目名（英文，建议 kebab-case）")
    ap.add_argument("--dir", default=".", help="父目录")
    ap.add_argument("--text", default="", help="直接给文字")
    ap.add_argument("--text-file", default="", help="文字文件（UTF-8）")
    ap.add_argument("--srt", default="", help="SRT 文件")
    ap.add_argument("--rate", type=float, default=4.25, help="目标语速 字/秒")
    ap.add_argument("--bgm", default="", help="BGM 音频路径（相对项目目录，可选）")
    ap.add_argument("--bgm-db", type=float, default=-22.0)
    ap.add_argument("--voice", default="", help="TTS 音色ID")
    args = ap.parse_args()

    root = Path(args.dir).resolve() / args.name
    scenes_dir = root / "assets/whiteboard" / args.name
    scenes_dir.mkdir(parents=True, exist_ok=True)
    (root / "audio/bgm").mkdir(parents=True, exist_ok=True)

    if args.text:
        scenes = from_text(args.text)
    elif args.text_file:
        scenes = from_text(Path(args.text_file).read_text(encoding="utf-8"))
    elif args.srt:
        scenes = from_srt(Path(args.srt))
    else:
        raise SystemExit("需要 --text / --text-file / --srt 之一")

    if not scenes:
        raise SystemExit("没能从输入里解析出句子")

    cfg = {
        "name": args.name,
        "rate": args.rate,
        "lead": 0.30,
        "gap": 0.35,
        "bg": "#F5EBD7",
        "ink": "#3C3A38",
        "bgm_db": args.bgm_db,
        "voice_gain": 1.6,
        "font": "PingFang SC",
        "font_ratio": 0.050,
        "margin_ratio": 0.16,
        "base_y_ratio": 0.90,
        "line_h_ratio": 0.072,
        "voice": args.voice or "zh_male_taocheng_uranus_bigtts",
        "bgm": args.bgm,
        "scenes": scenes,
    }
    p = root / "config.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # 同时写一份纯文本，方便核对字幕与原文
    (root / "original.txt").write_text(
        "\n".join(s["text"] for s in scenes), encoding="utf-8")

    print(f"项目已创建：{root}")
    print(f"  config.json    {len(scenes)} 幕")
    print(f"  original.txt   字幕原文（逐字校验基准）")
    print(f"  线稿目录       {scenes_dir}")
    print(f"\n下一步：按 SKILL.md 生成 {len(scenes)} 张线稿 + 标注 JSON，然后")
    print(f"  python scripts/build_audio.py --project {root} plan")


if __name__ == "__main__":
    main()
