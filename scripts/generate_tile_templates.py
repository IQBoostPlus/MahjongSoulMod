"""
合成雀魂牌面模板

用 PIL 程序化生成 37 张标准日麻牌面模板图片。
干净、无噪声 — 模板匹配效果优于截图提取。

牌面布局 (模仿雀魂风格):
  ┌─────────┐
  │  5       │  ← 数字/汉字 (居中)
  │          │
  │ 万       │  ← 花色小字 (右下角)
  └─────────┘

模板输出: vision/templates/tiles/{0..36}.png
尺寸: ~48×32px, 灰度 PNG

运行: python scripts/generate_tile_templates.py
"""

import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles")

# ── 牌面定义 ──
# 每张牌: (主文字, 花色名, 颜色)
TILE_DEFS = [
    # 万子 (0-8) — 数字 + "万"
    ("1", "万", (40, 40, 40)), ("2", "万", (40, 40, 40)),
    ("3", "万", (40, 40, 40)), ("4", "万", (40, 40, 40)),
    ("5", "万", (40, 40, 40)), ("6", "万", (40, 40, 40)),
    ("7", "万", (40, 40, 40)), ("8", "万", (40, 40, 40)),
    ("9", "万", (40, 40, 40)),
    # 筒子 (9-17) — 数字 + 筒图案
    ("1", "筒", (40, 40, 40)), ("2", "筒", (40, 40, 40)),
    ("3", "筒", (40, 40, 40)), ("4", "筒", (40, 40, 40)),
    ("5", "筒", (40, 40, 40)), ("6", "筒", (40, 40, 40)),
    ("7", "筒", (40, 40, 40)), ("8", "筒", (40, 40, 40)),
    ("9", "筒", (40, 40, 40)),
    # 索子 (18-26) — 数字 + "索"
    ("1", "索", (40, 40, 40)), ("2", "索", (40, 40, 40)),
    ("3", "索", (40, 40, 40)), ("4", "索", (40, 40, 40)),
    ("5", "索", (40, 40, 40)), ("6", "索", (40, 40, 40)),
    ("7", "索", (40, 40, 40)), ("8", "索", (40, 40, 40)),
    ("9", "索", (40, 40, 40)),
    # 字牌 (27-33) — 单汉字
    ("東", "", (40, 40, 40)), ("南", "", (40, 40, 40)),
    ("西", "", (40, 40, 40)), ("北", "", (40, 40, 40)),
    ("白", "", (40, 40, 40)), ("發", "", (0, 100, 0)),  # 绿
    ("中", "", (180, 20, 20)),  # 红
    # 赤宝牌 (34-36) — 红色数字
    ("5", "万", (200, 30, 30)),  # 赤5万
    ("5", "筒", (200, 30, 30)),  # 赤5筒
    ("5", "索", (200, 30, 30)),  # 赤5索
]


def generate_all():
    """生成全部 37 张模板"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[ERROR] PIL/Pillow required: pip install Pillow")
        return

    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    # 尝试加载中文字体
    font_main, font_suit = _find_fonts()

    # 模板尺寸
    TILE_W = 32
    TILE_H = 48
    MARGIN = 2  # 边框

    generated = 0

    for tile_id, (main_text, suit_text, color) in enumerate(TILE_DEFS):
        # 创建牌面 (白色底 + 浅灰边框)
        img = Image.new("L", (TILE_W, TILE_H), 240)  # 255=白, 0=黑

        draw = ImageDraw.Draw(img)

        # 边框 (深灰, 模拟牌边)
        draw.rectangle([0, 0, TILE_W - 1, TILE_H - 1], outline=80, width=1)

        # 内缩区域
        inner = [MARGIN, MARGIN, TILE_W - MARGIN, TILE_H - MARGIN]
        draw.rectangle(inner, outline=120, width=1)

        # 主文字 (居中偏上)
        main_size = 20 if len(main_text) == 1 else 14

        try:
            font_m = ImageFont.truetype(font_main, main_size)
        except Exception:
            font_m = ImageFont.load_default()

        # 文字边界框
        bbox = draw.textbbox((0, 0), main_text, font=font_m)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        mx = (TILE_W - tw) // 2
        my = (TILE_H - th) // 2 - 3  # 稍偏上

        # 画主文字 (用灰色填充模拟 RGB 颜色 → 灰度)
        gray_color = int(0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2])
        draw.text((mx, my), main_text, fill=gray_color, font=font_m)

        # 花色文字 (右下角小字)
        if suit_text:
            try:
                font_s = ImageFont.truetype(font_suit, 10)
            except Exception:
                font_s = ImageFont.load_default()

            s_bbox = draw.textbbox((0, 0), suit_text, font=font_s)
            sw = s_bbox[2] - s_bbox[0]
            sx = TILE_W - MARGIN - sw - 2
            sy = TILE_H - 14

            gray_suit = int(0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2])
            draw.text((sx, sy), suit_text, fill=gray_suit, font=font_s)

        # 保存为灰度 PNG
        path = os.path.join(TEMPLATE_DIR, f"{tile_id}.png")
        img.save(path, "PNG")
        generated += 1

        # 简要日志
        from vision.tiles import tile_to_name
        print(f"  [{tile_id:2d}] {tile_to_name(tile_id):4s} = {main_text}{suit_text} → {TILE_W}x{TILE_H}px")

    print(f"\n[Done] Generated {generated} tile templates → {TEMPLATE_DIR}")
    print("  Note: These are synthetic templates. For best accuracy,")
    print("  replace them with real game screenshots using capture_templates.py")


def _find_fonts():
    """查找系统中可用的中文字体"""
    import platform

    font_main = None
    font_suit = None

    if platform.system() == "Windows":
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
            "C:/Windows/Fonts/simsun.ttc",     # 宋体
            "C:/Windows/Fonts/simhei.ttf",     # 黑体
            "C:/Windows/Fonts/msgothic.ttc",   # MS Gothic (日文)
            "C:/Windows/Fonts/arial.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

    for path in candidates:
        if os.path.isfile(path):
            if font_main is None:
                font_main = path
            font_suit = path
            break

    return font_main, font_suit


if __name__ == "__main__":
    generate_all()
