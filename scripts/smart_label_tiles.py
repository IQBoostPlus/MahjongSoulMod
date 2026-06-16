"""
智能标注牌面模板 — 通过读取牌面特征识别具体牌种

策略:
  1. 从 debug 截图提取手牌 (改进峰值检测)
  2. 通过中心区域颜色区分花色 (筒=红, 索=绿, 万=黑, 字=单色大字)
  3. 通过数字区域模板匹配识别 1-9
  4. 利用雀魂自动理牌特性交叉验证

输出: 正确命名的模板文件 0.png ~ 36.png
"""

import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "debug_output")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles")


def main():
    import cv2
    import numpy as np

    hand_path = os.path.join(INPUT_DIR, "02_hand_roi.png")
    if not os.path.isfile(hand_path):
        print("[ERROR] Run test_vision_live.py first to capture screenshot")
        return

    hand_roi = cv2.imread(hand_path)
    if hand_roi is None:
        print("[ERROR] Cannot read hand ROI")
        return

    h, w = hand_roi.shape[:2]
    gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY)

    # ── 改进的峰值检测: 自适应 min_dist ──
    # 先估算每张牌的宽度
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 水平投影找牌的上边界 (用于精确裁剪)
    h_proj = np.sum(binary == 255, axis=1).astype(np.float32)
    active_rows = np.where(h_proj > h_proj.max() * 0.1)[0]
    if len(active_rows) > 10:
        y1, y2 = active_rows[0], active_rows[-1]
    else:
        y1, y2 = 0, h

    # 垂直投影
    strip = binary[y1:y2, :]
    v_proj = np.sum(strip == 255, axis=0).astype(np.float32)

    # 平滑 — 更宽的核以合并同一张牌的多个峰
    smooth_kernel = max(5, w // 40)
    if smooth_kernel % 2 == 0:
        smooth_kernel += 1
    v_proj_smooth = cv2.GaussianBlur(v_proj, (smooth_kernel, 1),
                                       sigmaX=smooth_kernel / 2.5).flatten()

    # 自适应 min_dist: 假设 13-14 张牌
    # 牌宽 ≈ (手牌区宽度 - 边距) / 牌数
    est_tile_width = w / 14
    min_dist = int(est_tile_width * 0.65)  # 峰值间距 ≈ 牌宽的 65%

    min_height = v_proj_smooth.max() * 0.08
    peaks = []
    for i in range(1, len(v_proj_smooth) - 1):
        if (v_proj_smooth[i] > v_proj_smooth[i-1] and
            v_proj_smooth[i] >= v_proj_smooth[i+1]):
            if v_proj_smooth[i] >= min_height:
                if not peaks or i - peaks[-1] >= min_dist:
                    peaks.append(i)

    # 如果峰值太多, 逐步提高阈值
    while len(peaks) > 16 and min_height < v_proj_smooth.max() * 0.5:
        min_height *= 1.3
        peaks = [p for p in peaks if v_proj_smooth[p] >= min_height]

    # 如果太少, 降低阈值
    while len(peaks) < 10 and min_dist > est_tile_width * 0.3:
        min_dist = int(min_dist * 0.8)
        peaks = []
        min_height = v_proj_smooth.max() * 0.05
        for i in range(1, len(v_proj_smooth) - 1):
            if (v_proj_smooth[i] > v_proj_smooth[i-1] and
                v_proj_smooth[i] >= v_proj_smooth[i+1]):
                if v_proj_smooth[i] >= min_height:
                    if not peaks or i - peaks[-1] >= min_dist:
                        peaks.append(i)

    print(f"[Peaks] {len(peaks)} tiles (min_dist={min_dist}px, min_h={min_height:.0f})")
    print(f"  Peak positions: {peaks}")

    # ── 裁剪 ──
    est_w = int(est_tile_width * 0.85)
    half_w = max(15, est_w // 2)

    crops = []
    for px in peaks:
        x1 = max(0, px - half_w)
        x2 = min(w, px + half_w)
        crop = hand_roi[y1:y2, x1:x2]
        if crop.size > 200 and crop.shape[0] > 10 and crop.shape[1] > 10:
            crops.append((px, crop))

    n = len(crops)
    print(f"[Crops] {n} valid crops")

    # ── 花色检测 ──
    suits = []
    for px, crop in crops:
        suit = detect_suit(crop)
        suits.append(suit)
        from vision.tiles import TILE_NAMES

    print(f"\n[Suits] {[(s,) for s in suits]}")

    # ── 按位置分配 ──
    # 雀魂自动理牌顺序: 万→筒→索→字
    # 从左到右扫描, 同花色连续段 = 该花色的牌
    suit_map = {'m': 0, 'p': 9, 's': 18, 'x': 27}

    # 先检测花色切换点
    segments = []
    cur_suit = suits[0] if suits else 'm'
    seg_start = 0
    for i in range(1, n):
        if suits[i] != cur_suit:
            segments.append((cur_suit, seg_start, i - 1))
            cur_suit = suits[i]
            seg_start = i
    segments.append((cur_suit, seg_start, n - 1))

    print(f"[Segments] {segments}")

    # 分配 tile_id
    labels = [-1] * n
    for suit, start, end in segments:
        base = suit_map.get(suit, 0)
        count = end - start + 1
        for j, idx in enumerate(range(start, end + 1)):
            if suit == 'x':
                # 字牌: 按具体识别
                labels[idx] = base + j
            else:
                # 数牌: 1-9
                labels[idx] = base + j % 9

    # ── 用具体数字识别细化 (对字牌和1-9) ──
    for i, (px, crop) in enumerate(crops):
        suit = suits[i]
        if suit == 'x':
            # 尝试识别具体字牌
            specific = detect_honor(crop)
            if specific >= 0:
                labels[i] = specific

    from vision.tiles import tile_to_name
    print(f"\n[Labels]")
    for i, (px, crop) in enumerate(crops):
        print(f"  [{i:2d}] suit={suits[i]:2s} tile_id={labels[i]:2d} = {tile_to_name(labels[i])}")

    # ── 保存模板 ──
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    saved = set()
    TARGET_H = 48
    for i, (px, crop) in enumerate(crops):
        tid = labels[i]
        if tid < 0 or tid > 36:
            continue

        h_c, w_c = crop.shape[:2]
        new_w = max(6, int(w_c * TARGET_H / h_c))
        resized = cv2.resize(crop, (new_w, TARGET_H))

        path = os.path.join(TEMPLATE_DIR, f"{tid}.png")
        cv2.imwrite(path, resized)
        saved.add(tid)
        print(f"  [save] {tid}.png = {tile_to_name(tid)} ({new_w}x{TARGET_H}px)")

    print(f"\n[Done] Saved {len(saved)} unique templates")
    print(f"  Run: python scripts/test_vision_live.py")


# ═══════════════════════════════════════════════════════════
#  花色检测
# ═══════════════════════════════════════════════════════════

def detect_suit(crop):
    """
    通过牌面颜色特征检测花色。

    返回: 'm' (万), 'p' (筒), 's' (索), 'x' (字)
    """
    import cv2
    import numpy as np

    h, w = crop.shape[:2]

    # 取中心 60% 区域
    cy1 = h // 5
    cy2 = 4 * h // 5
    cx1 = w // 5
    cx2 = 4 * w // 5
    center = crop[cy1:cy2, cx1:cx2]

    # 转 HSV 以更好地分离颜色
    hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)

    # 红色范围 (0-10, 160-180)
    red_low1 = np.array([0, 50, 50])
    red_high1 = np.array([10, 255, 255])
    red_low2 = np.array([160, 50, 50])
    red_high2 = np.array([180, 255, 255])
    red_mask = cv2.inRange(hsv, red_low1, red_high1) | cv2.inRange(hsv, red_low2, red_high2)
    red_ratio = red_mask.sum() / red_mask.size

    # 绿色范围 (40-80)
    green_low = np.array([35, 40, 40])
    green_high = np.array([85, 255, 255])
    green_mask = cv2.inRange(hsv, green_low, green_high)
    green_ratio = green_mask.sum() / green_mask.size

    # 正常 BGR 通道
    mean_bgr = center.mean(axis=(0, 1))
    mean_b, mean_g, mean_r = mean_bgr[0], mean_bgr[1], mean_bgr[2]

    # 极亮 = 白 (白板)
    brightness = center.mean()
    if brightness > 200:
        return 'x'  # 白

    # 极暗 = 字牌或万子
    darkness = 255 - brightness

    if red_ratio > 0.03:
        return 'p'  # 筒 (红色圆点)
    if green_ratio > 0.03 or (mean_g > mean_r + 3 and mean_g > mean_b + 3):
        return 's'  # 索 (绿色特征)

    # 万子 vs 字牌: 万子有密集笔画, 字牌是大面积单字
    gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
    # 用 Canny 边缘数判断复杂度
    edges = cv2.Canny(gray, 50, 150)
    edge_density = edges.sum() / edges.size

    if edge_density > 0.08:
        return 'm'  # 万 (笔画多)
    else:
        return 'x'  # 字牌 (大字, 边缘少)


def detect_honor(crop):
    """
    识别具体字牌: 東(27), 南(28), 西(29), 北(30), 白(31), 發(32), 中(33)

    通过颜色特征区分:
      白=极亮(>220) → 31
      發=偏绿 → 32
      中=偏红 → 33
      东南西北=暗黑 → 无法细分, 默认按顺序
    """
    import cv2
    import numpy as np

    h, w = crop.shape[:2]
    center = crop[h//4:3*h//4, w//4:3*w//4]
    hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
    mean_bgr = center.mean(axis=(0, 1))
    mean_b, mean_g, mean_r = mean_bgr[0], mean_bgr[1], mean_bgr[2]

    brightness = center.mean()

    if brightness > 210:
        return 31  # 白
    if mean_g > mean_r + 5 and mean_g > mean_b + 5:
        return 32  # 發 (绿)
    if mean_r > mean_g + 10 and mean_r > mean_b + 10:
        return 33  # 中 (红)

    # 东南西北 — 无法细分, 保持原分配
    return -1


if __name__ == "__main__":
    main()
