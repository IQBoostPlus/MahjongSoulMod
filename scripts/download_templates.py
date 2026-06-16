"""
下载雀魂牌面数据集并生成模板图片

从 Hugging Face 下载 pjura/mahjong_souls_tiles,
对每类选最佳代表图, 保存为 vision/templates/tiles/{id}.png

牌类映射: 需要根据数据集实际标签确定,
预映射 (待验证):
  0-8   = 万子 man (1m-9m)
  9-17  = 筒子 pin (1p-9p)
  18-26 = 索子 sou (1s-9s)
  27-33 = 字牌 honors (东E,南S,西W,北N,白P,发F,中C)
  34-36 = 赤宝牌 (r5m, r5p, r5s) — 可能不在数据集中

运行: python scripts/download_templates.py
"""

import os
import sys
import hashlib
import time

# 确保项目在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "templates", "tiles")
DATASET_NAME = "pjura/mahjong_souls_tiles"

# 雀魂牌类标签名 (与数据集 ImageFolder 类名对应)
# 数据集使用常见的日麻牌名格式
EXPECTED_CLASSES = [
    # 万子 (0-8)
    "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
    # 筒子 (9-17)
    "1p", "2p", "3p", "4p", "5p", "5pr", "6p", "7p", "8p", "9p",
    # 索子 (18-26)
    "1s", "2s", "3s", "4s", "5s", "5sr", "6s", "7s", "8s", "9s",
    # 字牌 (27-33)
    "1z", "2z", "3z", "4z", "5z", "6z", "7z",
]

# 对应我们的 tile_id (0-33), 赤宝牌暂用普通牌替代
CLASS_TO_TILE_ID = {}
_tile_idx = 0
for group in [
    range(0, 9),   # 万
    range(9, 18),  # 筒 (含赤5筒 "5pr")
    range(18, 27), # 索 (含赤5索 "5sr")
    range(27, 34), # 字
]:
    for idx in group:
        if _tile_idx < len(EXPECTED_CLASSES):
            CLASS_TO_TILE_ID[EXPECTED_CLASSES[_tile_idx]] = idx
            _tile_idx += 1

# 赤宝牌特殊映射
RED_DORA_MAP = {
    "5pr": 35,  # 赤5筒
    "5sr": 36,  # 赤5索
    "0m": 34,   # 赤5万
    "0p": 35,   # 赤5筒
    "0s": 36,   # 赤5索
}


def download_and_extract():
    """下载数据集并提取模板"""

    print(f"[Download] Fetching dataset: {DATASET_NAME}")
    print(f"[Download] This may take a few minutes...")

    try:
        from datasets import load_dataset
    except ImportError:
        print("[ERROR] Please install: pip install datasets")
        return

    # 尝试加载数据集 (自动缓存到 ~/.cache/huggingface/)
    try:
        dataset = load_dataset(DATASET_NAME, split="train")
        print(f"[Download] Loaded {len(dataset)} images")
        print(f"[Download] Features: {dataset.features}")
    except Exception as e:
        print(f"[ERROR] Failed to load dataset: {e}")
        print("[TIP] Try: huggingface-cli download pjura/mahjong_souls_tiles")
        return

    # 探索数据集结构
    print("\n[Explore] Dataset structure:")
    print(f"  Columns: {dataset.column_names}")
    print(f"  Sample: {dataset[0]}")

    # 找出所有唯一类别
    if "label" in dataset.features:
        labels = dataset.features["label"]
        if hasattr(labels, 'names'):
            class_names = labels.names
            print(f"\n[Explore] Class names ({len(class_names)}):")
            for i, name in enumerate(class_names):
                print(f"  {i}: {name}")
            print()
    else:
        print("[WARN] No 'label' feature found, trying 'image' only")
        class_names = None

    # 如果数据集的类名映射已知，用它
    if class_names:
        # 按类分组, 每类选一张最清晰的图
        os.makedirs(TEMPLATE_DIR, exist_ok=True)

        print("[Extract] Selecting best images per class...")
        selected = {}
        for item in dataset:
            label = item["label"] if isinstance(item["label"], int) else int(item["label"])
            if label not in selected:
                selected[label] = item

        print(f"[Extract] Found {len(selected)} classes")

        # 映射到我们的 tile_id
        tile_mapping = _build_tile_mapping(class_names)

        extracted = 0
        for label_idx, item in sorted(selected.items()):
            tile_id = tile_mapping.get(label_idx, label_idx)
            img = item["image"]

            # 处理 RGBA → RGB
            if img.mode == "RGBA":
                # 创建白色背景
                from PIL import Image
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # 调整大小为标准模板 (高度 48px, 保持宽高比)
            h_target = 48
            w_orig, h_orig = img.size
            w_target = int(w_orig * h_target / h_orig)
            img = img.resize((w_target, h_target))

            # 保存
            path = os.path.join(TEMPLATE_DIR, f"{tile_id}.png")
            img.save(path)

            class_name = class_names[label_idx] if label_idx < len(class_names) else f"cls_{label_idx}"
            print(f"  [{extracted:2d}] class='{class_name}' → tile_id={tile_id} ({w_target}x{h_target}px)")
            extracted += 1

        print(f"\n[Done] Saved {extracted} templates to {TEMPLATE_DIR}")

    else:
        # 无标签: 尝试通过文件名推理
        _extract_from_filenames(dataset)


