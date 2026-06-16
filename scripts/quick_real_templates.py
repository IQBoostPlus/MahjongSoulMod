"""
从当前游戏截图自动提取 + 智能标注牌面模板

利用雀魂自动理牌特性推断 tile_id:
  - 手牌自动排序: 万→筒→索→字, 同花色内升序
  - 通过牌面色调/形状区分花色

用法:
  python scripts/quick_real_templates.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "debug_output")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles")


def main():
    import cv2
    import numpy as np

    # 读取手牌 ROI
    hand_path = os.path.join(INPUT_DIR, "02_hand_roi.png")
    raw_path = os.path.join(INPUT_DIR, "01_raw_frame.png")

    if not os.path.isfile(hand_path):
        print(f"[ERROR] No debug screenshot found. Run test_vision_live.py first.")
        return

    hand_roi = cv2.imread(hand_path)
    h, w = hand_roi.shape[:2]
    gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY)

    # ── 更好的二值化 ──
    # 牌面白底黑字 → THRESH_BINARY_INV 让文字变白
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 垂直投影
    projection = np.sum(binary == 255, axis=0).astype(np.float32)
    kernel = max(3, w // 60)
    if kernel % 2 == 0:
        kernel += 1
    projection = cv2.GaussianBlur(projection, (kernel, 1), sigmaX=kernel / 2.0).flatten()

    # ── 找峰值, 过滤间距太近的 (去重) ──
    min_dist = w // 18
    min_height = projection.max() * 0.1

    candidates = []
    for i in range(1, len(projection) - 1):
        if projection[i] > projection[i - 1] and projection[i] >= projection[i + 1]:
            if projection[i] >= min_height:
                candidates.append((i, projection[i]))

    # 按高度降序, 贪心选峰值
    candidates.sort(key=lambda x: -x[1])
    peaks = []
    for idx, val in candidates:
        if not any(abs(idx - p) < min_dist for p in peaks):
            peaks.append(idx)
    peaks.sort()

    # 只取最强的 14 个
    if len(peaks) > 14:
        peak_vals = [(p, projection[p]) for p in peaks]
        peak_vals.sort(key=lambda x: -x[1])
        peaks = sorted([p for p, _ in peak_vals[:14]])

    print(f"[OK] Hand ROI: {w}x{h} → {len(peaks)} tiles (filtered)")

    if len(peaks) < 5:
        print("[ERROR] Too few tiles detected")
        return

    # ── 裁剪每张牌 ──
    tile_w_est = (peaks[-1] - peaks[0]) // max(len(peaks) - 1, 1)  # 平均间距
    half_w = max(10, tile_w_est // 2 - 4)

    crops = []
    for i, px in enumerate(peaks):
        x1 = max(0, px - half_w)
        x2 = min(w, px + half_w)
        y1 = 2
        y2 = max(3, h - 2)
        crop = hand_roi[y1:y2, x1:x2]
        if crop.size > 100:
            crops.append((px, crop))

    print(f"[OK] Cropped {len(crops)} tiles")

    # ── 按花色自动分组 → 推断 tile_id ──
    # 策略: 分析每张牌的中心区域颜色特征
    # 万子: 黑色数字+万字, 偏暗
    # 筒子: 红色圆圈图案
    # 索子: 绿色/蓝色条状
    # 字牌: 单个大字, 白/发/中 有特殊颜色

    labels = _auto_classify(crops)
    print(f"\n[Classify] Auto-detected suits:")
    for i, (px, crop) in enumerate(crops):
        tid = labels[i] if i < len(labels) else -1
        from vision.tiles import tile_to_name
        print(f"  [{i:2d}] tile_id={tid:2d} {tile_to_name(tid):5s} ({crop.shape[1]}x{crop.shape[0]}px)")

    # ── 保存模板 ──
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    # 备份旧的合成模板
    backup_dir = TEMPLATE_DIR + "_synthetic_backup"
    if not os.path.isdir(backup_dir):
        os.makedirs(backup_dir, exist_ok=True)
        for f in os.listdir(TEMPLATE_DIR):
            if f.endswith(".png") and f[0].isdigit():
                os.rename(os.path.join(TEMPLATE_DIR, f),
                         os.path.join(backup_dir, f))
        print(f"\n[Backup] Moved old synthetic templates to {backup_dir}")

    # 保存新模板 — 统一高度 48px
    TARGET_H = 48
    saved = 0
    for i, (px, crop) in enumerate(crops):
        tid = labels[i] if i < len(labels) else i
        h_c, w_c = crop.shape[:2]
        new_w = max(4, int(w_c * TARGET_H / h_c))
        resized = cv2.resize(crop, (new_w, TARGET_H))

        path = os.path.join(TEMPLATE_DIR, f"{tid}.png")
        cv2.imwrite(path, resized)

        from vision.tiles import tile_to_name
        print(f"  [save] {tid}.png = {tile_to_name(tid)} ({new_w}x{TARGET_H}px)")
        saved += 1

    print(f"\n[Done] Saved {saved} real templates → {TEMPLATE_DIR}")
    print(f"  Run test_vision_live.py again to test with real templates!")


def _auto_classify(crops):
    """
    根据雀魂自动理牌规则推断 tile_id。

    雀魂手牌排序: 万(0-8) → 筒(9-17) → 索(18-26) → 字(27-33)
    同花色内按数字升序。

    识别花色方法: 分析牌面中心区域的 RGB 颜色特征
    """
    import cv2
    import numpy as np

    n = len(crops)
    labels = [-1] * n

    if n == 0:
        return labels

    # 分析每张牌的颜色特征
    features = []
    for px, crop in crops:
        h, w = crop.shape[:2]
        # 只取中心区域 (避开边框)
        cy1, cy2 = h // 4, 3 * h // 4
        cx1, cx2 = w // 4, 3 * w // 4
        center = crop[cy1:cy2, cx1:cx2]

        # RGB 均值
        mean_rgb = center.mean(axis=(0, 1))  # BGR
        mean_b, mean_g, mean_r = mean_rgb

        # 颜色特征
        redness = mean_r - (mean_g + mean_b) / 2  # 越正越红 (筒子, 中)
        greenness = mean_g - (mean_r + mean_b) / 2  # 越正越绿 (發, 索子)
        darkness = 255 - (mean_r + mean_g + mean_b) / 3  # 越正越暗 (萬子黑字)

        features.append({
            'redness': redness, 'greenness': greenness,
            'darkness': darkness, 'mean_gray': center.mean(),
            'std': center.std(),
        })

    # ── 分组逻辑 ──
    # 万子: 纯黑字, 低 redness, 低 greenness, 高 darkness
    # 筒子: 红色圆点, 高 redness
    # 索子: 绿色/蓝色条纹, 中 greenness
    # 字牌: 大字, 低 std (大面积同色), 各色不同

    # 简化的分组: 按 redness 降序排列
    # 实际上雀魂已经排好序了, 从左到右就是 万→筒→索→字

    # 策略: 找到花色切换点
    # 万→筒切换: redness 突然升高
    # 筒→索切换: redness 降低, greenness 升高
    # 索→字切换: std 突然降低 (字牌大面积同色背景)

    # 对于 13-14 张牌的场景, 用简单的启发式:
    # 从左到右扫描, 用颜色特征变化找切换点

    # 简化为: 按位置比例分配
    # 前 ~40% 是万, 接着 ~30% 筒, ~20% 索, 最后是字
    # 这在实际牌局中大致准确

    # 更好的方式: 用 K-Means 聚类 (4 类: 万/筒/索/字)
    if n >= 6:
        from collections import Counter

        # 提取颜色特征向量
        X = np.array([[f['redness'], f['greenness'], f['darkness']] for f in features])

        # 用 K-Means 聚类为花色
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
        # 尝试 k=4 聚类
        k = min(4, n)
        _, labels_k, centers = cv2.kmeans(
            X.astype(np.float32), k, None, criteria, 10,
            cv2.KMEANS_RANDOM_CENTERS
        )
        labels_k = labels_k.flatten()

        # 按 redness 对聚类排序: 字<万<索<筒
        center_redness = centers[:, 0]
        cluster_order = np.argsort(center_redness)

        # 映射: redness最低=字牌/万子混合, 最高=筒子
        suit_map = {}
        for order_idx, cluster_id in enumerate(cluster_order):
            # 根据 redness 大小分配花色
            if order_idx == 0:
                suit_map[cluster_id] = 'x'  # 字牌或万子 (暗色)
            elif order_idx == k - 1:
                suit_map[cluster_id] = 'p'  # 筒子 (红色)
            elif k >= 3 and order_idx == k - 2:
                suit_map[cluster_id] = 's'  # 索子 (绿色)
            else:
                suit_map[cluster_id] = 'm'  # 万子

        # 按位置分段
        suit_order = []  # 从左到右的花色序列
        current_suit = None
        run_length = 0

        for i in range(n):
            cluster = labels_k[i]
            suit = suit_map.get(cluster, 'm')

            # 合并连续同花色
            if suit == current_suit:
                run_length += 1
            else:
                if current_suit is not None and run_length > 0:
                    suit_order.append((current_suit, i - run_length, i - 1))
                current_suit = suit
                run_length = 1
        if current_suit is not None and run_length > 0:
            suit_order.append((current_suit, n - run_length, n - 1))

        # ── 分配 tile_id ──
        # 花色内按数字升序 (从左到右 = 从小到大)
        suit_base = {'m': 0, 'p': 9, 's': 18, 'x': 27}
        suit_name = {'m': '万', 'p': '筒', 's': '索', 'x': '字'}

        print(f"  [Cluster] suits: {suit_order}")

        for suit, start_idx, end_idx in suit_order:
            count = end_idx - start_idx + 1
            base = suit_base.get(suit, 27)

            if suit == 'x':
                # 字牌: 按 position 直接映射
                # 东=27,南=28,西=29,北=30,白=31,發=32,中=33
                for j, i in enumerate(range(start_idx, end_idx + 1)):
                    if i < len(labels):
                        labels[i] = base + min(j, 6)
            else:
                # 数牌: 1-9
                for j, i in enumerate(range(start_idx, end_idx + 1)):
                    if i < len(labels):
                        labels[i] = base + min(j, 8)

    # 如果聚类失败 → 按位置均分
    if all(l == -1 for l in labels):
        # 简单启发式分配
        # 假设 13 张: 5万+3筒+3索+2字 (典型手牌分布)
        boundaries = _estimate_suit_boundaries(n)
        for i in range(n):
            for suit, (start, end) in boundaries.items():
                if start <= i <= end:
                    base = {'m': 0, 'p': 9, 's': 18, 'x': 27}[suit]
                    labels[i] = base + (i - start)
                    break

    return labels


def _estimate_suit_boundaries(n):
    """按典型手牌分布估算花色边界"""
    # 典型分布: 万 ≈ 40%, 筒 ≈ 25%, 索 ≈ 20%, 字 ≈ 15%
    n_man = max(1, int(n * 0.40))
    n_pin = max(1, int(n * 0.25))
    n_sou = max(1, int(n * 0.20))
    n_hon = n - n_man - n_pin - n_sou

    return {
        'm': (0, n_man - 1),
        'p': (n_man, n_man + n_pin - 1),
        's': (n_man + n_pin, n_man + n_pin + n_sou - 1),
        'x': (n_man + n_pin + n_sou, n - 1),
    }


if __name__ == "__main__":
    main()
