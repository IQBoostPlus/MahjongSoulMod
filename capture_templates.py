#!/usr/bin/env python3
"""
Airtest 模板采集工具

在当前屏幕截图中框选按钮区域，保存为模板文件。
用于让 Airtest 准确识别游戏中的按钮。

用法:
  1. 打开雀魂并进入对局 (让按钮显示在屏幕上)
  2. 切换到终端，运行:
     python capture_templates.py

  3. 按提示在截图中框选:
     - pon (碰按钮)
     - chi (吃按钮)
     - kan (杠按钮)
     - riichi (立直按钮)
     - ron (荣和按钮)
     - tsumo (自摸按钮)
     - pass (过按钮)

模板保存到 templates/ 目录。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import pyautogui
    import cv2
    import numpy as np
except ImportError:
    print("需要安装: pip install pyautogui opencv-python numpy")
    sys.exit(1)


def capture_template(name, description):
    """截屏并在窗口中框选模板区域"""
    print(f"\n{'='*50}")
    print(f"  截取模板: {name} ({description})")
    print(f"{'='*50}")
    print(f"  1. 确保游戏窗口中 '{description}' 按钮可见")
    print(f"  2. 切换到终端，按 Enter 截图...")
    input()

    # 截图
    screen = pyautogui.screenshot()
    img = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
    clone = img.copy()

    # 用鼠标框选
    print(f"  3. 在截图中用鼠标框选 '{description}' 按钮区域")
    print(f"     左键拖拽框选 → 按 SPACE 确认 → 按 C 重选 → 按 ESC 跳过")

    roi = cv2.selectROI(f"Select: {name} - {description}", clone, False)
    cv2.destroyAllWindows()

    x, y, w, h = roi
    if w == 0 or h == 0:
        print(f"  ⏭ 跳过: {name}")
        return False

    # 保存
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    os.makedirs(template_dir, exist_ok=True)
    path = os.path.join(template_dir, f"{name}.png")
    cv2.imwrite(path, img[y:y+h, x:x+w])
    print(f"  ✅ 已保存: {path} ({w}x{h})")
    return True


def auto_capture():
    """自动模式: 对整个屏幕截图，保存为模板参考"""
    print("\n自动截屏模式")
    print("将在 3 秒后截屏，保存完整游戏画面作为参考...")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    screen = pyautogui.screenshot()
    img = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    os.makedirs(template_dir, exist_ok=True)
    path = os.path.join(template_dir, "_full_screen_ref.png")
    cv2.imwrite(path, img)
    print(f"  已保存参考截图: {path}")
    print(f"  请用图片编辑器从此截图中裁剪按钮区域")


def main():
    print("=" * 50)
    print("  Airtest 模板采集工具")
    print("=" * 50)
    print()
    print("  选择模式:")
    print("    1. 交互式框选 (逐个截取按钮)")
    print("    2. 自动截屏 (保存完整截图, 手动裁剪)")
    print()
    choice = input("  输入 1 或 2 [2]: ").strip() or "2"

    if choice == "1":
        templates = [
            ("pon",    "碰"),
            ("chi",    "吃"),
            ("kan",    "杠"),
            ("riichi", "立直"),
            ("ron",    "荣和"),
            ("tsumo",  "自摸"),
            ("pass",   "过/跳过"),
        ]
        captured = 0
        for name, desc in templates:
            if capture_template(name, desc):
                captured += 1
        print(f"\n完成! 已采集 {captured}/{len(templates)} 个模板")
    else:
        auto_capture()
        print()
        print("  下一步:")
        print("  1. 用画图/Photoshop 打开 templates/_full_screen_ref.png")
        print("  2. 裁剪按钮区域，保存为 pon.png, chi.png 等")
        print("  3. 裁剪手牌区域，保存为 tile_area.png")


if __name__ == "__main__":
    main()
