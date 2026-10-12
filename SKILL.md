---
name: srt-whiteboard-animation
description: 将 SRT 字幕做成暖米黄纸张底的白板手绘动画：读字幕→输出配图策略→确认后生成统一风格线稿→按叙事语义标注分区→预览台调整→渲染 MP4→可选配音（TTS）与背景音乐混音。编排沿用分区遮罩揭示（annotation.json / sequence / startMs / protectedRegions），但每个区域内的落墨换成 stream 的连续笔迹（骨架/网格 ink→color）。当用户提供 SRT 字幕并要求"字幕做成白板手绘/流式笔迹视频""SRT 生成白板动画""按字幕分镜画手绘""白板动画加配音/字幕"时触发。
---

# SRT 白板动画（mask 编排 + stream 画法）

把 SRT 字幕转成白板手绘动画：**编排**沿用分区遮罩揭示（按叙事顺序逐区域揭示、未开始区域完全隐藏、重叠用 `protectedRegions` 保护）；**画法**换成流式笔迹——每个区域在自己的允许掩码内，笔尖沿骨架/网格连续滑行落墨（起笔 ink → 添彩 color），所有区域共享一张持久画布，已画完的区域保留在画布上。所有面向用户的说明、分镜、配置和界面文字必须使用中文。

与逐格跳变或矩形擦除不同：本 skill 的笔迹是**连贯流动**的；与整图stream 不同：本 skill 按**字幕叙事分区**依次作画，可控制每个元素的出场顺序与时序。

> **⚠️ 动手前必读`references/production-lessons.md`**
> 那里面记录了真实项目中所有失败案例的根因与正解：出图去色、建筑变城堡、
> 铅笔手锚点为0导致只露笔尖、TTS 资源 ID 与鉴权诊断、混音三重坑、
> **幕号漏一导致后续全部错位**、字幕逐字校验等。跳过它会重复踩坑。

## 用户偏好（协作要点）

- **零容忍演示/占位实现**：任何环节都要真实可用，临时方案必须显式声明。
- **先查数据再改码**：用户陈述的现象（如"某两幕重叠了"）是他已验证的事实，
  直接查数据确认，不要质疑；报告要带具体数字（多少秒、多少 dB、改了哪个文件）。
- **交付前跑量化校验**：用户会逐帧/逐段核对（"第5 幕和第 6 幕重叠"这种级别），
  肉眼判断不可靠，必须用脚本输出对比表。
- **风格与设定要一次定死**：人物年龄、建筑样式等写成逐字复用的固定提示词段落，
  否则 12 张图会漂移，导致全量重做。
- **修改要局部可重做**：渲染脚本支持单幕参数覆盖，不要每次都全量重渲。

## 默认实现参数

| 项目 | 默认要求 |
|---|---|
| 纸张背景 | 生成图使用暖米黄旧纸色（建议 `#F5EBD7`）；渲染时从原图距四角内缩取样染底，禁止纯白。 |
| 画法 | 每区域 stream 连续笔迹：起笔 `ink`（铺线稿）→ 添彩 `color`（还原原色）；权重 `ink:color = 2:1`。 |
| 笔迹路径 | `--ink-path grid`（网格，默认，稳）或 `skeleton`（骨架追踪，线稿清晰的插画更贴合）。 |
| 上色风格 | `--color-fill contour-wipe`（轮廓扫描，默认）或 `brush`（沿轨迹刷）。 |
| 笔尖素材 | 默认素材是**写实 3D 手**，与扁平线稿冲突时改用手绘风素材并传入；只要铅笔不要手时传入仅铅笔的素材。 |
| 笔尖锚点 | **必须实测传入**：`--tip-anchor-x/y`（内置素材约 `0.21/0.68`），缺省 `(0,0)` 会把手推出画布只露笔尖。 |
| 笔高度 | `--hand-height` 按画面大小调，线稿细腻时 240–320（缺省 493 适合 1080p）。 |
| 未绘制区域 | 区域的允许掩码 = 矩形 `region` 扣除「后续区域 + protectedRegions」；未开始区域完全隐藏。 |
| 时长来源 | 由**朗读时间轴反推**（见下"配音与混音"），不是先定时长再塞文字。 |
| 编辑框 | 预览台默认显示全部编号编辑框；编辑框不属于动画画面内容。 |

