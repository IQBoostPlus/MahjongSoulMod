"""
自动模板采集器 — 边玩边收集深色主题牌面

运行: python scripts/auto_collect_templates.py

工作原理:
  1. 持续监控屏幕，找到雀魂窗口
  2. 每 1 秒检测手牌
  3. 对每张牌与现有模板库比对
  4. 匹配置信度 < 阈值 → 认为新牌种 → 自动保存
  5. 按 F8 手动触发采集当前手牌
  6. Ctrl+C 退出

输出: vision/templates/tiles/collected_*.png
      vision/templates/tiles/collected_log.json (记录每张牌被识别为什么)

后续: 人工查看 collected_*.png, 按牌种重命名为 tile_id.png
"""

import os
import sys
import time
import json
import signal
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles")
LOG_PATH = os.path.join(TEMPLATE_DIR, "collected_log.json")

# 采集阈值: 匹配置信度低于此值 → 认为模板库中没有 → 采集
COLLECT_THRESHOLD = 0.85
# 已知模板 tile_id 集合
KNOWN_TILES = set()


def load_known_tiles():
    """加载已有模板的 tile_id 列表"""
    global KNOWN_TILES
    KNOWN_TILES = set()
    for f in os.listdir(TEMPLATE_DIR):
        if f.endswith('.png') and f.split('.')[0].isdigit():
            KNOWN_TILES.add(int(f.split('.')[0]))
    print(f"[Init] Known templates: {sorted(KNOWN_TILES)} ({len(KNOWN_TILES)}/34)")


def find_game_window():
    """查找雀魂窗口 → (left, top, width, height) or None"""
    try:
        import pygetwindow as gw
    except ImportError:
        return None

    candidates = []
    for w in gw.getAllWindows():
        title = w.title or ""
        if any(kw in title for kw in ["雀魂", "MahjongSoul", "Mahjong Soul"]):
            skip = ["Visual Studio", "Code", "Terminal", "Claude", "AutoMod"]
            if any(kw in title for kw in skip):
                continue
            if w.visible and w.width > 600:
                candidates.append((w.width * w.height, w))
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        w = candidates[0][1]
        return (w.left, w.top, w.width, w.height)
    return None


