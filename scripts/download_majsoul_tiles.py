"""
从 majsoul-generator 下载真实雀魂牌面模板

来源: GitHub vg-mjg/majsoul-generator/ui/
文件命名: 1m-9m(万), 1p-9p(筒), 1s-9s(索), 1z-7z(字), 0m/0p/0s(赤)

映射到我们的 tile_id (0-36):
  0-8   = 1m-9m
  9-17  = 1p-9p
  18-26 = 1s-9s
  27-33 = 1z-7z (東南西北白發中)
  34-36 = 0m/0p/0s (赤宝牌)

运行: python scripts/download_majsoul_tiles.py
"""

import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 远程文件 → tile_id 映射
# majsoul-generator 的命名: 1m-9m, 1p-9p, 1s-9s, 1z-7z, 0m/0p/0s
TILE_MAP = {}

# 万子 (1m-9m) → tile_id 0-8
for n in range(1, 10):
    TILE_MAP[f"{n}m.png"] = n - 1

# 筒子 (1p-9p) → tile_id 9-17
for n in range(1, 10):
    TILE_MAP[f"{n}p.png"] = 8 + n

# 索子 (1s-9s) → tile_id 18-26
for n in range(1, 10):
    TILE_MAP[f"{n}s.png"] = 17 + n

# 字牌 (1z-7z) → tile_id 27-33
# 1z=東, 2z=南, 3z=西, 4z=北, 5z=白, 6z=發, 7z=中
for n in range(1, 8):
    TILE_MAP[f"{n}z.png"] = 26 + n

# 赤宝牌 → tile_id 34-36
TILE_MAP["0m.png"] = 34
TILE_MAP["0p.png"] = 35
TILE_MAP["0s.png"] = 36

BASE_URL = "https://raw.githubusercontent.com/vg-mjg/majsoul-generator/master/ui"
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles")


def download_all():
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    downloaded = 0
    failed = 0

    for filename, tile_id in sorted(TILE_MAP.items(), key=lambda x: x[1]):
        url = f"{BASE_URL}/{filename}"
        dest = os.path.join(TEMPLATE_DIR, f"{tile_id}.png")

        from vision.tiles import TILE_NAMES
        tile_name = TILE_NAMES[tile_id] if 0 <= tile_id < len(TILE_NAMES) else f"t{tile_id}"

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()

            with open(dest, "wb") as f:
                f.write(data)

            size_kb = len(data) / 1024
            print(f"  [{tile_id:2d}] {tile_name:5s} ← {filename:8s} ({size_kb:.1f} KB)")
            downloaded += 1

        except Exception as e:
            print(f"  [{tile_id:2d}] {tile_name:5s} ← {filename:8s} FAILED: {e}")
            failed += 1

    print(f"\n[Done] Downloaded {downloaded} templates ({failed} failed)")
    print(f"  Output: {TEMPLATE_DIR}")

    if failed == 0:
        print(f"  ✅ All 37 tiles ready! Run: python scripts/test_vision_live.py")


if __name__ == "__main__":
    download_all()