def _build_tile_mapping(class_names: list) -> dict:
    """
    构建 数据集label索引 → 我们的tile_id 的映射。

    数据集类名格式推测:
      - "man1", "man2", ... "man9"
      - "pin1", ... "pin9"
      - "sou1", ... "sou9"
      - "east", "south", "west", "north", "white", "green", "red"

    或简写: "1m", "2m", ... "1p", ... "1s", ... "E", "S", ...

    返回: {label_idx: tile_id_0_to_36}
    """
    mapping = {}

    # 尝试多种常见命名方案
    for idx, name in enumerate(class_names):
        name = name.lower().strip()

        tile_id = _parse_class_name(name)
        if tile_id is not None:
            mapping[idx] = tile_id
        else:
            # 兜底: 按索引顺序分配
            if idx < 34:
                mapping[idx] = idx
            print(f"  [WARN] Unknown class name: '{name}' → using idx {idx}")

    return mapping


def _parse_class_name(name: str) -> int or None:
    """
    解析常见雀魂牌类名 → tile_id。

    支持格式:
      - "1m", "2m", ... "9m"  → 0-8
      - "1p", "2p", ... "9p"  → 9-17
      - "1s", "2s", ... "9s"  → 18-26
      - "1z"..."7z" 或 "E/S/W/N/P/F/C" → 27-33
      - "r5m", "r5p", "r5s"  → 34-36
    """
    name = name.strip().lower()

    # 万子: "1m"~"9m" 或 "man1"~"man9"
    for n in range(1, 10):
        if name in (f"{n}m", f"man{n}"):
            return n - 1  # 0-8

    # 筒子: "1p"~"9p" 或 "pin1"~"pin9"
    for n in range(1, 10):
        if name in (f"{n}p", f"pin{n}"):
            return 8 + n  # 9-17

    # 索子: "1s"~"9s" 或 "sou1"~"sou9"
    for n in range(1, 10):
        if name in (f"{n}s", f"sou{n}"):
            return 17 + n  # 18-26

    # 字牌 (编号 1z-7z)
    honor_map = {
        "1z": 27, "east": 27, "e": 27, "东": 27,
        "2z": 28, "south": 28, "s": 28, "南": 28,
        "3z": 29, "west": 29, "w": 29, "西": 29,
        "4z": 30, "north": 30, "n": 30, "北": 30,
        "5z": 31, "white": 31, "haku": 31, "白": 31,
        "6z": 32, "green": 32, "hatsu": 32, "发": 32,
        "7z": 33, "red": 33, "chun": 33, "中": 33,
    }
    if name in honor_map:
        return honor_map[name]

    # 赤宝牌
    red_map = {
        "r5m": 34, "0m": 34, "akaman5": 34,
        "r5p": 35, "0p": 35, "akapin5": 35,
        "r5s": 36, "0s": 36, "akasou5": 36,
    }
    if name in red_map:
        return red_map[name]

    return None


def _extract_from_filenames(dataset):
    """无 label 字段时, 从图片文件名推理类名"""
    print("[Extract] No label feature, trying filename-based extraction...")
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    import cv2
    import numpy as np

    # 如果是纯图片数据集 (无标签列), 每个 item 就是一张图
    extracted = 0
    for item in dataset:
        img = item["image"] if "image" in item else item
        if not hasattr(img, "save"):
            continue

        # 尝试获取文件名
        path = getattr(img, "filename", None) or getattr(img, "_path", "")
        basename = os.path.basename(str(path)) if path else f"tile_{extracted}.png"

        # 从文件名推断 tile_id
        tile_id = _infer_tile_id_from_filename(basename)

        # 保存
        h_target = 48
        w_orig, h_orig = img.size if hasattr(img, "size") else (48, 48)
        w_target = int(w_orig * h_target / max(1, h_orig))
        img = img.resize((max(1, w_target), h_target))

        out_path = os.path.join(TEMPLATE_DIR, f"{tile_id}.png")
        try:
            img.save(out_path)
            print(f"  [{extracted:2d}] {basename} → tile_id={tile_id}")
            extracted += 1
        except Exception as e:
            print(f"  [SKIP] {basename}: {e}")

        if extracted >= 37:
            break

    print(f"\n[Done] Saved {extracted} templates")


def _infer_tile_id_from_filename(filename: str) -> int:
    """从文件名推测试图对应的牌 ID"""
    name = os.path.splitext(filename)[0].lower()

    # 直接尝试解析
    parsed = _parse_class_name(name)
    if parsed is not None:
        return parsed

    # 对 hash 值做 fallback (随机分配)
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return h % 34


if __name__ == "__main__":
    download_and_extract()
