#!/usr/bin/env python3
"""按人工给定的相对比例(0~1)生成 12 个 annotation.json，并做像素级校验。

为什么不用自动分块：这批线稿是连贯的全景构图（墙面、窗格、砖缝彼此相连），
形态学连通域会把整幅画合成一块，无法区分"主体"。所以主体位置由人眼读图后
以相对比例给出，这里只负责换算成整数像素、检查越界与重叠、写入 JSON。
"""
import json
from pathlib import Path

from PIL import Image

import sys
# 用法: gen_annotations.py <场景目录> [--gap 0.5]
D = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()

#每幕：场景id、时长(ms)、叙事依据、元素列表
#元素：id/label/role/subtitle/seq/相对矩形/类型
SCENES = [
    dict(
        sid="scene-01", dur=8000,
        story="自娱自乐的年轻人并未在意我的到来；我到厂房旧居的第一眼所见。",
        els=[
            dict(id="factory", label="厂房立面", role="场景铺垫：西安道北老厂房本体，平顶砖墙、砖烟囱、水塔",
                 sub="自娱自乐的年轻人并没有在意我的到来。", seq=1, r=(0.100, 0.085, 0.400, 0.190), t="structure"),
            dict(id="door", label="厂房大门", role="关键建筑：紧闭的大门，强化「家」已不属于我的感觉",
                 sub="自娱自乐的年轻人并没有在意我的到来。", seq=2, r=(0.095, 0.365, 0.100, 0.215), t="structure"),
            dict(id="window", label="厂房钢窗", role="关键建筑：多格钢窗，画面视觉重心",
                 sub="自娱自乐的年轻人并没有在意我的到来。", seq=3, r=(0.250, 0.385, 0.210, 0.150), t="structure"),
            dict(id="plants", label="墙边花盆", role="环境点缀：院落生活痕迹",
                 sub="自娱自乐的年轻人并没有在意我的到来。", seq=4, r=(0.180, 0.665, 0.075, 0.060), t="object"),
            dict(id="tenant", label="低头刷手机的年轻人", role="关键人物：完全沉浸在自己的世界，对我的到来毫无察觉",
                 sub="自娱自乐的年轻人并没有在意我的到来。", seq=5, r=(0.665, 0.465, 0.075, 0.255), t="character"),
        ],
    ),
    dict(
        sid="scene-02", dur=7000,
        story="我从他身后绕过去，想看看现在家里的样子。",
        els=[
            dict(id="factory", label="厂房与院墙", role="场景铺垫：我正走向这栋房子的墙面",
                 sub="我从他身后绕过去，抱着侥幸的心里，想看看现在家里的样子。", seq=1, r=(0.115, 0.115, 0.520, 0.470), t="structure"),
            dict(id="window", label="厂房钢窗", role="关键建筑：我要看的那个窗口",
                 sub="我从他身后绕过去，抱着侥幸的心里，想看看现在家里的样子。", seq=2, r=(0.435, 0.290, 0.145, 0.265), t="structure"),
            dict(id="narrator", label="三十岁的我", role="关键人物：侧身经过，目光朝向窗",
                 sub="我从他身后绕过去，抱着侥幸的心里，想看看现在家里的样子。", seq=3, r=(0.230, 0.595, 0.120, 0.235), t="character"),
            dict(id="tenant", label="仍低头看手机的人", role="陪衬人物：仍在自顾自，衬托我的试探",
                 sub="我从他身后绕过去，抱着侥幸的心里，想看看现在家里的样子。", seq=4, r=(0.440, 0.620, 0.075, 0.215), t="character"),
        ],
    ),
    dict(
        sid="scene-03", dur=7000,
        story="窗户很久没擦，从外面什么也看不清。",
        els=[
            dict(id="watertank", label="屋顶水塔", role="场景标志：老厂房的记忆坐标",
                 sub="但窗户不知多久没擦过了，从外面看什么也看不清。", seq=1, r=(0.300, 0.000, 0.175, 0.165), t="structure"),
            dict(id="window", label="积灰的钢框窗", role="关键物体：布满污渍的玻璃，室内完全不可见",
                 sub="但窗户不知多久没擦过了，从外面看什么也看不清。", seq=2, r=(0.290, 0.155, 0.430, 0.560), t="structure"),
            dict(id="sill", label="窗台", role="环境点缀：积尘的窗沿",
                 sub="但窗户不知多久没擦过了，从外面看什么也看不清。", seq=3, r=(0.285, 0.765, 0.430, 0.070), t="object"),
            dict(id="narrator", label="我的肩与头", role="关键人物：站在窗外凝望",
                 sub="但窗户不知多久没擦过了，从外面看什么也看不清。", seq=4, r=(0.000, 0.440, 0.085, 0.560), t="character"),
        ],
    ),
    dict(
        sid="scene-04", dur=6000,
        story="父亲交代过我可以表明身份，但我最终没有说。",
        els=[
            dict(id="wall", label="砖墙与院门", role="场景铺垫：紧闭的院门，「家」已隔我于门外",
                 sub="出发前父亲交代过我，可以向对方说明我是房主的儿子。", seq=1, r=(0.040, 0.290, 0.430, 0.370), t="structure"),
            dict(id="narrator", label="三十岁的我", role="关键人物：背对镜头，站定未动",
                 sub="出发前父亲交代过我，可以向对方说明我是房主的儿子。", seq=2, r=(0.565, 0.460, 0.130, 0.350), t="character"),
            dict(id="bubble", label="空对话框", role="关键符号：话到嘴边却没有说出口",
                 sub="但我最终没这么做。", seq=3, r=(0.625, 0.340, 0.145, 0.135), t="symbol"),
        ],
    ),
    dict(
        sid="scene-05", dur=8000,
        story="出发前，父亲在门口抬手叮嘱我。",
        els=[
            dict(id="house", label="老房与院墙", role="场景铺垫：出发前的家",
                 sub="出发前父亲交代过我，可以向对方说明我是房主的儿子。", seq=1, r=(0.215, 0.225, 0.430, 0.480), t="structure"),
            dict(id="tree", label="院中枯树", role="环境点缀：老院子的时间痕迹",
                 sub="出发前父亲交代过我，可以向对方说明我是房主的儿子。", seq=2, r=(0.060, 0.090, 0.145, 0.580), t="object"),
            dict(id="father", label="五十多岁的父亲", role="关键人物：抬手叮嘱，灰白头发、微驼，明显年长于我",
                 sub="出发前父亲交代过我，可以向对方说明我是房主的儿子。", seq=3, r=(0.510, 0.425, 0.130, 0.300), t="character"),
            dict(id="narrator", label="三十岁的我", role="关键人物：背影聆听，年轻的听者",
                 sub="出发前父亲交代过我，可以向对方说明我是房主的儿子。", seq=4, r=(0.650, 0.405, 0.120, 0.330), t="character"),
            dict(id="luggage", label="地上的行李", role="关键物件：即将远行的物证",
                 sub="出发前父亲交代过我，可以向对方说明我是房主的儿子。", seq=5, r=(0.595, 0.715, 0.075, 0.070), t="object"),
        ],
    ),
    dict(
        sid="scene-06", dur=7000,
        story="上次回来时天热，窗户是开着的。",
        els=[
            dict(id="tree", label="院中大树", role="场景铺垫：夏日院落的生机",
                 sub="上次回来时要幸运些，可能由于天气太热，那天小静家租户的窗户是开着的。", seq=1, r=(0.090, 0.130, 0.290, 0.380), t="object"),
            dict(id="house", label="厂房与院墙", role="场景铺垫：老房夏日一景",
                 sub="上次回来时要幸运些，可能由于天气太热，那天小静家租户的窗户是开着的。", seq=2, r=(0.340, 0.295, 0.500, 0.330), t="structure"),
            dict(id="window", label="外撑的窗扇", role="关键物体：向外支开的窗，与下一幕衔接",
                 sub="那天小静家租户的窗户是开着的。", seq=3, r=(0.455, 0.385, 0.130, 0.165), t="structure"),
            dict(id="door", label="房门", role="环境点缀：夏日里另一处紧闭的门",
                 sub="那天小静家租户的窗户是开着的。", seq=4, r=(0.355, 0.410, 0.070, 0.190), t="structure"),
        ],
    ),
    dict(
        sid="scene-07", dur=9000,
        story="窗后有个五六岁的小姑娘，坐在从前小静的书桌上做功课。",
        els=[
            dict(id="casement-l", label="左侧窗扇", role="构图框架：从窗外向里看的视角",
                 sub="窗户后面，有个五六岁的小姑娘坐在从前小静的书桌上做功课。", seq=1, r=(0.130, 0.055, 0.150, 0.760), t="structure"),
            dict(id="casement-r", label="右侧窗扇", role="构图框架：对称的窗框",
                 sub="窗户后面，有个五六岁的小姑娘坐在从前小静的书桌上做功课。                ", seq=2, r=(0.700, 0.045, 0.170, 0.770), t="structure"),
            dict(id="interior", label="室内墙面", role="场景铺垫：空荡的室内",
                 sub="窗户后面，有个五六岁的小姑娘坐在从前小静的书桌上做功课。", seq=3, r=(0.270, 0.115, 0.445, 0.410), t="structure"),
            dict(id="desk", label="小静的旧书桌", role="关键物体：曾经属于小静的桌子，如今被租户的孩子使用",
                 sub="有个五六岁的小姑娘坐在从前小静的书桌上做功课。", seq=4, r=(0.375, 0.545, 0.190, 0.130), t="object"),
            dict(id="girl", label="做功课的小姑娘", role="关键人物：五六岁，低头写字，安静专注",
                 sub="有个五六岁的小姑娘坐在从前小静的书桌上做功课。", seq=5, r=(0.475, 0.410, 0.115, 0.245), t="character"),
            dict(id="chair", label="木椅", role="环境点缀：简陋的椅子",
                 sub="有个五六岁的小姑娘坐在从前小静的书桌上做功课。", seq=6, r=(0.555, 0.525, 0.075, 0.180), t="object"),
            dict(id="sill", label="窗台", role="环境点缀：把内外分隔开的边界",
                 sub="有个五六岁的小姑娘坐在从前小静的书桌上做功课。", seq=7, r=(0.215, 0.755, 0.600, 0.075), t="object"),
        ],
    ),
    dict(
        sid="scene-08", dur=7000,
        story="我忍不住停下，望着她发了一会呆。",
        els=[
            dict(id="wall", label="砖墙", role="场景铺垫：我所站立的墙外",
                 sub="我忍不住停下，望着她发了一会呆。", seq=1, r=(0.055, 0.095, 0.290, 0.420), t="structure"),
            dict(id="window", label="厂房钢窗", role="关键物体：窗内即是那盏旧书桌",
                 sub="我忍不住停下，望着她发了一会呆。", seq=2, r=(0.105, 0.135, 0.200, 0.285), t="structure"),
            dict(id="narrator", label="驻足发呆的三十岁我", role="关键人物：定住不动，望向窗口，故事的关键停顿",
                 sub="我忍不住停下，望着她发了一会呆。", seq=3, r=(0.265, 0.385, 0.095, 0.245), t="character"),
            dict(id="paving", label="地面砖与影子", role="环境点缀：脚下的光斑，暗示午后",
                 sub="我忍不住停下，望着她发了一会呆。", seq=4, r=(0.175, 0.635, 0.470, 0.135), t="object"),
        ],
    ),
    dict(
        sid="scene-09", dur=9000,
        story="晃神里，我看见童年的自己跑到小静的窗下喊她。",
        els=[
            dict(id="house", label="厂房与门口", role="场景铺垫：记忆中的老房",
                 sub="在那个晃神里，我似乎看见童年的自己跑到小静的窗户下喊她出来玩。", seq=1, r=(0.010, 0.070, 0.375, 0.500), t="structure"),
            dict(id="boy", label="奔跑的七岁男孩", role="关键人物：张开手臂、嘴张开呼喊，奔向窗户",
                 sub="我似乎看见童年的自己跑到小静的窗户下喊她出来玩。", seq=2, r=(0.565, 0.475, 0.185, 0.290), t="character"),
            dict(id="bubble", label="空对话框", role="关键符号：喊出的那句「出来玩」仍留白",
                 sub="我似乎看见童年的自己跑到小静的窗户下喊她出来玩。", seq=3, r=(0.745, 0.290, 0.145, 0.140), t="symbol"),
            dict(id="tree", label="院中小树", role="环境点缀：记忆里的院落",
                 sub="我似乎看见童年的自己跑到小静的窗户下喊她出来玩。", seq=4, r=(0.790, 0.560, 0.140, 0.135), t="object"),
        ],
    ),
    dict(
        sid="scene-10", dur=7000,
        story="起初她不答应，装模作样地做功课。",
        els=[
            dict(id="xiaojing", label="七岁的小静", role="关键人物：短马尾、无袖衫，手撑下巴、眼神看向别处，装作在做功课，酷飒不乖",
                 sub="起初她不答应，装模作样地做功课。", seq=1, r=(0.345, 0.135, 0.150, 0.230), t="character"),
            dict(id="bubble", label="空对话框", role="关键符号：她没答应的回应留白",
                 sub="起初她不答应，装模作样地做功课。", seq=2, r=(0.535, 0.165, 0.080, 0.070), t="symbol"),
            dict(id="desk", label="小静的旧书桌与课本", role="关键物体：她从前做功课的地方，桌上摊着空白的书",
                 sub="起初她不答应，装模作样地做功课。", seq=3, r=(0.335, 0.395, 0.390, 0.230), t="object"),
            dict(id="chair", label="木椅", role="环境点缀：她坐着的椅子",
                 sub="起初她不答应，装模作样地做功课。", seq=4, r=(0.280, 0.365, 0.085, 0.175), t="object"),
            dict(id="foreground", label="窗框与前景椅", role="构图前景：从窗外望去的框景",
                 sub="起初她不答应，装模作样地做功课。", seq=5, r=(0.000, 0.000, 1.000, 1.000), t="structure",
                 protect=[(0.000, 0.430, 0.450, 0.570), (0.620, 0.000, 0.380, 1.000)],
                 last=True),
        ],
    ),
    dict(
        sid="scene-11", dur=8000,
        story="我感到失望，打算独自回家。",
        els=[
            dict(id="factory", label="厂房长排", role="场景铺垫：渐行渐远的厂房",
                 sub="在我感到失望，打算独自回家时，", seq=1, r=(0.030, 0.470, 0.530, 0.150), t="structure"),
            dict(id="boy", label="垂肩低头走开的男孩", role="关键人物：背包、耸肩、垂头，情绪低落的背影",
                 sub="在我感到失望，打算独自回家时，", seq=2, r=(0.435, 0.545, 0.110, 0.150), t="character"),
            dict(id="birds", label="飞鸟", role="环境点缀：掠过的鸟群，强化离别的空旷",
                 sub="在我感到失望，打算独自回家时，", seq=3, r=(0.330, 0.140, 0.470, 0.145), t="object"),
            dict(id="tree", label="枯树", role="环境点缀：荒凉的前景",
                 sub="在我感到失望，打算独自回家时，", seq=4, r=(0.705, 0.580, 0.120, 0.125), t="object"),
            dict(id="ground", label="空地", role="环境点缀：留白最多的地方，承载孤独",
                 sub="在我感到失望，打算独自回家时，", seq=5, r=(0.000, 0.720, 1.000, 0.230), t="object",
                 last=True),
        ],
    ),
    dict(
        sid="scene-12", dur=9000,
        story="身后突然传来了开门的声音，小静站在门内。",
        els=[
            dict(id="chimney", label="砖烟囱与通风筒", role="场景标志：老厂房的天际线",
                 sub="身后突然传来了开门的声音。", seq=1, r=(0.550, 0.055, 0.330, 0.115), t="structure"),
            dict(id="factory", label="厂房立面", role="场景铺垫：老房子的正面",
                 sub="身后突然传来了开门的声音。", seq=2, r=(0.375, 0.165, 0.530, 0.300), t="structure"),
            dict(id="door", label="大敞的门", role="关键物体：两扇门板完全敞开贴在墙上",
                 sub="身后突然传来了开门的声音。", seq=3, r=(0.410, 0.395, 0.330, 0.290), t="structure"),
            dict(id="xiaojing", label="门里的小静", role="关键人物：站在门内，细线勾勒的清晰轮廓，平静地等着",
                 sub="身后突然传来了开门的声音。", seq=4, r=(0.570, 0.520, 0.080, 0.150), t="character"),
            dict(id="boy", label="回头的男孩", role="关键人物：停步回头望向门，全片情绪落点",
                 sub="身后突然传来了开门的声音。", seq=5, r=(0.325, 0.590, 0.085, 0.170), t="character"),
        ],
    ),
]

