# DESIGN.md — 篮球图片集

## 设计原则
用户明确要求**零设计**：不做风格方案，只把图片贴进每页。因此本文件仅记录最小必要约束。

## 画布
- 尺寸：1280 × 720 px（16:9）

## 极简规则
- 每页 = 一张 1:1 图片，居中放置，等比例缩放（用 `objectFit: 'contain'` 保证不裁切主体）。
- 图片高度按 1:1 约束，取 600px（宽 600px），垂直居中。
- 背景：纯白 `#FFFFFF`（干净、无干扰）。
- 页码：右下角，16px，`#9CA3AF`，格式 `NN/08`。
- 字体：系统默认（不指定特殊字体）。
- 色彩：仅 `#FFFFFF` 背景 + `#9CA3AF` 页码灰，无需主色/辅色。

## 图片清单
| 文件 | 来源 | 真实内容 | 使用页 | 已核对 |
|---|---|---|---|---|
| assets/01_basketball_equipment.png | 用户材料 | 篮球特写 | 01 | ✅ |
| assets/02_basketball_court_sunset.png | 用户材料 | 夕阳球场 | 02 | ✅ |
| assets/03_basketball_player_dunk.png | 用户材料 | 球员扣篮 | 03 | ✅ |
| assets/04_basketball_sneakers.png | 用户材料 | 篮球鞋 | 04 | ✅ |
| assets/05_basketball_jersey.png | 用户材料 | 34 号球衣 | 05 | ✅ |
| assets/06_basketball_team_huddle.png | 用户材料 | 球队围圈 | 06 | ✅ |
| assets/07_basketball_streetball.png | 用户材料 | 夜间街头球场 | 07 | ✅ |
| assets/08_basketball_championship.png | 用户材料 | 冠军奖杯 | 08 | ✅ |
