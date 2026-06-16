"""
Live template capture — extracts tile images from running game

Usage while game is open and in a match:
    python scripts/capture_live_templates.py

Press Enter to capture the current hand tiles.
Press Ctrl+C to stop and save collected templates.
"""

import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles_live")


def find_peaks(signal, min_distance=10, min_height=None):
    """1D peak detection"""
    n = len(signal)
    if n < 3:
        return []
    if min_height is None:
        min_height = signal.max() * 0.15
    candidates = []
    for i in range(1, n - 1):
        if signal[i] > signal[i-1] and signal[i] >= signal[i+1]:
            if signal[i] >= min_height:
                candidates.append((i, signal[i]))
    candidates.sort(key=lambda x: -x[1])
    selected = []
    for idx, _ in candidates:
        if not any(abs(idx - s) < min_distance for s in selected):
            selected.append(idx)
    return sorted(selected)


def extract_tiles(hand_roi):
    """Extract individual tile images from hand ROI"""
    h, w = hand_roi.shape[:2]
    gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY)

    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, 15, 3)
    projection = np.sum(binary == 255, axis=0).astype(np.float32)
    ks = max(3, w // 100)
    if ks % 2 == 0:
        ks += 1
    projection = cv2.GaussianBlur(projection, (ks, 1), sigmaX=2.0).flatten()

    peaks = find_peaks(projection, min_distance=w // 16)

    tiles = []
    tile_h = int(h * 0.80)
    tile_w = int(w / 14 * 0.50)
    half_w = tile_w // 2
    y1 = int(h * 0.10)
    y2 = y1 + tile_h

    for px in peaks:
        x1 = max(0, px - half_w)
        x2 = min(w, px + half_w)
        crop = hand_roi[y1:y2, x1:x2]
        if crop.size > 0:
            tiles.append(crop)
    return tiles


def classify_tile(tile_img):
    """Color-based suit classification"""
    h, w = tile_img.shape[:2]
    b, g, r = cv2.split(tile_img)

    # Check upper 40% of tile where suit indicator/number is
    upper_h = int(h * 0.4)
    r_up = r[:upper_h, :]
    g_up = g[:upper_h, :]
    b_up = b[:upper_h, :]

    r_mean, g_mean, b_mean = np.mean(r_up), np.mean(g_up), np.mean(b_up)

    # Red pixel ratio
    red = np.sum((r.astype(int) - g.astype(int) > 25) &
                 (r.astype(int) - b.astype(int) > 25)) / (h * w)
    blue = np.sum((b.astype(int) - r.astype(int) > 20) &
                  (b.astype(int) - g.astype(int) > 20)) / (h * w)
    green = np.sum((g.astype(int) - r.astype(int) > 20) &
                   (g.astype(int) - b.astype(int) > 20)) / (h * w)

    # Std dev - low std = honor/blank tiles
    gray_std = np.std(cv2.cvtColor(tile_img, cv2.COLOR_BGR2GRAY))

    if red > 0.03:
        return "man"
    elif blue > 0.03:
        return "pin"
    elif green > 0.03:
        return "sou"
    elif gray_std < 35:
        return "honor_blank"
    else:
        return "honor"


def main():
    from vision.capture import CaptureConfig, CaptureBackend, CaptureFactory
    from vision.regions import RegionConfig

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("  Live Template Capture")
    print("=" * 60)
    print(f"  Output: {OUTPUT_DIR}")
    print("  Press ENTER to capture current hand")
    print("  Press Ctrl+C to stop")
    print()

    # Setup capture
    try:
        config = CaptureConfig(backend=CaptureBackend.DXCAM, target_fps=5)
        capture = CaptureFactory.create(config)
    except Exception:
        config = CaptureConfig(backend=CaptureBackend.PIL, target_fps=3)
        capture = CaptureFactory.create(config)

    frame = capture.capture()
    if frame is None:
        print("ERROR: Cannot capture screen")
        return

    h, w = frame.shape[:2]
    print(f"Screen: {w}x{h}")

    regions = RegionConfig.get_for_window(w, h)
    total_captured = 0
    captured_suits = {"man": 0, "pin": 0, "sou": 0, "honor": 0, "honor_blank": 0}

    try:
        while True:
            input(">>> Press ENTER to capture...")

            frame = capture.capture()
            if frame is None:
                print("  Capture failed")
                continue

            hand_roi = regions.hand.crop(frame, w, h)
            tiles = extract_tiles(hand_roi)

            print(f"  Found {len(tiles)} tiles")

            for i, tile in enumerate(tiles):
                suit = classify_tile(tile)

                # Save with suit prefix
                count = captured_suits[suit]
                filename = f"{suit}_{count:03d}.png"
                path = os.path.join(OUTPUT_DIR, filename)
                cv2.imwrite(path, tile)

                captured_suits[suit] += 1
                total_captured += 1

                # Show preview info
                mean_val = np.mean(cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY))
                print(f"    [{i}] {filename} suit={suit} mean={mean_val:.0f}")

            print(f"  Total captured: {total_captured}")
            print()

    except KeyboardInterrupt:
        print(f"\n\nDone. Captured {total_captured} tiles to {OUTPUT_DIR}")
        print(f"  man: {captured_suits['man']}")
        print(f"  pin: {captured_suits['pin']}")
        print(f"  sou: {captured_suits['sou']}")
        print(f"  honor: {captured_suits['honor']}")
        print(f"  honor_blank: {captured_suits['honor_blank']}")
        print()
        print("Next step: manually label tiles (rename file to tile_id.png)")
        print("  man_000.png -> 0.png (if it's 1m)")
        print("  or run: python scripts/smart_label_tiles.py")

    capture.stop()


if __name__ == "__main__":
    main()
