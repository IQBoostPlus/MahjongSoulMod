"""
从 debug 截图提取真实牌面模板

读取 debug_output/01_raw_frame.png + 02_hand_roi.png,
用垂直投影分割每张牌, 保存到对应 tile_id 的模板文件。

需要用户在保存后手动标注每张牌对应的 tile_id。

用法:
  python scripts/extract_from_screenshot.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "debug_output")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles")


def main():
    import cv2
    import numpy as np

    hand_path = os.path.join(OUTPUT_DIR, "02_hand_roi.png")
    if not os.path.isfile(hand_path):
        print(f"[ERROR] {hand_path} not found — run test_vision_live.py first")
        return

    hand_roi = cv2.imread(hand_path)
    h, w = hand_roi.shape[:2]
    print(f"[OK] Loaded hand ROI: {w}x{h}")

    # 垂直投影分割
    gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY)
    # 用大津二值化
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    projection = np.sum(binary == 255, axis=0).astype(np.float32)
    # 平滑
    kernel = max(3, w // 80)
    if kernel % 2 == 0:
        kernel += 1
    projection = cv2.GaussianBlur(projection, (kernel, 1), sigmaX=2.0).flatten()

    # 峰值检测
    min_dist = w // 20
    min_height = projection.max() * 0.15
    peaks = []
    for i in range(1, len(projection) - 1):
        if projection[i] > projection[i - 1] and projection[i] >= projection[i + 1]:
            if projection[i] >= min_height:
                if not peaks or i - peaks[-1] >= min_dist:
                    peaks.append(i)

    print(f"[OK] Found {len(peaks)} peaks")

    # 为每张牌裁剪
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    # 估算牌宽
    tile_w = w // max(len(peaks), 1)
    tile_h = h - 6

    print(f"\n[Extract] Cropping tiles ({tile_w}x{tile_h}px each):")
    print(f"  Saving to: {TEMPLATE_DIR}/")

    # 保存每张牌的裁剪图
    extracted = []
    for i, px in enumerate(peaks):
        x1 = max(0, px - tile_w // 2 + 2)
        x2 = min(w, px + tile_w // 2 - 2)
        y1 = 3
        y2 = max(4, h - 3)

        tile_img = hand_roi[y1:y2, x1:x2]
        if tile_img.size < 50:
            continue

        # 保存为临时文件
        fname = f"real_{i:02d}.png"
        path = os.path.join(TEMPLATE_DIR, fname)
        cv2.imwrite(path, tile_img)
        print(f"  [{i:2d}] {fname} ({x2-x1}x{y2-y1}px)")
        extracted.append((i, fname, tile_img))

    print(f"\n[Done] Extracted {len(extracted)} tile images")
    print(f"\n  下一步：")
    print(f"  1. 打开 {TEMPLATE_DIR}/ 查看 real_*.png")
    print(f"  2. 对照游戏画面, 将每张图重命名为 tile_id.png")
    print(f"     Tile ID: 0-8=万, 9-17=筒, 18-26=索, 27-33=字")
    print(f"  3. 运行 python scripts/test_vision_live.py 重新测试")
    print(f"\n  或者, 如果你现在能告诉我每张牌是什么,")
    print(f"  我可以直接帮你重命名")


if __name__ == "__main__":
    main()
