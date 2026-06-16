"""
OCR 牌面标注 — 用 PaddleOCR 读汉字来识别牌种

安装: pip install paddlepaddle paddleocr

如果 PaddleOCR 不可用, 回退到颜色 + 位置启发性
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "debug_output")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles")


def main():
    import cv2
    import numpy as np

    hand_path = os.path.join(INPUT_DIR, "02_hand_roi.png")
    if not os.path.isfile(hand_path):
        print("[ERROR] Run test_vision_live.py first")
        return

    hand_roi = cv2.imread(hand_path)
    h, w = hand_roi.shape[:2]
    gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY)

    # ── 峰值检测 (改进版) ──
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 只在有内容的行做投影
    h_proj = np.sum(binary == 255, axis=1).astype(np.float32)
    rows = np.where(h_proj > h_proj.max() * 0.05)[0]
    if len(rows) > 10:
        y1, y2 = rows[0], rows[-1]
    else:
        y1, y2 = 0, h

    strip = binary[y1:y2, :]
    v_proj = np.sum(strip == 255, axis=0).astype(np.float32)

    # 用较宽的平滑核
    ks = max(7, w // 50)
    if ks % 2 == 0:
        ks += 1
    v_smooth = cv2.GaussianBlur(v_proj, (ks, 1), sigmaX=ks / 2.5).flatten()

    # 动态 min_dist
    est_w = w / 14
    min_dist = int(est_w * 0.65)
    min_h = v_smooth.max() * 0.08

    peaks = []
    for i in range(1, len(v_smooth) - 1):
        if v_smooth[i] > v_smooth[i-1] and v_smooth[i] >= v_smooth[i+1]:
            if v_smooth[i] >= min_h:
                if not peaks or i - peaks[-1] >= min_dist:
                    peaks.append(i)

    # 自适应: 最可能的牌数是 13 或 14
    # 如果峰值太多 → 取最强的 14 个
    if len(peaks) > 14:
        peak_vals = [(p, v_smooth[p]) for p in peaks]
        peak_vals.sort(key=lambda x: -x[1])
        peaks = sorted([p for p, _ in peak_vals[:14]])
    elif len(peaks) < 10:
        # 太少 → 降低阈值重来
        min_h = v_smooth.max() * 0.03
        min_dist = int(est_w * 0.45)
        peaks = []
        for i in range(1, len(v_smooth) - 1):
            if v_smooth[i] > v_smooth[i-1] and v_smooth[i] >= v_smooth[i+1]:
                if v_smooth[i] >= min_h:
                    if not peaks or i - peaks[-1] >= min_dist:
                        peaks.append(i)

    print(f"[Peaks] {len(peaks)} found")
    for i, p in enumerate(peaks):
        print(f"  peak[{i:2d}] @ x={p:4d} val={v_smooth[p]:.0f}")

    # ── 裁剪 ──
    half_w = max(15, int(est_w * 0.55))
    crops = []
    for px in peaks:
        x1 = max(0, px - half_w)
        x2 = min(w, px + half_w)
        crop = hand_roi[y1:y2, x1:x2]
        if crop.size > 200 and crop.shape[1] > 8:
            crops.append((px, crop))

    n = len(crops)
    print(f"\n[Crops] {n} valid tiles")

    # ── OCR 识别每张牌 ──
    print(f"\n[OCR] Reading tile characters...")
    results = []
    for i, (px, crop) in enumerate(crops):
        text = ocr_tile(crop)
        tid = text_to_tile_id(text)
        from vision.tiles import tile_to_name
        print(f"  [{i:2d}] OCR='{text}' → tile_id={tid} ({tile_to_name(tid)})")
        results.append((tid, crop, text))

    # ── 用 Majsoul 自动理牌验证 ──
    # 雀魂的牌是从左到右按 万→筒→索→字 排序的
    # 所以 tile_ids 应该非递减
    ids_only = [r[0] for r in results]
    expect_sorted = all(ids_only[i] <= ids_only[i+1]
                        for i in range(len(ids_only) - 1)
                        if ids_only[i] >= 0 and ids_only[i+1] >= 0)

    if not expect_sorted:
        print(f"\n[WARN] Tile IDs not sorted! Possible OCR errors.")
        print(f"  IDs: {ids_only}")
        print(f"  Majsoul auto-sorts → ids should be non-decreasing")
        # 尝试修正: 强制排序
        corrected = sorted(ids_only)
        print(f"  Corrected: {corrected}")
        for i in range(len(results)):
            results[i] = (corrected[i], results[i][1], results[i][2])

    # ── 保存模板 ──
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    TARGET_H = 48
    saved = {}

    for i, (tid, crop, text) in enumerate(results):
        if tid < 0 or tid > 36:
            continue
        if tid in saved:
            # 同一 tile_id 出现多次: 保留更大更清晰的
            continue

        h_c, w_c = crop.shape[:2]
        new_w = max(6, int(w_c * TARGET_H / h_c))
        resized = cv2.resize(crop, (new_w, TARGET_H))

        path = os.path.join(TEMPLATE_DIR, f"{tid}.png")
        cv2.imwrite(path, resized)
        saved[tid] = crop

        from vision.tiles import tile_to_name
        print(f"  [save] {tid}.png = {tile_to_name(tid)} ({new_w}x{TARGET_H}px)")

    print(f"\n[Done] Saved {len(saved)} unique templates")
    print(f"  Missing tiles: {sorted(set(range(34)) - set(saved.keys()))[:20]}...")


# ═══════════════════════════════════════════════════════════
#  OCR
# ═══════════════════════════════════════════════════════════

_paddle = None

def ocr_tile(crop):
    """用 PaddleOCR 读取牌面文字"""
    global _paddle

    # Try PaddleOCR first
    if _paddle is None:
        try:
            from paddleocr import PaddleOCR
            _paddle = PaddleOCR(lang='ch', show_log=False, use_angle_cls=False)
        except ImportError:
            _paddle = False  # Mark as unavailable

    if _paddle:
        try:
            result = _paddle.ocr(crop, cls=False)
            if result and result[0]:
                texts = [line[1][0] for line in result[0]]
                return ''.join(texts)
        except Exception:
            pass

    # Fallback: simple color/position heuristic
    return ocr_fallback(crop)


def ocr_fallback(crop):
    """无 PaddleOCR 时的回退识别 (用颜色+区域特征)"""
    import cv2
    import numpy as np

    h, w = crop.shape[:2]
    center = crop[h//4:3*h//4, w//4:3*w//4]

    # RGB 分析
    mean_bgr = center.mean(axis=(0, 1))
    b, g, r = mean_bgr[0], mean_bgr[1], mean_bgr[2]
    bright = center.mean()

    # 白板
    if bright > 210:
        return "白"

    # 红 → 中 or 筒
    if r > g + 15 and r > b + 15:
        if bright < 150:
            return "中"
        return "筒"

    # 绿 → 發 or 索
    if g > r + 8 and g > b + 8:
        if bright < 150:
            return "發"
        return "索"

    # 暗色 → 万 or 字牌(东南西北)
    # 万有数字+万, 字牌只有一个大字
    gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edge_ratio = edges.sum() / edges.size

    if edge_ratio > 0.06:
        return "万"  # 复杂笔画 = 数字+万
    else:
        # 大字牌: 东/南/西/北 (无法区分)
        return "東"


def text_to_tile_id(text):
    """OCR 文字 → tile_id"""
    text = text.strip()

    # 直接映射
    tile_map = {
        # 万子
        "一万": 0, "一萬": 0, "1万": 0, "1萬": 0,
        "二万": 1, "二萬": 1, "2万": 1, "2萬": 1,
        "三万": 2, "三萬": 2, "3万": 2, "3萬": 2,
        "四万": 3, "四萬": 3, "4万": 3, "4萬": 3,
        "五万": 4, "五萬": 4, "5万": 4, "5萬": 4,
        "六万": 5, "六萬": 5, "6万": 5, "6萬": 5,
        "七万": 6, "七萬": 6, "7万": 6, "7萬": 6,
        "八万": 7, "八萬": 7, "8万": 7, "8萬": 7,
        "九万": 8, "九萬": 8, "9万": 8, "9萬": 8,
        # 筒子
        "一筒": 9, "1筒": 9, "①": 9,
        "二筒": 10, "2筒": 10,
        "三筒": 11, "3筒": 11,
        "四筒": 12, "4筒": 12,
        "五筒": 13, "5筒": 13,
        "六筒": 14, "6筒": 14,
        "七筒": 15, "7筒": 15,
        "八筒": 16, "8筒": 16,
        "九筒": 17, "9筒": 17,
        # 索子
        "一索": 18, "1索": 18,
        "二索": 19, "2索": 19,
        "三索": 20, "3索": 20,
        "四索": 21, "4索": 21,
        "五索": 22, "5索": 22,
        "六索": 23, "6索": 23,
        "七索": 24, "7索": 24,
        "八索": 25, "8索": 25,
        "九索": 26, "9索": 26,
        # 字牌
        "東": 27, "东": 27,
        "南": 28,
        "西": 29,
        "北": 30,
        "白": 31,
        "發": 32, "发": 32,
        "中": 33,
    }

    if text in tile_map:
        return tile_map[text]

    # 模糊匹配: 如果 text 包含牌名
    for key, val in tile_map.items():
        if len(key) >= 2 and key in text:
            return val

    # 仅花色信息 — 无法确定具体数字
    if "万" in text or "萬" in text:
        return 0  # 回退为 1m
    if "筒" in text:
        return 9  # 回退为 1p
    if "索" in text:
        return 18  # 回退为 1s

    return -1


if __name__ == "__main__":
    main()
