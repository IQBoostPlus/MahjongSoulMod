"""
Vision Pipeline 实机测试 — 对雀魂 Steam/浏览器 窗口进行识别

用法:
  1. 打开雀魂并进入对局 (或观战)
  2. python scripts/test_vision_live.py
  3. 查看输出和 saved debug 截图

测试内容:
  - 窗口查找
  - 帧采集
  - ROI 分割
  - 手牌识别
  - 牌河识别
  - 宝牌识别
  - 按钮检测
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "debug_output")


def main():
    import cv2
    import numpy as np

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("  雀魂 Vision Pipeline 实机测试")
    print("=" * 60)

    # ════════════════════════════════════════════════════════
    # 1. 窗口查找
    # ════════════════════════════════════════════════════════
    print("\n[1] 查找游戏窗口...")

    try:
        import pygetwindow as gw
    except ImportError:
        print("  ❌ pygetwindow 未安装: pip install pygetwindow")
        return

    game_win = None
    all_candidates = []

    for w in gw.getAllWindows():
        title = w.title or ""
        is_game = any(kw in title for kw in [
            "雀魂", "MahjongSoul", "Mahjong Soul",
            "mahjongsoul", "mahjong_soul", "Jansou", "Majsoul",
        ])

        skip_kw = ["Visual Studio", "Code", "Terminal", "终端",
                    "PowerShell", "cmd", "Claude", "Cursor",
                    "Sublime", "Notepad", "记事本", "AutoMod",
                    "修复", "MOD", "mod", "build", "Python"]
        is_tool = any(kw in title for kw in skip_kw)

        if is_game and not is_tool and w.visible and w.width > 600:
            all_candidates.append((w.width * w.height, w, title))

    if not all_candidates:
        print("  ❌ 未找到雀魂窗口!")
        print("  请确保雀魂已打开并在对局中")
        print(f"\n  当前所有可见窗口:")
        for w in sorted(gw.getAllWindows(), key=lambda x: -(x.width * x.height))[:10]:
            if w.title and w.visible:
                print(f"    '{w.title}' {w.width}x{w.height}")
        return

    # 选最大的
    all_candidates.sort(key=lambda x: -x[0])
    _, game_win, win_title = all_candidates[0]
    print(f"  ✅ 找到: '{win_title}' ({game_win.width}x{game_win.height} "
          f"@ {game_win.left},{game_win.top})")

    # 列出所有候选
    if len(all_candidates) > 1:
        print(f"  ⚠ 共找到 {len(all_candidates)} 个候选窗口:")
        for area, w, t in all_candidates:
            print(f"    - '{t}' {w.width}x{w.height}")

    # ════════════════════════════════════════════════════════
    # 2. 帧采集
    # ════════════════════════════════════════════════════════
    print("\n[2] 采集屏幕帧...")

    from vision.capture import CaptureConfig, CaptureBackend, CaptureFactory

    # 尝试 DXcam
    dxcam_ok = False
    try:
        config = CaptureConfig(backend=CaptureBackend.DXCAM, target_fps=10)
        capture = CaptureFactory.create(config)
        if hasattr(capture, '_camera') and capture._camera is not None:
            frame = capture.capture()
            if frame is not None:
                dxcam_ok = True
                print(f"  ✅ DXcam 采集成功: {frame.shape}")
    except Exception:
        pass

    if not dxcam_ok:
        # 回退到 PIL
        config = CaptureConfig(backend=CaptureBackend.PIL, target_fps=5)
        capture = CaptureFactory.create(config)
        frame = capture.capture()
        if frame is not None:
            print(f"  ✅ PIL 采集成功: {frame.shape}")
        else:
            print("  ❌ 所有采集方式均失败")
            return

    # 直接使用全屏截图 — ROI 坐标已经是全屏百分比
    # 不再依赖窗口裁剪 (DPI缩放导致窗口坐标不准)
    print(f"  ✅ 使用全屏截图: {frame.shape[1]}x{frame.shape[0]}")
    ww, wh = frame.shape[1], frame.shape[0]

    # 保存原始截图
    raw_path = os.path.join(OUTPUT_DIR, "01_raw_frame.png")
    cv2.imwrite(raw_path, frame)
    print(f"  📷 保存: {raw_path}")

    # ════════════════════════════════════════════════════════
    # 3. ROI 分割与识别
    # ════════════════════════════════════════════════════════
    print("\n[3] ROI 分割...")

    from vision.regions import RegionConfig, ROIDefinition
    from vision.tiles import TileRecognizer, tiles_to_str, tile_to_name
    from vision.buttons import ButtonDetector

    regions = RegionConfig.get_for_window(ww, wh)
    tile_rec = TileRecognizer(threshold=0.60)  # 降低阈值用于合成模板
    button_det = ButtonDetector()

    h, w = frame.shape[:2]

    # ── 手牌 ──
    hand_roi = regions.hand.crop(frame, w, h)
    cv2.imwrite(os.path.join(OUTPUT_DIR, "02_hand_roi.png"), hand_roi)
    hand_results = tile_rec.recognize_hand(hand_roi)

    print(f"\n  🀄 手牌 ({len(hand_results)} 张):")
    for i, (tid, conf) in enumerate(hand_results):
        name = tile_to_name(tid)
        bar = "█" * int(conf * 20) + "░" * (20 - int(conf * 20))
        print(f"    [{i:2d}] tile_id={tid:2d} {name:5s} conf={conf:.3f} {bar}")

    hand_ids = [tid for tid, _ in hand_results if tid >= 0]
    print(f"  识别结果: {tiles_to_str(hand_ids)}")

    # ── 牌河 (4家) ──
    river_seat_names = ["自家", "下家", "对家", "上家"]
    for seat in range(4):
        river_roi = regions.get_discard_rect(seat).crop(frame, w, h)
        cv2.imwrite(os.path.join(OUTPUT_DIR, f"03_river_seat{seat}.png"), river_roi)
        river_result = tile_rec.recognize_river(river_roi)
        flat = [t for row in river_result for t in row]
        if flat:
            print(f"  🀫 {river_seat_names[seat]}牌河 ({len(flat)} 枚): {tiles_to_str(flat)}")
        else:
            print(f"  🀫 {river_seat_names[seat]}牌河: (空)")

    # ── 宝牌 ──
    dora_roi = regions.dora.crop(frame, w, h)
    cv2.imwrite(os.path.join(OUTPUT_DIR, "04_dora_roi.png"), dora_roi)
    dora_tiles = tile_rec.recognize_dora(dora_roi)
    print(f"\n  🀽 宝牌指示牌: {tiles_to_str(dora_tiles) if dora_tiles else '(未识别)'}")

    # ── 按钮 ──
    btn_roi = regions.buttons.crop(frame, w, h)
    cv2.imwrite(os.path.join(OUTPUT_DIR, "05_button_roi.png"), btn_roi)
    visible_btns = button_det.detect_buttons(btn_roi)
    print(f"  🔘 可见按钮: {visible_btns if visible_btns else '(无)'}")

    # ════════════════════════════════════════════════════════
    # 4. 标注截图 (调试可视化)
    # ════════════════════════════════════════════════════════
    print("\n[4] 生成标注截图...")

    annotated = frame.copy()

    # 画手牌区域
    hx, hy, hw2, hh = regions.hand.to_xywh(w, h)
    cv2.rectangle(annotated, (hx, hy), (hx + hw2, hy + hh), (0, 255, 0), 2)
    cv2.putText(annotated, "HAND", (hx, hy - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    # 画牌河区域
    colors = [(0, 255, 255), (255, 0, 255), (255, 255, 0), (0, 165, 255)]
    for seat in range(4):
        r_rect = regions.get_discard_rect(seat)
        rx, ry, rw, rh = r_rect.to_xywh(w, h)
        cv2.rectangle(annotated, (rx, ry), (rx + rw, ry + rh), colors[seat], 2)
        cv2.putText(annotated, f"R{seat}", (rx, ry - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, colors[seat], 1)

    # 画宝牌区域
    dx, dy, dw, dh = regions.dora.to_xywh(w, h)
    cv2.rectangle(annotated, (dx, dy), (dx + dw, dy + dh), (0, 0, 255), 2)
    cv2.putText(annotated, "DORA", (dx, dy - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

    # 画按钮区域
    bx, by, bw, bh = regions.buttons.to_xywh(w, h)
    cv2.rectangle(annotated, (bx, by), (bx + bw, by + bh), (255, 128, 0), 2)
    cv2.putText(annotated, "BTNS", (bx, by - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 0), 1)

    # 画手牌分割线 (垂直投影的峰值)
    if hand_results:
        peaks = _find_tile_centers(hand_roi)
        for px in peaks:
            abs_x = hx + px
            cv2.line(annotated, (abs_x, hy), (abs_x, hy + hh), (0, 255, 0), 1)

    annotated_path = os.path.join(OUTPUT_DIR, "06_annotated.png")
    cv2.imwrite(annotated_path, annotated)
    print(f"  📷 标注截图: {annotated_path}")

    # ════════════════════════════════════════════════════════
    # 5. 总结报告
    # ════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("  测试报告")
    print("=" * 60)
    print(f"  窗口: {win_title} ({ww}x{wh})")
    print(f"  采集: {'DXcam' if dxcam_ok else 'PIL'}")
    print(f"  手牌: {len(hand_ids)} 张 → {tiles_to_str(hand_ids)}")
    print(f"  平均置信度: {sum(c for _, c in hand_results) / max(1, len(hand_results)):.3f}")

    if hand_results:
        high_conf = sum(1 for _, c in hand_results if c > 0.7)
        low_conf = sum(1 for _, c in hand_results if c < 0.5)
        print(f"  高置信(>0.7): {high_conf}/{len(hand_results)}")
        print(f"  低置信(<0.5): {low_conf}/{len(hand_results)}")
        if low_conf > len(hand_results) * 0.5:
            print(f"  ⚠ 多数牌置信度低 — 建议用 capture_real_templates.py 采集真实模板")

    print(f"  宝牌: {tiles_to_str(dora_tiles)}")
    print(f"  按钮: {visible_btns}")
    print(f"  所有调试截图: {OUTPUT_DIR}/")

    capture.stop()


def _find_tile_centers(hand_roi):
    """手牌区域找牌中心 x 坐标 (复用 tiles.py 的峰值检测)"""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY) if len(hand_roi.shape) == 3 else hand_roi
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, 15, 3)
    projection = np.sum(binary == 255, axis=0).astype(np.float32)
    w = binary.shape[1]
    kernel = max(3, w // 100)
    if kernel % 2 == 0:
        kernel += 1
    projection = cv2.GaussianBlur(projection, (kernel, 1), sigmaX=2.0).flatten()

    min_height = projection.max() * 0.15
    min_dist = w // 18
    peaks = []
    for i in range(1, len(projection) - 1):
        if projection[i] > projection[i-1] and projection[i] >= projection[i+1]:
            if projection[i] >= min_height:
                if not peaks or i - peaks[-1] >= min_dist:
                    peaks.append(i)
    return peaks


if __name__ == "__main__":
    main()
