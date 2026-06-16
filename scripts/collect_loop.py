"""
Continuous tile collector — watches game and accumulates unique tiles.

Captures a frame every 1s. When a new hand appears (13+ tiles detected),
extracts tiles, deduplicates via dhash, and saves new ones to tiles_live/.

Run while playing normally. Stop with Ctrl+C when 34 unique tiles collected.

Usage:
    python scripts/collect_loop.py
"""

import os, sys, time, json, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cv2, numpy as np
from collections import defaultdict

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles_live")
os.makedirs(OUT_DIR, exist_ok=True)

# --- Perceptual hash ---
def dhash(img_gray, size=8):
    resized = cv2.resize(img_gray, (size+1, size))
    diff = resized[:, 1:] > resized[:, :-1]
    h = 0
    for row in diff:
        for bit in row:
            h = (h << 1) | int(bit)
    return h

def hamming(a, b):
    return bin(a ^ b).count('1')

DEDUP = 8  # Hamming threshold for "same tile"

# --- Capture setup ---
from vision.capture import CaptureConfig, CaptureBackend, CaptureFactory
from vision.regions import RegionConfig
from vision.tiles import DEFAULT_TILE_W, DEFAULT_TILE_H

try:
    cfg = CaptureConfig(backend=CaptureBackend.DXCAM, target_fps=3)
    cap = CaptureFactory.create(cfg)
except:
    cfg = CaptureConfig(backend=CaptureBackend.PIL, target_fps=2)
    cap = CaptureFactory.create(cfg)

frame = cap.capture()
if frame is None:
    print("ERROR: Cannot capture. Is game open?")
    sys.exit(1)

h, w = frame.shape[:2]
regions = RegionConfig.get_for_window(w, h)

# --- Load existing live templates ---
existing = {}  # hash_val -> filename
manifest_path = os.path.join(OUT_DIR, "manifest.json")
if os.path.isfile(manifest_path):
    with open(manifest_path) as f:
        for entry in json.load(f):
            existing[entry["hash_val"]] = entry["filename"]

print(f"Screen: {w}x{h}")
print(f"Existing live templates: {len(existing)}")
print("Watching for new hands... (Ctrl+C to stop)")
print()

last_count = 0
stable = 0

try:
    while len(existing) < 34:
        frame = cap.capture()
        if frame is None:
            time.sleep(0.5)
            continue

        hand_roi = regions.hand.crop(frame, w, h)
        hh, hw_roi = hand_roi.shape[:2]

        # Tile detection
        gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY)
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY_INV, 15, 3)
        proj = np.sum(binary == 255, axis=0).astype(np.float32)
        ks = max(3, hw_roi//100)
        if ks%2==0: ks+=1
        proj = cv2.GaussianBlur(proj, (ks,1), sigmaX=2.0).flatten()

        min_dist = max(10, hw_roi//16)
        peaks = []
        mh = float(proj.max())*0.15
        for i in range(1, len(proj)-1):
            if proj[i] > proj[i-1] and proj[i] >= proj[i+1] and proj[i] >= mh:
                if not any(abs(i-p) < min_dist for p in peaks):
                    peaks.append(i)

        tile_count = len(peaks)

        # New hand detection
        if last_count < 5 and tile_count >= 13:
            stable += 1
            if stable >= 2:  # Confirmed new hand
                print(f"[NEW HAND] {tile_count} tiles")
                tmpl_aspect = DEFAULT_TILE_W / DEFAULT_TILE_H
                tw = max(20, int(hw_roi / 14 * 0.45))
                th = int(tw / tmpl_aspect)
                if th > hh: th = hh - 4; tw = int(th * tmpl_aspect)
                hw2, y_off = tw//2, max(0, (hh-th)//2)
                new_count = 0

                for px in peaks:
                    x1, x2 = max(0, px-hw2), min(hw_roi, px+hw2)
                    y1, y2 = y_off, min(hh, y_off+th)
                    crop = hand_roi[y1:y2, x1:x2]
                    if crop.size == 0: continue
                    hval = dhash(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))

                    # Dedup
                    is_new = True
                    for eh in existing:
                        if hamming(hval, eh) <= DEDUP:
                            is_new = False
                            break

                    if is_new:
                        fname = f"tile_{len(existing):03d}.png"
                        cv2.imwrite(os.path.join(OUT_DIR, fname), crop)
                        existing[hval] = fname
                        new_count += 1

                print(f"  -> {new_count} new, total {len(existing)}/34")
                if len(existing) >= 34:
                    print("[DONE] 34 tiles collected!")
                    break
                stable = 0
        elif tile_count < 5:
            stable = 0

        last_count = tile_count
        time.sleep(1.0)

except KeyboardInterrupt:
    print("\n[STOPPED]")

# Save manifest
manifest = [{"hash_val": h, "filename": f} for h, f in existing.items()]
with open(manifest_path, 'w') as f:
    json.dump(manifest, f, indent=2)

print(f"Total: {len(existing)} unique tiles in {OUT_DIR}/")
cap.stop()
