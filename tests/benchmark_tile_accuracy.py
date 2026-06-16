"""
Benchmark: tile recognition accuracy v2.2 vs v2.3

Simulates dark theme by inverting all templates (255 - gray), adding noise.
Tests both old (CCORR_NORMED, no inversion) and new (CCOEFF_NORMED, auto-invert)
algorithms against the same dark test set.

Usage:
    python tests/benchmark_tile_accuracy.py
"""

import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def benchmark():
    import cv2
    from vision.tiles import (
        TileTemplateMatcher, TILE_NAMES, TOTAL_TEMPLATES, tile_to_name, RED_DORA_MAP
    )

    print("=" * 65)
    print("  Tile Recognition Benchmark: v2.2 vs v2.3")
    print("=" * 65)

    # --- Generate dark theme test set ---
    print("\n[1] Generating dark-theme test set...")

    template_dir = os.path.join(
        os.path.dirname(__file__), "..", "vision", "templates", "tiles"
    )

    dark_test_set = {}
    for tile_id in range(TOTAL_TEMPLATES):
        path = os.path.join(template_dir, f"{tile_id}.png")
        if not os.path.isfile(path):
            continue
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue

        # Simulate dark theme: invert + light Gaussian noise (screenshot compression)
        dark = cv2.bitwise_not(img)
        noise = np.random.normal(0, 3, dark.shape).astype(np.int16)
        dark = np.clip(dark.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        dark_test_set[tile_id] = dark

    print(f"  [OK] Generated {len(dark_test_set)} dark-theme test samples")

    # --- v2.2 old algorithm (simulated) ---
    print("\n[2] v2.2 OLD: CCORR_NORMED, no invert, edge 1.2x...")

    matcher_old = TileTemplateMatcher(
        invert_dark=False, margin_threshold=0.0, threshold=0.01
    )
    t0 = time.perf_counter()
    old_correct = 0
    old_total = 0
    old_red_correct = 0
    old_red_total = 0
    old_conf_sum = 0.0
    old_errors = []

    for tile_id, dark_roi in dark_test_set.items():
        gray = dark_roi
        h, w = gray.shape
        roi_edges = cv2.Canny(gray, 30, 90)

        best_id, best_conf = -1, 0.0
        method = cv2.TM_CCORR_NORMED

        for tid, tmpl in matcher_old._templates.items():
            th, tw = tmpl.shape
            if max(h / max(1, th), th / max(1, h)) > 2.5:
                continue
            for scale in matcher_old._scales:
                sw, sh = int(tw * scale), int(th * scale)
                if sw < 4 or sh < 4 or sw > w or sh > h:
                    continue
                try:
                    # Edge match (old weight 1.2)
                    if tid in matcher_old._edge_templates:
                        et = cv2.resize(matcher_old._edge_templates[tid], (sw, sh))
                        _, mv, _, _ = cv2.minMaxLoc(cv2.matchTemplate(roi_edges, et, method))
                        if float(mv) * 1.2 > best_conf:
                            best_conf = float(mv) * 1.2
                            best_id = tid
                    # Pixel match
                    st = cv2.resize(tmpl, (sw, sh))
                    _, mv, _, _ = cv2.minMaxLoc(cv2.matchTemplate(gray, st, method))
                    if float(mv) > best_conf:
                        best_conf = float(mv)
                        best_id = tid
                except cv2.error:
                    continue

        old_total += 1
        old_conf_sum += best_conf

        if tile_id in RED_DORA_MAP:
            old_red_total += 1
            if best_id == tile_id or best_id == RED_DORA_MAP[tile_id]:
                old_red_correct += 1

        if best_id == tile_id:
            old_correct += 1
        else:
            old_errors.append((tile_id, best_id, best_conf))

    old_time = time.perf_counter() - t0
    old_acc = old_correct / old_total * 100 if old_total else 0
    old_red_acc = old_red_correct / old_red_total * 100 if old_red_total else 0

    print(f"  Accuracy: {old_correct}/{old_total} = {old_acc:.1f}%")
    print(f"  Red dora accuracy: {old_red_correct}/{old_red_total} = {old_red_acc:.1f}%")
    print(f"  Avg confidence: {old_conf_sum/old_total:.3f}")
    print(f"  Time: {old_time:.2f}s")

    # --- v2.3 new algorithm ---
    print("\n[3] v2.3 NEW: CCOEFF_NORMED, auto-invert, edge 0.95x, margin 0.05...")

    matcher_new = TileTemplateMatcher(
        invert_dark=True, margin_threshold=0.05, threshold=0.01
    )

    t0 = time.perf_counter()
    new_correct = 0
    new_total = 0
    new_uncertain = 0
    new_red_correct = 0
    new_red_total = 0
    new_conf_sum = 0.0
    new_errors = []

    for tile_id, dark_roi in dark_test_set.items():
        best_id, best_conf = matcher_new.match_single(dark_roi)
        new_total += 1

        if tile_id in RED_DORA_MAP:
            new_red_total += 1
            if best_id == tile_id or best_id == RED_DORA_MAP[tile_id]:
                new_red_correct += 1

        if best_id == tile_id:
            new_correct += 1
        elif best_id == -1:
            new_uncertain += 1
        else:
            new_errors.append((tile_id, best_id, best_conf))

        if best_conf > 0:
            new_conf_sum += best_conf

    new_time = time.perf_counter() - t0
    new_acc = new_correct / new_total * 100 if new_total else 0
    new_red_acc = new_red_correct / new_red_total * 100 if new_red_total else 0

    print(f"  Accuracy: {new_correct}/{new_total} = {new_acc:.1f}%")
    print(f"  Uncertain (margin < 0.05): {new_uncertain}/{new_total}")
    print(f"  Red dora accuracy: {new_red_correct}/{new_red_total} = {new_red_acc:.1f}%")
    print(f"  Avg confidence: {new_conf_sum/new_total:.3f}")
    print(f"  Time: {new_time:.2f}s")

    # --- Comparison report ---
    print("\n" + "=" * 65)
    print("  Comparison Report")
    print("=" * 65)
    print(f"  {'Metric':<28} {'v2.2 (old)':>12} {'v2.3 (new)':>12} {'Delta':>10}")
    print(f"  {'-'*28} {'-'*12} {'-'*12} {'-'*10}")
    print(f"  {'Top-1 Accuracy':<28} {old_acc:>11.1f}% {new_acc:>11.1f}% {new_acc-old_acc:>+9.1f}%")
    print(f"  {'Red Dora Accuracy':<28} {old_red_acc:>11.1f}% {new_red_acc:>11.1f}% {new_red_acc-old_red_acc:>+9.1f}%")
    print(f"  {'Uncertain Rate (safe reject)':<28} {'N/A':>12} {new_uncertain/new_total*100:>11.1f}% {'--':>10}")

    if old_errors:
        print(f"\n  v2.2 errors ({len(old_errors)}):")
        for tid, got, conf in old_errors[:8]:
            print(f"    tile {tid:2d} ({tile_to_name(tid):5s}) -> misidentified as {got:2d} ({tile_to_name(got):5s}) conf={conf:.3f}")

    if new_errors:
        print(f"\n  v2.3 errors ({len(new_errors)}):")
        for tid, got, conf in new_errors[:8]:
            print(f"    tile {tid:2d} ({tile_to_name(tid):5s}) -> misidentified as {got:2d} ({tile_to_name(got):5s}) conf={conf:.3f}")

    if not new_errors and not old_errors:
        print("\n  [OK] Both algorithms had zero errors")

    # --- Light theme compatibility ---
    print("\n[4] Light-theme compatibility (template self-match)...")
    light_ok = 0
    for tile_id, tmpl in matcher_new._templates.items():
        tid, conf = matcher_new.match_single(tmpl)
        if tid == tile_id:
            light_ok += 1
    light_acc = light_ok / len(matcher_new._templates) * 100
    print(f"  Light accuracy: {light_ok}/{len(matcher_new._templates)} = {light_acc:.1f}%")

    print("\n" + "=" * 65)
    if new_acc >= 90:
        print("  [PASS] P0 fix successful -- dark-theme accuracy > 90%")
    elif new_acc >= 70:
        print("  [WARN] Significant improvement but needs optimization")
        print("         Consider collecting real dark-theme templates")
    else:
        print("  [FAIL] Algorithm fix insufficient -- need ONNX model or real templates")
    print("=" * 65)

    return new_acc


if __name__ == "__main__":
    benchmark()
