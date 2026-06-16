"""
从真实游戏截屏采集牌面模板 — 半自动工具

使用方法:
  1. 打开雀魂, 进入对局 (或观战)
  2. 运行: python scripts/capture_real_templates.py
  3. 按提示操作 — 自动截取手牌区域并分割为单张模板
  4. 模板保存到 vision/templates/tiles/

需要: pyautogui, opencv-python, numpy

工作原理:
  - 全屏截图
  - 在手牌区域做垂直投影分割 (每 14 张牌)
  - 每张牌保存为独立的 tile_{id}.png
  - 用户确认每张牌的映射
"""

import os
import sys
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles")


def capture_hand_templates(hand_mode="13"):
    """
    截取当前手牌区并分割为模板。

    Args:
        hand_mode: "13" (刚配牌) 或 "14" (摸牌后)
    """
    try:
        import pyautogui
        import cv2
        import numpy as np
        import pygetwindow as gw
    except ImportError as e:
        print(f"[ERROR] Missing dependency: {e}")
        print("  pip install pyautogui opencv-python numpy pygetwindow")
        return

    # 查找雀魂窗口
    game_win = None
    for w in gw.getAllWindows():
        title = w.title or ""
        if any(kw in title for kw in ["雀魂", "MahjongSoul", "Mahjong Soul"]):
            if w.visible and w.width > 800:
                game_win = w
                break

    if game_win is None:
        print("[ERROR] 雀魂窗口未找到 — 请打开游戏")
        return

    print(f"[OK] Found window: '{game_win.title}' "
          f"({game_win.width}x{game_win.height})")

    # 激活窗口
    try:
        game_win.activate()
        time.sleep(0.5)
    except Exception:
        pass

    # 截全屏
    screen = pyautogui.screenshot()
    frame = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

    # 只取窗口区域
    wx, wy, ww, wh = game_win.left, game_win.top, game_win.width, game_win.height
    frame = frame[wy:wy+wh, wx:wx+ww]

    h, w = frame.shape[:2]
    print(f"[OK] Captured {w}x{h} frame")

    # 手牌区域 (窗口 88%-98% 高度, 3%-97% 宽度)
    hand_y1 = int(h * 0.88)
    hand_y2 = int(h * 0.98)
    hand_x1 = int(w * 0.03)
    hand_x2 = int(w * 0.97)

    hand_roi = frame[hand_y1:hand_y2, hand_x1:hand_x2]
    gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY)

    # 垂直投影分割
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    projection = np.sum(binary == 255, axis=0).astype(np.float32)

    # 高斯平滑
    kernel = max(3, w // 100)
    if kernel % 2 == 0:
        kernel += 1
    projection = cv2.GaussianBlur(projection, (kernel, 1), sigmaX=2.0)
    projection = projection.flatten()

    # 峰值检测
    min_dist = hand_roi.shape[1] // 18
    min_h = projection.max() * 0.2
    peaks = []
    for i in range(1, len(projection) - 1):
        if projection[i] > projection[i-1] and projection[i] >= projection[i+1]:
            if projection[i] >= min_h:
                if not peaks or i - peaks[-1] >= min_dist:
                    peaks.append(i)

    print(f"[OK] Found {len(peaks)} tile positions")

    if len(peaks) < 5:
        print("[WARN] Too few tiles detected — adjust thresholds or capture in better light")
        return

    # 裁剪每张牌
    tile_h = hand_roi.shape[0] - 4
    tile_w = max(10, hand_roi.shape[1] // len(peaks))

    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    saved = 0
    print("\n[Capture] Extracted tiles — please map each to its tile_id:")
    print("  Tile IDs: 0-8=man, 9-17=pin, 18-26=sou, 27-33=honors, 34-36=red dora")
    print("  (Press Enter to save with auto-index, or type tile_id + Enter)")

    for i, px in enumerate(peaks):
        x1 = max(0, px - tile_w // 2)
        x2 = min(hand_roi.shape[1], px + tile_w // 2)
        y1 = 2
        y2 = max(3, hand_roi.shape[0] - 2)

        tile_img = hand_roi[y1:y2, x1:x2]

        # 跳过太小或太暗的
        if tile_img.size < 100:
            continue

        gray_tile = cv2.cvtColor(tile_img, cv2.COLOR_BGR2GRAY)
        if gray_tile.std() < 15:
            continue

        # 自动保存
        path = os.path.join(TEMPLATE_DIR, f"captured_{i}.png")
        cv2.imwrite(path, tile_img)

        # 预览
        h_t, w_t = tile_img.shape[:2]
        print(f"  [{i:2d}] saved as captured_{i}.png ({w_t}x{h_t}px)")

        saved += 1

    print(f"\n[Done] Captured {saved} tiles → {TEMPLATE_DIR}")
    print(f"  Next: rename captured_*.png to 0.png ~ 36.png matching actual tiles")


def list_and_verify():
    """列出现有模板并验证"""
    if not os.path.isdir(TEMPLATE_DIR):
        print(f"[ERROR] Template directory not found: {TEMPLATE_DIR}")
        return

    files = [f for f in os.listdir(TEMPLATE_DIR) if f.endswith(".png")]
    print(f"[Templates] {len(files)} files in {TEMPLATE_DIR}:")

    from vision.tiles import TILE_NAMES

    for f in sorted(files, key=lambda x: int(os.path.splitext(x)[0]) if os.path.splitext(x)[0].isdigit() else 999):
        tid_str = os.path.splitext(f)[0]
        try:
            tid = int(tid_str)
            name = TILE_NAMES[tid] if 0 <= tid < len(TILE_NAMES) else "?"
        except ValueError:
            name = "?"
            tid = -1

        path = os.path.join(TEMPLATE_DIR, f)
        size = os.path.getsize(path)
        print(f"  {f:20s} → tile_id={tid:2d} {name:5s} ({size}B)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="雀魂牌面模板采集工具")
    parser.add_argument("--capture", action="store_true", help="从游戏窗口截取手牌模板")
    parser.add_argument("--list", action="store_true", help="列出现有模板")
    parser.add_argument("--verify", action="store_true", help="验证模板质量")

    args = parser.parse_args()

    if args.list:
        list_and_verify()
    elif args.capture:
        capture_hand_templates()
    else:
        print("雀魂牌面模板采集工具")
        print("  --capture  从游戏截取手牌并分割")
        print("  --list     列出现有模板")
        print("  --verify   验证模板质量")
        print()
        list_and_verify()