## 统一出图视觉规范（强制）

所有场景的源图必须遵循同一套视觉语言；生成前把以下要求完整写入出图提示词，生成后逐条检查：

- **风格与构图：** 极简手绘插图、纯素描草图风格、类似 Notion 的克制涂鸦美学。以概念表达为主，不追求写实；构图简洁、背景干净、大量留白，整体情感平和、清晰，系列内线条/人物/配色一致。
- **颜色与材质：** 米色纸张背景 `#F5EBD7`、深灰色草图线条；仅可用红色、橙色、蓝色 作少量概念性点缀。不得使用其他强调色、高饱和度配色或复杂纹理。
- **人物与对象：** 对象以简洁轮廓、少量线条和留白表达，强调关系/变化/核心概念，而非真实比例、材质与细节。
- **绝对禁止：** 场景源图中的任何文字、词语、字母、数字、字体或标签；写实感、摄影细节、3D 效果、绘画质感；复杂场景、密集背景、繁复装饰和高饱和度画面。
- **绘制手部例外：** 若用户明确说明笔杆上的文字是其标识并要求保留，可保留 `drawing-hand.png` 笔杆上的标识；它不属于场景源图文字，也不需要清除或重绘。未获得用户明确说明时，仍按无文字画面处理。

## 确认关卡（强制）

默认工作流的**每一步完成后都必须停止并等待用户明确确认**，才可开始下一步。确认前不得生成下一步的图片、标注、预览、视频或合并文件；不得把“未回复”“此前的笼统授权”“用户没有反对”视为确认。用户要求修改上一步时，只重做该步，并在完成后再次等待确认。

唯一的连带动作是：**标注 JSON 创建完成后，必须立即自动打开预览台并载入该 JSON 所在目录**；这属于第 3 步的交付，不需要为“打开预览台”另行等待确认。若浏览器的 File System Access API 要求用户手势，使用浏览器界面选择这个已确定的目录；不得因此向用户索要额外确认或改为让用户自行打开预览台。

## 工作流程