TYPES = {"structure": "structure", "character": "character",
         "object": "object", "symbol": "symbol"}


def to_px(r, w, h):
    x, y, rw, rh = r
    return (int(round(x * w)), int(round(y * h)),
            int(round(rw * w)), int(round(rh * h)))


def build() -> list:
    issues = []
    out = []
    for sc in SCENES:
        exact = D / f"{sc['sid']}.png"
        if exact.exists():
            img, out_name = exact, f"{sc['sid']}"
        else:
            cands = sorted(c for c in D.glob(f"{sc['sid']}-*.png")
                           if not c.name.startswith("_"))
            if not cands:
                issues.append(f"{sc['sid']}: 找不到对应图片")
                continue
            img = cands[0]
            out_name = img.stem
        w, h = Image.open(img).size
        els = []
        for e in sc["els"]:
            x, y, rw, rh = to_px(e["r"], w, h)
            rw = min(rw, w - x)
            rh = min(rh, h - y)
            if x < 0 or y < 0 or x + rw > w or y + rh > h:
                issues.append(f"{sc['sid']}/{e['id']}: 越界 x={x} y={y} w={rw} h={rh} / {w}x{h}")
            protect = []
            for pr in e.get("protect", []):
                px = to_px(pr, w, h)
                protect.append({"x": px[0], "y": px[1], "width": px[2], "height": px[3]})
            # 时序：区域串行作画，按sequence 分配起止
            els.append({
                "id": e["id"],
                "label": e["label"],
                "sequence": e["seq"],
                "narrativeRole": e["role"],
                "subtitle": e["sub"].strip(),
                "type": TYPES[e["t"]],
                "region": {"x": x, "y": y, "width": rw, "height": rh},
                "reveal": {
                    "direction": "left_to_right",
                    "startMs": 0,          # 稍后按串行时序回填
                    "durationMs": 0,
                    "maskPaddingPx": 22,
                    "protectedRegions": protect,
                },
                "handPath": {"start": [x + rw // 2, y], "end": [x + rw // 2, y + rh],
                             "easing": "easeInOut"},
            })

        # 串行时序：按 sequence 排；总时长=幕时长，尾部至少留 500ms 完整原图
        # 布局：起始200ms 呼吸 + n 个作画段+ (n-1) 个 150ms 呼吸 + 尾部 500ms 收尾
        n = len(els)
        lead, gap, tail = 200, 150, 500
        usable = sc["dur"] - lead - gap * (n - 1) - tail
        per = usable // n
        cursor = lead
        for i, el in enumerate(els):
            # 最后一个元素吃掉所有余量，保证不超时
            d = per if i < n - 1 else (sc["dur"] - tail - cursor)
            d = max(d, 200)
            el["reveal"]["startMs"] = cursor
            el["reveal"]["durationMs"] = d
            cursor += d + gap

        last_end = els[-1]["reveal"]["startMs"] + els[-1]["reveal"]["durationMs"]
        out.append({
            "sceneId": sc["sid"],
            "outName": out_name,
            "canvas": {"width": w, "height": h},
            "storyBasis": sc["story"],
            "sceneDurationMs": sc["dur"],
            "elements": els,
        })
        if last_end > sc["dur"]:
            issues.append(f"{sc['sid']}: 末元素结束 {last_end} 超出幕时长 {sc['dur']}")
    return out, issues


def main() -> None:
    scenes, issues = build()
    for sc in scenes:
        p = D / f"{sc['outName']}.annotation.json"
        p.write_text(json.dumps(sc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] {p.name}  {sc['canvas']['width']}x{sc['canvas']['height']}"
              f"  {len(sc['elements'])} 个区域")
    if issues:
        print("\n需要修正：")
        for i in issues:
            print("  !", i)
    else:
        print("\n全部校验通过：坐标均在画布内，时序未超出幕时长。")


if __name__ == "__main__":
    main()