def capture_frame():
    """截取全屏 → numpy BGR"""
    try:
        import pyautogui
        img = pyautogui.screenshot()
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def extract_hand_tiles(frame):
    """
    从全屏截图中提取手牌裁剪列表。

    返回: [(crop_image, x_center_screen), ...] or []
    """
    h, w = frame.shape[:2]
    # 手牌区域: 83-94% 高度, 8-92% 宽度 (全屏百分比)
    y1, y2 = int(h * 0.83), int(h * 0.94)
    x1, x2 = int(w * 0.08), int(w * 0.92)

    if y2 <= y1 or x2 <= x1:
        return []

    hand = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(hand, cv2.COLOR_BGR2GRAY)

    # 二值化 + 垂直投影
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    vp = np.sum(binary == 255, axis=0).astype(float)

    ks = max(7, hand.shape[1] // 60)
    if ks % 2 == 0:
        ks += 1
    vp = cv2.GaussianBlur(vp, (ks, 1), sigmaX=ks / 2.5).flatten()

    # 峰值检测
    min_dist = hand.shape[1] // 18
    peaks = []
    for i in range(1, len(vp) - 1):
        if vp[i] > vp[i - 1] and vp[i] >= vp[i + 1]:
            if vp[i] >= vp.max() * 0.06:
                if not peaks or i - peaks[-1] >= min_dist:
                    peaks.append(i)

    # 取最强的14个
    if len(peaks) > 14:
        pv = [(p, vp[p]) for p in peaks]
        pv.sort(key=lambda x: -x[1])
        peaks = sorted([p for p, _ in pv[:14]])

    # 裁剪
    half = 45
    crops = []
    for px in peaks:
        cx1 = max(0, px - half)
        cx2 = min(hand.shape[1], px + half)
        crop = hand[8:hand.shape[0] - 8, cx1:cx2]
        if crop.size > 100:
            screen_x = x1 + px
            crops.append((crop, screen_x))

    return crops


def match_against_templates(crop):
    """
    用 CCORR_NORMED 匹配所有已知模板。

    返回: (best_tile_id, confidence)
    """
    best_tid, best_val = -1, 0.0

    for tid in KNOWN_TILES:
        tp = os.path.join(TEMPLATE_DIR, f"{tid}.png")
        if not os.path.isfile(tp):
            continue
        tmpl = cv2.imread(tp)
        if tmpl is None:
            continue

        for scale in [0.5, 0.65, 0.8, 0.9, 1.0, 1.1, 1.3, 1.5]:
            sw = int(tmpl.shape[1] * scale)
            sh = int(tmpl.shape[0] * scale)
            if sw < 8 or sh < 8 or sw > crop.shape[1] or sh > crop.shape[0]:
                continue
            st = cv2.resize(tmpl, (sw, sh))
            try:
                r = cv2.matchTemplate(crop, st, cv2.TM_CCORR_NORMED)
                _, mv, _, _ = cv2.minMaxLoc(r)
                if mv > best_val:
                    best_val = mv
                    best_tid = tid
            except cv2.error:
                continue

    return best_tid, best_val


def save_collected(crop, tile_id_guess, confidence, log_entries):
    """保存采集到的牌面"""
    # 用内容哈希去重
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hh = hash(gray.tobytes())

    # 检查是否已采集过相似图片
    for existing_hash, _ in log_entries:
        if existing_hash == hh:
            return False

    # 保存
    fname = f"collected_{len(log_entries):04d}.png"
    path = os.path.join(TEMPLATE_DIR, fname)

    # 保持适当尺寸 (高100px)
    h_c, w_c = crop.shape[:2]
    new_h = 100
    new_w = max(8, int(w_c * new_h / h_c))
    resized = cv2.resize(crop, (new_w, new_h))
    cv2.imwrite(path, resized)

    log_entries.append((hh, fname, tile_id_guess, confidence))
    return True


def load_log():
    """加载采集日志"""
    if os.path.isfile(LOG_PATH):
        try:
            with open(LOG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []  # [(hash, fname, guessed_tile_id, confidence), ...]


def save_log(entries):
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def print_status(known_count, collected_count, last_hand, fps):
    """单行状态"""
    from vision.tiles import tiles_to_str
    hand_s = tiles_to_str(last_hand) if last_hand else "?"
    bar = "█" * min(20, known_count) + "░" * max(0, 20 - known_count)
    print(f"\r[{known_count}/34] {bar} | collected: {collected_count} | hand: {hand_s:40s} | {fps:.0f}fps", end="", flush=True)


def main():
    print("=" * 55)
    print("  雀魂自动模板采集器")
    print("  边玩边收集深色主题牌面")
    print("=" * 55)
    print()
    print("  F8 = 手动触发采集当前手牌")
    print("  Ctrl+C = 退出")
    print()

    load_known_tiles()
    log_entries = load_log()
    collected_count = len(log_entries)

    if collected_count > 0:
        print(f"[Log] {collected_count} previously collected tiles in {LOG_PATH}")

    if len(KNOWN_TILES) >= 34:
        print("[Done] All 34 tile types already known — nothing to collect!")
        return

    # 键盘监听 (F8)
    f8_pressed = [False]

    try:
        from pynput import keyboard

        def on_press(key):
            try:
                if key == keyboard.Key.f8:
                    f8_pressed[0] = True
            except Exception:
                pass

        listener = keyboard.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()
        print("[Hotkey] F8 监听已启动")
    except ImportError:
        print("[Hotkey] pynput 未安装 — F8 不可用 (pip install pynput)")

    # 统计
    frame_count = 0
    last_time = time.time()
    last_hand_ids = []
    last_save_time = 0
    save_cooldown = 2.0  # 同一手牌至少间隔2秒才再次采集

    print("\n[Loop] 开始监控... 打开雀魂进入对局即可\n")

    try:
        while True:
            frame_count += 1

            # 截帧
            frame = capture_frame()
            if frame is None:
                time.sleep(0.5)
                continue

            # 找窗口 (每10帧)
            # 不依赖窗口坐标，直接用全屏百分比

            # 提取手牌
            crops = extract_hand_tiles(frame)

            if not crops or len(crops) < 5:
                time.sleep(0.5)
                continue

            # 匹配每张牌
            hand_ids = []
            new_collected = False

            for crop, sx in crops:
                tid, conf = match_against_templates(crop)

                if tid >= 0:
                    hand_ids.append(tid)
                else:
                    hand_ids.append(-1)

                # 低置信度或未知 → 采集
                if conf < COLLECT_THRESHOLD or tid < 0:
                    now = time.time()
                    if now - last_save_time > save_cooldown:
                        if save_collected(crop, tid, conf, log_entries):
                            new_collected = True
                            last_save_time = now
                            collected_count += 1

            # F8 手动触发: 采集所有当前手牌
            if f8_pressed[0]:
                f8_pressed[0] = False
                for crop, sx in crops:
                    tid, conf = match_against_templates(crop)
                    if save_collected(crop, tid, conf, log_entries):
                        collected_count += 1
                        new_collected = True
                print(f"\n[F8] Captured current hand! Total collected: {collected_count}")

            # 保存日志
            if new_collected:
                save_log(log_entries)
                # 刷新已知模板
                new_tiles = set()
                for f in os.listdir(TEMPLATE_DIR):
                    if f.endswith('.png') and f.split('.')[0].isdigit():
                        new_tiles.add(int(f.split('.')[0]))
                newly_added = new_tiles - KNOWN_TILES
                if newly_added:
                    print(f"\n[New] Templates added: {sorted(newly_added)}")

            # 每秒输出状态
            now = time.time()
            if now - last_time >= 1.0:
                fps = frame_count / (now - last_time) if now > last_time else 0
                print_status(len(KNOWN_TILES), collected_count, hand_ids, fps)
                frame_count = 0
                last_time = now
                last_hand_ids = hand_ids

            # 检查是否集齐
            if len(KNOWN_TILES) >= 34:
                print("\n\n[Complete] All 34 tile types collected!")
                break

            time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n\n[Stop] Saving log...")
    finally:
        save_log(log_entries)
        print(f"[Done] Collected {collected_count} tiles total")
        print(f"  Templates: {TEMPLATE_DIR}/collected_*.png")
        print(f"  Log: {LOG_PATH}")
        print(f"  Known: {sorted(KNOWN_TILES)}")
        print()
        print("  下一步: 查看 collected_*.png → 按牌种重命名为 tile_id.png")
        print("  命名规则: 0-8=1m~9m  9-17=1p~9p  18-26=1s~9s  27-33=字")


if __name__ == "__main__":
    main()