1. **读字幕、出策略（不生成图片）。** 用 `scripts/parse_srt.py` 把 SRT 解析成字幕条并按 25–35 秒/幕给出建议分镜。据此输出配图策略：每幕的场景编号、核心表达、画面主体、对应字幕区间与 `sceneDurationMs`。每幕只表达一个核心意思。**完成后停止，等待用户确认策略。**
2. **生成线稿。** 仅在用户确认策略后，按“统一出图视觉规范”逐幕生成 16:9 暖米黄旧纸张底线稿图，背景 `#F5EBD7`，主体之间保留充足留白便于自动拆分；不得生成文字、复杂照片、重叠对象或与规范冲突的元素。**完成后停止，展示线稿并等待用户确认。**
3. **先读字幕再看图，然后标注并打开预览台。** 仅在用户确认线稿后，先阅读该图对应的字幕、再实际查看图片、并获取原图像素宽高；不得只凭字幕臆测画面，也不得只按画面位置机械排序。先提炼字幕叙事事件，再把图中可见主体对应到事件，按“场景铺垫 → 关键人物/物体 → 动作冲突或变化 → 反应/结果”的语义顺序安排绘制。随后创建 `<图片名>.annotation.json`。创建完成后，立即用默认浏览器打开 `assets/preview.html`，并通过预览台的“打开文件夹”载入**该标注文件所在目录**的全部 `<名称>.png` + `<名称>.annotation.json`；不得只给出文件路径或要求用户自行操作。**预览台已带入目录后停止，等待用户确认标注与预览内容。**
4. **生成区域预览图。** 仅在用户确认标注与预览内容后，用 `render_annotation_preview.py` 出编号/方向检查图，核对分区与叙事顺序一致、区域都在画布内、重叠主体用 `protectedRegions` 保护。**完成后停止，等待用户确认预览图。**
5. **在预览台调整并保存。** 仅在用户确认预览图后，在已打开且已载入对应目录的预览台调整：默认（未播放）显示完整图片和区域框；画布是**矩形代理**：拖区域四边四角改 `region`，右侧改名称/方向/**开始(ms)/结束(ms)**（时长= 结束−开始，只读）与**字幕**，拖动模块列表**调整顺序**（自动重排 `sequence`），选中模块自动高亮对应字幕；拖时间轴或按播放看揭示（未开始区域不显示）；`direction` 只影响此代理。改完点“保存本场景/全部保存”写回原 `.annotation.json`（含每区域 `subtitle`，并把 `sceneDurationMs` 对齐到最后区域结束+0.5s）。**保存后停止，等待用户确认最终标注与时序。**
6. **命令行渲染成片。** 仅在用户确认最终标注与时序后，用 `render_stream_whiteboard.py` 逐幕出全清 MP4，抽查开场、任意重叠模块中段、结尾三个时间点。**完成后停止，等待用户确认成片。**
7. **多幕合并（仅适用于多幕）。** 仅在用户确认所有单幕成片后，用 `merge_scenes.py` 按顺序合并成一条。**完成后停止，等待用户确认最终合成视频。**

## 端到端：给一段文字 → 出成品

用户说"给你一段文字，输出成品"时走这条路径。**配音、字幕、音轨对齐、混音
都已封装在 `scripts/build_audio.py`，不需要手工拼 ffmpeg 命令。**

### 全流程（4 步）

```bash
# 1) 建项目（自动按中文标点分句，一句一幕）
python scripts/make_project.py --name my-video --dir <父目录> \
    --text "第一句话。第二句话。第三句话。" \
    --rate 4.25 --bgm audio/bgm/bg.mp3
# 也支持：--text-file story.txt  或  --srt story.srt

# 2) 按「统一出图视觉规范」生成 N 张线稿 + N 个标注 JSON
#    （线稿放 assets/whiteboard/my-video/scene-NN-xxx.png
#      标注放 assets/whiteboard/my-video/scene-NN-xxx.annotation.json）

# 3) 渲染画面并合并
for i in 01 02 ...; do
  <ENV_PY> scripts/render_stream_whiteboard.py <png> <ann> <mp4> <pencil.png> \
    --tip-anchor-x 0.5482 --tip-anchor-y 0.4605 --hand-height 220
done
<ENV_PY> scripts/merge_scenes.py --inputs .../scene-*-whiteboard.mp4 --output my-video-merged.mp4

# 4) 配音 + 字幕 + 混音 + 校验（一条命令）
export VOLC_API_KEY=<你的 X-Api-Key>
<ENV_PY> scripts/build_audio.py --project <父目录>/my-video all
```

第 4 步会依次完成：**严格按幕窗口对齐 → TTS 合成 → atempo 语速校正 →
摆放语音 → 混音（BGM 压低）→ 生成字幕 → 烧录字幕 → 量化校验**，
产物是 `my-video-final-subtitled.mp4`。

### 分步与调试

```bash
python scripts/build_audio.py --project <dir> plan      # 只看时间轴，不合成
python scripts/build_audio.py --project <dir> tts       # 只合成语音
python scripts/build_audio.py --project <dir> assemble  # 只摆放+变速
python scripts/build_audio.py --project <dir> mix --video <画面.mp4>
python scripts/build_audio.py --project <dir> verify    # 只跑量化校验
```

常用参数：`--rate`（语速，默认 4.25）、`--voice`（音色ID）、
`--engine none`（跳过TTS，自备音频）、`--force`（强制重合成）。

### config.json 说明

`make_project.py` 生成的配置是一切的地基：

| 字段 | 含义 |
|---|---|
| `scenes[].text` | **字幕文本 = 用户原文**，一字不增删；同时用于算字数 |
| `scenes[].speak` | 可选。仅当某句读音需要换气标点时覆盖（如加逗号/破折号）；**不影响字幕** |
| `scenes[].image` | 可选。显式指定线稿名；不填则按 `scene-NN-*.annotation.json` 匹配 |
| `rate` | 目标语速 字/秒。**改这里，不要去改幕时长** |
| `bgm` / `bgm_db` | BGM 路径与电平（默认 −22dB，不抢人声） |
| `bg` / `ink` | 纸色 / 墨色，字幕沿用这套配色 |
| `voice_gain` | 旁白增益（TTS 原始音量偏低，默认 1.6） |

**核心原则：语速锁定，用字数反推幕时长。**
不要先定每幕时长再往里塞文字——那样语速会在 1.4~4.9 字/秒之间剧烈波动。

### 流水线内置的防错（都在 build_audio.py 里）

| 防护 | 触发时 |
|---|---|
| 缺任一幕的文本 / 标注 | 立刻报错退出，**不做静默跳过**（曾因漏一幕导致后续全部偏移 −5.93s） |
| 语音越出本幕窗口 | 报错退出 |
| 语音与上一句重叠 | 报错退出 |
| 某幕时长装不下这句话 | 提示"需X s 超出可用 Y s"，建议调大该幕 `sceneDurationMs` |
| 音轨长度与时间轴不符 | 停止，不产出成片 |
| 字幕与原文逐字比对 | 不一致直接报错 |
| 成片音轨某段低于 −55dB | 校验报"疑似静音" |
| 结尾帧墨迹覆盖率< 0.9 | 校验报!! |

### 用户偏好（协作要点）

- **零容忍演示/占位实现**：任何环节都要真实可用，临时方案必须显式声明。
- **先查数据再改码**：用户陈述的现象（如"某两幕重叠了"）是他已验证的事实，
  直接查数据确认，不要质疑；报告要带具体数字（多少秒、多少 dB、改了哪个文件）。
- **交付前跑量化校验**：用户会逐帧/逐段核对（"第5 幕和第 6 幕重叠"这种级别），
  肉眼判断不可靠，必须用脚本输出对比表。
- **风格与设定要一次定死**：人物年龄、建筑样式等写成逐字复用的固定提示词段落，
  否则 12 张图会漂移，导致全量重做。
- **修改要局部可重做**：渲染脚本支持单幕参数覆盖，不要每次都全量重渲。
- **字幕必须与原文一字不差**，且一比一对应到画面段落。

## 安装

```bash
git clone https://github.com/eason6789/srt-whiteboard-animation.git \
    ~/.agents/skills/srt-whiteboard-animation
# 或 ~/.claude/skills/ 、 ~/.config/<agent>/skills/ 等对应目录

cd ~/.agents/skills/srt-whiteboard-animation
python scripts/prepare_env.py --check   # 探测依赖，末行输出 ENV_PY=<路径>
python scripts/prepare_env.py           # 缺则建 .venv
```

## 目录约定

在用户项目中创建：

```text
assets/whiteboard/<项目名>/
  scene-01-<名称>.png
  scene-01-<名称>.annotation.json     # 与 png 同名
  scene-01-<名称>-whiteboard.mp4      # 成片
  scene-01-<名称>-preview.mp4         # 真实片段（预览台生成，低清）
```

图片与配置必须同名：`foo.png` 对应 `foo.annotation.json`。预览台据此自动加载配置。

## 语义排序与像素级标注（必须执行）

1. **阅读依据：** 标注前必须同时具备字幕与已查看的原图。缺任一项先索取，不得生成标注。
2. **顺序依据：** `sequence`、`startMs` 与 `label` 必须反映字幕中的事件先后，而非仅按从左到右、从上到下或视觉显眼程度。
3. **坐标依据：** 每个模块输出原图坐标系的整数像素 `x`、`y`、`width`、`height`；原点左上角，禁止百分比/比例/估算坐标或省略尺寸。`canvas.width`/`canvas.height` 必须等于原图像素尺寸。
4. **模块字段：** 每个元素含 `sequence`、`narrativeRole`、`subtitle`、`region`、`reveal`、`handPath`。`narrativeRole` 用中文说明其在字幕中的叙事作用；`subtitle` 存该区域对应的字幕文本（来自 SRT，供预览台联动与后续用途）；`sequence` 从 1 起连续。
5. **校验：** 生成预览前检查每个区域是否在画布内、是否覆盖对应可见主体、是否与字幕事件相符；重叠主体用 `protectedRegions` 保护后绘制模块。

## 时序模型（stream 画法专用）

- **每幕总时长** `sceneDurationMs` 来自该幕字幕时间跨度（`parse_srt.py` 的 `scenes[].sceneDurationMs`）。
- **区域串行作画：** stream 画法是一支笔在动，同一幕内各区域应**在时间上依次进行**（`startMs` 不重叠）：下一区域从上一区域 `startMs + durationMs`（+ 可选 100–300ms 呼吸）开始。若 `startMs` 重叠，渲染器仍按顺序处理，但视觉上不再是并发。
- **区域内 ink→color：** 每个区域的 `durationMs` 会按 `ink:color = 2:1` 切成起笔段和添彩段。`durationMs` 由预览台的**开始/结束时间**决定（结束−开始），可对齐该区域对应字幕的时长；也可用 150 像素/秒 × 绘制距离作为初始估算。
- **凝视收尾：** 全部区域画完后自动补到 `sceneDurationMs`，并保证结尾至少停留 0.5 秒完整原图。
- `reveal.direction` 在 stream 画法下**不决定真实笔迹**（笔迹由骨架/网格自动生成），仅供预览台的矩形代理演示；保留它是为了预览台可用。

## 遮罩不变量（编排层，必须执行）

- 在时间 `t`，模块仅可显示其 `reveal.startMs ≤ t` 之后、且不超过当前作画进度的像素；未开始模块的任何线条/填充/图像都不得出现。
- 每个区域的**允许掩码** = 矩形 `region` 扣除全部**后续模块的 `region`**，再扣除本模块 `reveal.protectedRegions`。stream 落墨被限制在允许掩码内，因此后续区域不会提前露线。
- `protectedRegions` 采用与 `region` 相同的原图整数像素坐标，用于矩形过大、主体交叠或背景线条可能泄露的情况。
- 渲染器已实现"限制在允许掩码内落墨 → 后续区域与保护区天然不被触碰"的顺序；预览台矩形代理用等价的 `destination-out` 扣除演示同一编排。

## 配置示例

```json
{
  "sceneId": "scene-01",
  "canvas": { "width": 1672, "height": 941 },
  "storyBasis": "该幕字幕的事件摘要",
  "sceneDurationMs": 9000,
  "elements": [
    {
      "id": "rockery",
      "label": "假山场景",
      "sequence": 1,
      "narrativeRole": "故事的场景铺垫",
      "subtitle": "猴子山上，一只小猴子坐在假山顶端，手里拿着香蕉。",
      "type": "structure",
      "region": { "x": 20, "y": 120, "width": 540, "height": 780 },
      "reveal": { "direction": "top_to_bottom", "startMs": 300, "durationMs": 2600, "maskPaddingPx": 22, "protectedRegions": [] },
      "handPath": { "start": [290, 130], "end": [290, 890], "easing": "easeInOut" }
    }
  ]
}
```

> `direction` / `handPath` 仅供预览台矩形代理使用；成片笔迹由 stream 自动生成，无需精调。

## 使用脚本

所有渲染脚本用 skill 内 `.venv` 的解释器运行（依赖隔离）。

1. **准备环境**（首次或缺依赖时）：
   ```bash
   python scripts/prepare_env.py --check   # 探测；成功末行输出 ENV_PY=<路径>，捕获备用
   python scripts/prepare_env.py           # 缺则建 .venv 并装 opencv-python/numpy/av
   ```
2. **解析字幕 + 建议分镜**：
   ```bash
   python scripts/parse_srt.py <字幕.srt> --target-sec 30 --min-sec 25 --max-sec 35
   ```
3. **区域编号预览图**：
   ```bash
   python scripts/render_annotation_preview.py <图片> <标注> <预览图输出>
   ```
   脚本会自动探测系统中文字体（macOS 的 PingFang/Heiti、Linux 的 DejaVu、Windows 的 msyh），跨平台可用；标签文字为中文，勿手工改成英文。
4. **预览台（无需服务器）**：直接用 Chrome / Edge 打开 `assets/preview.html`，点"打开文件夹"选目录 → 载入全部图片+同名标注 → 拖拽编辑 → "保存"写回原文件。写回需 File System Access API（Chrome/Edge）；其它浏览器改为下载后手动覆盖。渲染仍走命令行（下面第 5 步）。
5. **渲染单幕成片**：
   ```bash
   <ENV_PY> scripts/render_stream_whiteboard.py <图片> <标注> <输出mp4> assets/drawing-hand.png \
       [--ink-path grid|skeleton] [--color-fill contour-wipe|brush] [--total-ms <毫秒>] \
       [--tip-anchor-x <0~1>] [--tip-anchor-y <0~1>] [--hand-height <像素>] [--cap-long-edge <长边像素上限>]
   ```
   `--total-ms` 缺省时用标注里的 `sceneDurationMs`。末行输出 `OUTPUT=<路径>`。
   `--tip-anchor-x/y` 指定笔尖在手部素材上的锚点（0~1 相对素材宽高，缺省 0 即左上角）。**缺省值几乎总是错的**：素材左上角对齐落墨点会把整只手推到画布外、画面上只剩一截笔尖。正确做法是先量出素材里笔尖的真实位置再传入（内置素材实测约 `x=0.21 y=0.68`），渲染后抽帧确认笔尖与线条确实接触。
   `--hand-height` 控制手部缩放后的像素高度（缺省 493，按 1080p 调校）。画面主体较小或线条细腻时应调小到 240–320，否则手会盖住正在画的内容。
   **手部素材与画风不匹配时**：若场景是扁平线稿而内置手部素材是写实质感，应把素材像素按场景同一套"墨色→纸色"双色调重新映射（保留原 alpha），生成与线稿同调的手部素材再传入。
6. **多幕合并**：
   ```bash
   <ENV_PY> scripts/merge_scenes.py --inputs 幕1.mp4 幕2.mp4 幕3.mp4 --output final.mp4
   ```
7. **建项目（配音/字幕项目必做）**：
   ```bash
   python scripts/make_project.py --name my-video --dir <父目录> \
       [--text "第一句。第二句。"| --text-file story.txt| --srt story.srt] \
       [--rate 4.25] [--bgm audio/bgm/bg.mp3] [--bgm-db -22]
   ```
   自动按中文标点分句、一句一幕，生成 `config.json` + `original.txt`
   （`original.txt` 是字幕逐字校验的基准）与目录结构。
8. **配音 + 字幕 + 混音 + 校验（一条命令）**：
   ```bash
   export VOLC_API_KEY=<你的 X-Api-Key>
   <ENV_PY> scripts/build_audio.py --project <父目录>/my-video all
   ```
   子命令：`plan`（只看时间轴）/ `tts` / `assemble` / `mix` / `verify`。
   常用参数：`--rate`、`--voice`、`--engine none`（跳过 TTS 自备音频）、
   `--video`（指定画面成片）、`--force`。
   产物：`<name>-final-subtitled.mp4`。
   **详见上文「端到端：给一段文字 → 出成品」章节。**

## 出图后处理（自带脚本）

以下脚本在 `scripts/` 下，直接可用：

| 脚本 | 作用 | 关键点 |
|---|---|---|
| `duotone.py` | 双色调统一（墨→纸），消除残留彩色 | **不要用简单去色**，会把暖米黄纸底灰化 |
| `clean_watermark.py` | 清除出图角落的模型水印 | 取邻域众数色回填，保留 alpha |
| `gen_annotations.py` | 批量生成标注 JSON（含越界/时序校验） | 时序：`lead + n段 + (n-1)×gap + tail`，最后元素吃余量 |
| `grid_overlay.py` | 叠加归一化坐标网格 | 目测坐标偏差大，先铺网格再读位置 |
| `detect_regions.py` | 形态学分块 | **仅适合粗线稿**；细密线稿会整幅合成一块 |
| `extract_pencil.py` | 从手部素材分离出铅笔（去掉手） | 镜面翻转后笔尖锚点 x′ = 1 − x |

## 质量检查

渲染前/后确认：

- 首帧为干净的暖米黄旧纸张底，没有提前露出线条。
- 已阅读对应字幕并实际查看原图；`canvas` 与原图像素尺寸一致，所有 `region` 为整数像素坐标且在画布内。
- `sequence`、`startMs` 与字幕事件顺序一致；预览图编号/标签/区域来自同一份标注 JSON。
- 在开场、任意重叠模块中段、所有模块完成后三个时间点检查：未绘制模块均不可见，重叠保护区不漏出，最终帧显示完整原图。
- 笔尖贴近正在推进的笔迹；线稿清晰的插画可用 `--ink-path skeleton` 让笔迹更贴合。
- 所有模块结束后停留至少 0.5 秒完整原图。
- 多幕合并后顺序、时长与字幕分镜一致。

如需修改效果，先在预览台（`assets/preview.html`）调整标注（区域/顺序/时序）并保存，再命令行渲染，不要凭空反复出片。
