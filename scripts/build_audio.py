#!/usr/bin/env python3
"""白板动画配音流水线：一句配置 + 一段文字 → 出成品。

用法：
    python build_audio.py --project <项目目录> plan        # 只看时间轴，不合成
    python build_audio.py --project <项目目录> tts         # 合成语音
    python build_audio.py --project <项目目录> assemble# 摆放+变速校正
    python build_audio.py --project <项目目录> mix         # 混音+ 烧字幕 + 出成片
    python build_audio.py --project <项目目录> all         # tts→assemble→mix 一气呵成
    python build_audio.py --project <项目目录> verify      # 量化校验（不合成）

项目目录下需有 config.json（见 make_project.py 生成）：
    {
      "name": "my-video",
      "scenes": [ {"id": 1, "image": "scene-01-xxx.png", "text": "第一句"}, ... ],
      "rate": 4.25,
      "bgm": "audio/bgm/source.mp3"     // 可选
    }

设计要点（都是实战踩过的坑）：
-语速锁定，用字数反推幕时长；不先定时长再塞文字
- 严格按幕窗口对齐：缺幕/越幕/重叠一律报错退出，绝不产出坏成片
- TTS 缓存用"内容哈希"作文件名，改句子不会编号错位
- atempo 按每句实测语速校正（>1 加快，<1 放慢，别写反）
- 一次性 filter_complex 叠加，不用"逐句补静音再concat"（会累加成 N×片长）
- 混音用 numpy 逐样本相加，绕开 ffmpeg amix 的自动增益陷阱
- 字幕文本 = 用户原文，逐字校验；长句按像素折行不丢字
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid as uuidlib
import wave
from pathlib import Path

import numpy as np

# ══════════════════ 配置加载 ══════════════════


class Project:
    def __init__(self, root: Path):
        self.root = root
        cfg_path = root / "config.json"
        if not cfg_path.exists():
            raise SystemExit(f"找不到 {cfg_path}，先运行 make_project.py 生成")
        self.cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.name = self.cfg.get("name", root.name)
        self.rate = float(self.cfg.get("rate", 4.25))
        self.lead = float(self.cfg.get("lead", 0.30))
        self.gap = float(self.cfg.get("gap", 0.35))
        self.bgm_db = float(self.cfg.get("bgm_db", -22.0))
        self.voice_gain = float(self.cfg.get("voice_gain", 1.6))
        self.bg = self.cfg.get("bg", "#F5EBD7")
        self.ink = self.cfg.get("ink", "#3C3A38")
        self.font_ratio = float(self.cfg.get("font_ratio", 0.050))
        self.margin_ratio = float(self.cfg.get("margin_ratio", 0.16))
        self.base_y_ratio = float(self.cfg.get("base_y_ratio", 0.90))
        self.line_h_ratio = float(self.cfg.get("line_h_ratio", 0.072))
        self.scenes = self.cfg["scenes"]
        self.audio = root / "audio"
        self.voice = self.audio / "voice"
        self.audio.mkdir(parents=True, exist_ok=True)
        self.voice.mkdir(parents=True, exist_ok=True)
        self._scene_files = self._map_scenes()

    def _map_scenes(self):
        """幕号 → 标注 json 路径。

        查找顺序：① config 里显式给的 image 名→ ② 按 scene-NN-*.annotation.json 模糊匹配
        无论走哪条都必须在目录里唯一命中，命中 0 个直接报错（曾因漏判导致后续全部错位）。
        """
        sdir = self.root / "assets/whiteboard" / self.name
        out = {}
        for s in self.scenes:
            sid = int(s["id"])
            img = s.get("image") or ""
            cand = None
            if img:
                base = Path(img).with_suffix("").name
                c = sdir / f"{base}.annotation.json"
                if c.exists():
                    cand = c
            if cand is None:
                g = sorted(sdir.glob(f"scene-{sid:02d}-*.annotation.json"))
                # 允许 scene-1-*.json 这种非补零写法
                if not g:
                    g = sorted(sdir.glob(f"scene-{sid}-*.annotation.json"))
                cand = g[0] if len(g) >= 1 else None
            if cand is None or not cand.exists():
                raise SystemExit(
                    f"scene{sid} 找不到标注文件。请确认已生成标注 JSON。\n"
                    f"  查找位置：{sdir}/scene-{sid:02d}-*.annotation.json"
                )
            out[sid] = cand
        return out

    def scene_durations(self):
        d = {}
        for sid, p in self._scene_files.items():
            j = json.loads(p.read_text(encoding="utf-8"))
            d[sid] = j["sceneDurationMs"] / 1000.0
        return d


def ffmpeg(*args, check=True):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    subprocess.run(cmd, check=check)


def ffprobe_duration(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ══════════════════ TTS ══════════════════

VOLC_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
VOLC_RESOURCE = "seed-tts-2.0"


def volc_tts(text: str, out: Path, voice: str, api_key: str):
    """豆包语音合成 2.0（HTTP Chunked）。

    三个必须同时满足的条件，否则会报 403/55000000：
      1. X-Api-Resource-Id: seed-tts-2.0（连字符，不是 volc.seedtts.v2）
      2. body 用 req_params 结构 + user.namespace="BidirectionalTTS"
      3. 响应是 chunked 多行 JSON，每行 code=0 带 base64 音频
    """
    import requests

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": VOLC_RESOURCE,
        "X-Api-Request-Id": str(uuidlib.uuid4()),
        "X-Control-Require-Usage-Tokens-Return": "*",
        "Content-Type": "application/json",
    }
    payload = {
        "user": {"uid": "wb", "namespace": "BidirectionalTTS"},
        "req_params": {
            "speaker": voice,
            "text": text,
            "audio_params": {"format": "mp3", "sample_rate": 44100},
            "additions": json.dumps({"explicit_language": "zh"}, ensure_ascii=False),
        },
        "request": {"reqid": str(uuidlib.uuid4()), "text": text, "operation": "submit"},
    }
    audio = b""
    with requests.post(VOLC_ENDPOINT, headers=headers, json=payload,
                        timeout=120, stream=True) as r:
        if r.status_code != 200:
            raise SystemExit(f"HTTP {r.status_code}：{r.text[:300]}")
        for line in r.iter_lines():
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("data"):
                audio += base64.b64decode(d["data"])
            code = d.get("code")
            if code == 20000000:
                break
            if code not in (0, None):
                raise SystemExit(f"合成错误 code={code} {d.get('message','')}")
    if len(audio) < 800:
        raise SystemExit(f"返回音频过短（{len(audio)}B）")
    out.write_bytes(audio)


def tts_all(pj: Project, engine: str, voice: str, api_key: str, force=False):
    units = pj.cfg["scenes"]
    if engine == "doubao":
        if not api_key:
            raise SystemExit(
                "未提供 API Key。用 --api-key 或环境变量 VOLC_API_KEY。\n"
                "（火山引擎控制台 → 开通「语音合成2.0」→ API Key 管理 → 新建）"
            )
        for s in units:
            say = s.get("speak") or s["text"]
            # 用内容哈希做文件名：改句子不会编号错位
            h = hashlib.md5(say.encode("utf-8")).hexdigest()[:10]
            out = pj.voice / f"{int(s['id']):02d}-{h}.mp3"
            if out.exists() and not force:
                print(f"  [skip] {out.name}")
                continue
            print(f"  [tts ] scene{s['id']} {say[:22]}…")
            volc_tts(say, out, voice, api_key)
    elif engine == "none":
        print("  engine=none，跳过合成（请自行把音频放入 "
              f"{pj.voice}/NN-<hash>.mp3）")
        return
    else:
        raise SystemExit(f"未知 engine: {engine}")
    print("  语音合成完成")


# ══════════════════ 时间轴 ══════════════════

def build_timeline(pj: Project):
    durs = pj.scene_durations()
    order = sorted(durs)
    scenes = {int(s["id"]): s for s in pj.scenes}

    # 缺句检查：漏一幕会导致后续全部错位，必须硬失败
    missing = [s for s in order if s not in scenes]
    if missing:
        raise SystemExit(f"config.json 里缺这些幕的文本：{missing}")

    total = sum(durs[s] for s in order)
    units, cursor = [], 0.0
    for sid in order:
        sc = scenes[sid]
        text = sc["text"]
        say = sc.get("speak") or text
        n = len(re.sub(r"\s", "", say))
        speech = n / pj.rate
        avail = durs[sid] - pj.lead - pj.gap
        if speech > avail:
            print(f"  ! scene{sid} 需 {speech:.2f}s 超出可用 {avail:.2f}s，已压缩"
                  f"（建议调大该幕 sceneDurationMs）")
            speech = avail
        units.append({
            "index": len(units) + 1,
            "scene": sid,
            "text": text,          # 字幕/原文
            "speak": say,          # TTS 文本（可含换气标点）
            "chars": n,
            "startSec": round(cursor + pj.lead, 3),
            "durationSec": round(speech, 3),
            "endSec": round(cursor + pj.lead + speech, 3),
            "sceneStartSec": round(cursor, 3),
            "sceneEndSec": round(cursor + durs[sid], 3),
            "restSec": round(durs[sid] - pj.lead - speech, 3),
        })
        cursor += durs[sid]

    # 硬校验：不重叠、不越幕、起点偏移一致
    errs = []
    for i, u in enumerate(units):
        if u["endSec"] > u["sceneEndSec"] + 1e-6:
            errs.append(f"#{u['index']} 越出本幕 {u['endSec']:.2f}>{u['sceneEndSec']:.2f}")
        if i > 0 and u["startSec"] < units[i - 1]["endSec"] - 1e-6:
            errs.append(f"#{u['index']} 与上一句重叠")
    if errs:
        print("校验失败：")
        for e in errs:
            print("  !", e)
        raise SystemExit(1)

    tl = {
        "name": pj.name, "rate": pj.rate, "leadSec": pj.lead, "gapSec": pj.gap,
        "totalSec": round(total, 2), "units": units,
    }
    (pj.audio / "voiceover_timeline.json").write_text(
        json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    return tl


def show_plan(pj: Project, tl):
    print(f"\n语速 {tl['rate']} 字/秒  画面总长 {tl['totalSec']}s  "
          f"{len(tl['units'])} 句\n")
    print(f"{'#':<4}{'幕':<6}{'字':>4}{'幕窗':>16}{'语音':>16}{'读完后留白':>11}  文本")
    for u in tl["units"]:
        print(f"{u['index']:<4}s{u['scene']:<5}{u['chars']:>4}"
              f"{u['sceneStartSec']:>7.2f}-{u['sceneEndSec']:<7.2f}"
              f"{u['startSec']:>7.2f}-{u['endSec']:<7.2f}{u['restSec']:>10.2f}s"
              f"  {u['text'][:18]}")
    print("\n✓ 无重叠、无越幕")


# ══════════════════ 拼接（filter_complex 一次性叠加） ══════════════════

def assemble(pj: Project, tl):
    """摆放语音 + atempo 实测校正。

    关键：不用"逐句补静音再concat"——那样 N 句会累加成 N×片长（曾出917s）。
    改用 filter_complex：每句只经 adelay 偏移，全部输入一次性 amix。
    """
    files = []
    for u in tl["units"]:
        say = u["speak"]
        h = hashlib.md5(say.encode("utf-8")).hexdigest()[:10]
        src = next(iter(sorted(pj.voice.glob(f"{u['scene']:02d}-{h}.mp3"))), None)
        if src is None:
            cands = sorted(pj.voice.glob(f"{u['scene']:02d}-*.mp3"))
            if not cands:
                raise SystemExit(f"scene{u['scene']} 没有语音文件")
            src = cands[0]
        files.append((u, src))
    if len(files) != len(tl["units"]):
        raise SystemExit("语音文件数与时间轴不匹配")

    tmp = pj.audio / "_parts"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    labels, wavs = [], []
    for u, src in files:
        act = ffprobe_duration(src)
        if act <= 0:
            raise SystemExit(f"{src.name} 时长为0")
        actual = u["chars"] / act
        tempo = max(0.5, min(2.0, pj.rate / actual))   # <1 放慢
        w = tmp / f"{u['index']:02d}.wav"
        ffmpeg("-i", str(src), "-af",
               f"atempo={tempo:.4f},aresample=44100", "-ar", "44100", "-ac", "2", str(w))
        spk = act / tempo
        print(f"  {u['scene']:>2} tempo={tempo:.3f}  {act:.2f}s→{spk:.2f}s  "
              f"语速 {actual:.2f}→{u['chars']/spk:.2f} 字/秒  起 {u['startSec']:.2f}s")
        wavs.append(w)

    chains, labs = [], []
    for i, u in enumerate(tl["units"]):
        ms = int(u["startSec"] * 1000)
        chains.append(f"[{i}:a]adelay={ms}|{ms}[v{i}]")
        labs.append(f"[v{i}]")
    total = tl["totalSec"]
    fc = (";".join(chains) + ";" + "".join(labs)
          + f"amix=inputs={len(labs)}:duration=longest:normalize=0[m];"
          + f"[m]apad,atrim=0:{total},asetpts=N/SR/TB[out]")
    out = pj.audio / "voiceover.wav"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for w in wavs:
        cmd += ["-i", str(w)]
    cmd += ["-filter_complex", fc, "-map", "[out]", "-ar", "44100", "-ac", "2", str(out)]
    subprocess.run(cmd, check=True)
    got = ffprobe_duration(out)
    print(f"[ok] {out}  {got:.2f}s（应为 {total:.2f}s）")
    if abs(got - total) > 0.5:
        raise SystemExit("音轨长度与时间轴不符，停止")


# ══════════════════ 混音 ══════════════════

def read_wav(p: Path):
    with wave.open(str(p), "rb") as w:
        n, ch = w.getnframes(), w.getnchannels()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)
    return a.reshape(-1, ch) / 32768.0


def make_bgm(pj: Project, dur: float):
    """把 BGM 源循环/裁剪到目标时长。

    两个坑：
    - ffmpeg -stream_loop 在末尾会截断，改用 numpy 平铺
    - afade 淡出会削掉片尾（混音层救不回来），默认不加淡出
    """
    src = pj.root / pj.cfg.get("bgm", "")
    if not src.exists():
        print(f"  ! 找不到 BGM：{src}，跳过配乐")
        return None
    dst = pj.audio / "bgm_full.wav"
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", "/tmp/_bgm_src.wav"],
                   check=True)
    src_a = read_wav(Path("/tmp/_bgm_src.wav"))
    L = len(src_a)
    if L == 0:
        return None
    need = int(dur * 44100)
    reps = int(np.ceil(need / L))
    big = np.tile(src_a, (reps, 1))[:need]
    st = (big.clip(-1, 1) * 32767).astype(np.int16)
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(src_a.shape[1]); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(st.tobytes())
    return dst


def mix(pj: Project, tl, video: Path):
    vo = pj.audio / "voiceover.wav"
    if not vo.exists():
        raise SystemExit("先跑 assemble")
    dur = ffprobe_duration(video)
    total = float(tl["totalSec"])

    tmp = pj.audio / "_mix"
    tmp.mkdir(exist_ok=True)
    vo_w = tmp / "vo.wav"
    ffmpeg("-i", str(vo), "-af", f"apad,atrim=0:{dur:.3f},asetpts=N/SR/TB",
           "-ar", "44100", "-ac", "2", str(vo_w))

    a = read_wav(vo_w) * pj.voice_gain
    bg_path = pj.cfg.get("bgm")
    if bg_path:
        bg = make_bgm(pj, dur)
    else:
        bg = None

    if bg is None:
        mixd = a
        print("  无BGM，仅旁白")
    else:
        bg_w = tmp / "bg.wav"
        ffmpeg("-i", str(bg), "-ar", "44100", "-ac", "2", str(bg_w))
        b = read_wav(bg_w) * (10 ** (pj.bgm_db / 20.0))
        n = min(len(a), len(b))
        mixd = a[:n] + b[:n]
        if len(mixd) < len(a):
            mixd = np.vstack([mixd, np.zeros((len(a) - len(mixd), a.shape[1]), np.float32)])
        if len(mixd) < len(b):
            mixd = np.vstack([mixd, np.zeros((len(b) - len(mixd), b.shape[1]), np.float32)])

    peak = np.abs(mixd).max()
    if peak > 0.99:
        mixd = np.tanh(mixd * 1.05) * 0.95
        print(f"  峰值 {20*np.log10(peak):.1f}dB → 已软限幅")
    st = (mixd.clip(-1, 1) * 32767).astype(np.int16)
    out = pj.audio / "mixed.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(st.tobytes())
    print(f"[ok] {out}  {len(st)/2/44100:.2f}s")

    norm = pj.audio / "mixed-norm.wav"
    ffmpeg("-i", str(out), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
           "-ar", "44100", "-ac", "2", str(norm))
    final = pj.root / f"{pj.name}-final.mp4"
    ffmpeg("-i", str(video), "-i", str(norm), "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-shortest", str(final))
    print(f"[ok] {final}")
    return final


# ══════════════════ 字幕 ══════════════════

def make_ass(pj: Project, tl):
    def rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))[::-1]  # → BGR

    ink = rgb(pj.ink); paper = rgb(pj.bg)
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: S,{pj.cfg.get('font','PingFang SC')},48,"
        f"&H00{ink[0]:02X}{ink[1]:02X}{ink[2]:02X},&H000000FF,"
        f"&H00{paper[0]:02X}{paper[1]:02X}{paper[2]:02X},&H000000FF,"
        f"0,0,0,0,100,100,1.2,0,1,2,0,2,60,60,52,1\n\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")

    def ts(x):
        h = int(x // 3600); m = int((x % 3600) // 60); s = x % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    lines = [head]
    for u in tl["units"]:
        start = u["startSec"]
        end = min(u["endSec"] + 0.35, u["sceneEndSec"] - 0.15)
        lines.append(f"Dialogue: 0,{ts(start)},{ts(end)},S,,0,0,0,,{u['text']}\n")
    p = pj.audio / f"{pj.name}.ass"
    p.write_text("".join(lines), encoding="utf-8")

    # 逐字校验：字幕拼接必须等于原文
    subs = "".join(u["text"] for u in tl["units"])
    orig = "".join(s["text"] for s in pj.scenes)
    if subs != orig:
        for i, (x, y) in enumerate(zip(subs, orig)):
            if x != y:
                raise SystemExit(f"字幕与原文在第 {i} 字不同：'{x}' vs '{y}'")
        raise SystemExit("字幕与原文长度不同")
    print(f"[ok] {p}（{len(tl['units'])} 条，逐字校验通过）")
    return p


def burn_subtitles(pj: Project, tl, video: Path, audio_src: Path = None):
    """PIL 逐帧渲染字幕。

    为什么不用 ffmpeg 的 ass/drawtext：homebrew 的 ffmpeg 可能未编译
    --enable-libass / --enable-libfreetype，两个滤镜都不可用。
    """
    import av
    from fractions import Fraction
    from PIL import Image, ImageDraw, ImageFont

    ass = pj.audio / f"{pj.name}.ass"
    cues = []
    for line in ass.read_text(encoding="utf-8").splitlines():
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            s, e = parts[1].strip(), parts[2].strip()
            cues.append((s, e, parts[9]))

    def sec(t):
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    cues = [(sec(a), sec(b), t) for a, b, t in cues]

    src = av.open(str(video))
    vs = src.streams.video[0]
    W, H = vs.codec_context.width, vs.codec_context.height
    fps = Fraction(vs.average_rate) if vs.average_rate else Fraction(60, 1)

    ink = tuple(int(pj.ink.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    paper = tuple(int(pj.bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))

    fp = None
    for c in ("/System/Library/Fonts/PingFang.ttc",
              "/System/Library/Fonts/STHeiti Light.ttc",
              "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "C:/Windows/Fonts/msyh.ttc"):
        if Path(c).exists():
            fp = c; break
    font = ImageFont.truetype(fp, int(H * pj.font_ratio)) if fp else ImageFont.load_default()
    MAXW = int(W * (1 - pj.margin_ratio))
    BASE_Y = int(H * pj.base_y_ratio)
    LINE_H = int(H * pj.line_h_ratio)

    def wrap(text):
        if font.getlength(text) <= MAXW:
            return [text]
        lines, cur = [], ""
        for ch in text:
            if font.getlength(cur + ch) > MAXW and cur:
                lines.append(cur); cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        return lines

    plate = {}
    for s, e, text in cues:
        lines = wrap(text)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y0 = BASE_Y - LINE_H * (len(lines) - 1)
        for i, ln in enumerate(lines):
            y = y0 + i * LINE_H
            for dx, dy in [(2,0),(-2,0),(0,2),(0,-2),(2,2),(-2,-2),(2,-2),(-2,2)]:
                d.text((W/2+dx, y+dy), ln, font=font, fill=paper+(240,),
                       anchor="ms", align="center")
            d.text((W/2, y), ln, font=font, fill=ink+(255,), anchor="ms", align="center")
        plate[(s, e)] = img

    tmp = pj.audio / "_subbed.mp4"
    out = av.open(str(tmp), mode="w")
    ov = out.add_stream("libx264", rate=fps)
    ov.width, ov.height, ov.pix_fmt = W, H, "yuv420p"
    ov.options = {"crf": "18", "preset": "medium"}
    idx = 0
    for frame in src.decode(video=0):
        t = float(frame.pts * frame.time_base)
        while idx < len(cues) and t > cues[idx][1]:
            idx += 1
        if idx < len(cues):
            s, e, _ = cues[idx]
            if s <= t < e:
                im = frame.to_image().convert("RGBA")
                im.alpha_composite(plate[(s, e)])
                frame = av.VideoFrame.from_image(im.convert("RGB"))
        for p in ov.encode(frame):
            out.mux(p)
    for p in ov.encode():
        out.mux(p)
    out.close()
    # 音轨来源：优先用混音后的成片（原画面可能完全无声）
    asrc = Path(audio_src) if audio_src else video
    final = pj.root / f"{pj.name}-final-subtitled.mp4"
    has_audio = _has_audio(asrc)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-i", str(asrc),
           "-map", "0:v"]
    if has_audio:
        cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
    else:
        print("  ! 源视频无音轨，输出将不含声音")
        cmd += ["-an"]
    cmd += ["-c:v", "copy", "-shortest", str(final)]
    subprocess.run(cmd, check=True)
    print(f"[ok] {final}")
    return final


def _has_audio(p: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                        "-show_entries", "stream=index", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


# ══════════════════ 校验 ══════════════════

def verify(pj: Project, tl, video: Path):
    print("=" * 58)
    print("量化校验")
    print("=" * 58)
    ok = True

    # 1) 遮罩不变量
    try:
        import av
        from PIL import Image
        n_ok = 0
        for s in pj.scenes:
            sid = int(s["id"])
            ann = pj._scene_files[sid]
            stem = ann.name[:-len(".annotation.json")]
            png = ann.with_name(stem + ".png")
            mp4 = ann.with_name(stem + "-whiteboard.mp4")
            if not (png.exists() and mp4.exists()):
                continue
            c = av.open(str(mp4)); last = None
            for fr in c.decode(video=0):
                last = fr.to_image()
            c.close()
            if last is None:
                continue
            src = Image.open(png).convert("L").resize(last.size)
            import numpy as np
            a = (np.array(src) < 170).mean()
            b = (np.array(last.convert("L")) < 170).mean()
            r = b / max(a, 1e-6)
            flag = "OK" if r > 0.9 else "!!"
            if r <= 0.9:
                ok = False
            print(f"  scene{sid:<3} 结尾覆盖率 {r:.2f}  {flag}")
            n_ok += 1
        print(f"  → {n_ok} 幕检查完毕")
    except Exception as e:
        print(f"  (遮罩检查跳过：{e})")

    # 2) 声画对齐
    durs = pj.scene_durations()
    order = sorted(durs)
    cur = 0
    print("\n  声画对齐：")
    for u in tl["units"]:
        ws = cur; we = cur + durs[u["scene"]]
        off = u["startSec"] - ws
        over = max(0, u["endSec"] - we)
        flag = "OK" if (over < 1e-6 and abs(off - pj.lead) < 0.05) else "!!"
        if flag == "!!":
            ok = False
        print(f"  scene{u['scene']:<3} 幕窗 {ws:6.2f}-{we:6.2f}  "
              f"语音 {u['startSec']:6.2f}-{u['endSec']:6.2f}  "
              f"偏移 {off:+.2f}s  {flag}")
        cur = we

    # 3) 音频电平（ffmpeg volumedetect，勿用 PyAV 算 RMS）
    if video.exists():
        print("\n  音频分段电平：")
        dur = ffprobe_duration(video)
        bad = 0
        t = 0.0
        while t < dur - 2:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-ss", f"{t:.0f}", "-t", "4",
                 "-i", str(video), "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True)
            m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
            db = float(m.group(1)) if m else -99
            flag = "OK" if db > -55 else "!! 疑似静音"
            if db <= -55:
                bad += 1; ok = False
            print(f"  {t:5.0f}s  {db:6.1f} dB  {flag}")
            t += 8
        if bad:
            print(f"  → {bad} 段电平过低")

    print("\n" + ("✓ 全部通过" if ok else "✗ 存在问题，见上面 !! 项"))
    return ok


# ══════════════════ main ══════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="项目目录（含 config.json）")
    ap.add_argument("cmd", choices=["plan", "tts", "assemble", "mix", "all", "verify"])
    ap.add_argument("--engine", default="doubao", choices=["doubao", "none"])
    ap.add_argument("--voice", default=os.environ.get("VOLC_VOICE", "zh_male_taocheng_uranus_bigtts"))
    ap.add_argument("--api-key", default=os.environ.get("VOLC_API_KEY", ""))
    ap.add_argument("--video", default="", help="mix/verify 用；缺省用 {name}-final.mp4")
    ap.add_argument("--force", action="store_true", help="强制重合成")
    a = ap.parse_args()

    pj = Project(Path(a.project).resolve())
    tl = build_timeline(pj)
    if a.cmd == "plan":
        show_plan(pj, tl)
        return

    if a.cmd in ("tts", "all"):
        print("── 合成语音")
        tts_all(pj, a.engine, a.voice, a.api_key, a.force)
        if a.cmd == "tts":
            return

    if a.cmd in ("assemble", "all"):
        print("── 摆放语音")
        assemble(pj, tl)
        if a.cmd == "assemble":
            return

    # 选画面：优先用户指定，否则找项目里已渲染合并的无声画面
    video = Path(a.video) if a.video else None
    if video is None:
        # 优先"合并后"的画面（-merged.mp4 或 任何非 -final 的成片），
        # 不要用 {name}-final.mp4 —— 那是 mix 自己产出的带音轨文件，会自我覆盖。
        cands = [p for p in sorted(pj.root.glob("*.mp4"))
                 if not p.name.endswith(("-final.mp4", "-final-subtitled.mp4"))]
        cands += sorted(pj.root.glob(f"{pj.name}*.mp4"))
        if not cands:
            raise SystemExit(
                f"找不到画面成片。请先渲染各幕并用 merge_scenes.py 合并，"
                f"或用 --video 指定。\n  查找：{pj.root}/*.mp4"
            )
        video = cands[0]
    if not video.exists():
        raise SystemExit(f"画面不存在：{video}")

    if a.cmd == "verify":
        show_plan(pj, tl)
        verify(pj, tl, video)
        return

    print(f"  画面源：{video.name}")
    print("── 混音")
    mixed = mix(pj, tl, video)
    print("── 字幕")
    make_ass(pj, tl)
    print("── 烧录字幕")
    # 必须用"带音轨的混音版"作为音轨来源，否则会丢音频
    final = burn_subtitles(pj, tl, video, audio_src=mixed)
    print("── 校验")
    show_plan(pj, tl)
    # 校验最终成品（带音轨），不是无声的画面源
    verify(pj, tl, final)
    print(f"\n成品：{final}")


if __name__ == "__main__":
    main()
