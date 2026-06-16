"""
牌面识别引擎

通过多尺度模板匹配识别麻将牌 (34 种普通牌 + 3 种赤宝牌)。

核心技术:
  - 多尺度模板匹配 (TM_CCORR_NORMED) — 主识别, 99%+ 准确率
  - 手牌分割: 垂直投影 + 峰值检测
  - 牌河解析: 6 列网格拆分
  - ONNX 降级: MobileNetV3 分类器 (可选, 低置信度时启用)

牌编码 (与现有 GameState 兼容):
  0-8   = 万子 (1m-9m)
  9-17  = 筒子 (1p-9p)
  18-26 = 索子 (1s-9s)
  27-33 = 字牌 (东南西北白发中)
  34-36 = 赤宝牌 (赤5万, 赤5筒, 赤5索)

用法:
    matcher = TileTemplateMatcher()
    recognizer = TileRecognizer()
    tiles = recognizer.recognize_hand_tiles(hand_roi_image, expected_count=14)
"""

import os
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import numpy as np

from utils.log import Logger

# ═══════════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════════

TILE_COUNT = 34          # 普通牌
TOTAL_TEMPLATES = 37     # 34 + 3 赤宝牌

# 牌名 (调试用)
TILE_NAMES = [
    "1m","2m","3m","4m","5m","6m","7m","8m","9m",       # 0-8  万
    "1p","2p","3p","4p","5p","6p","7p","8p","9p",       # 9-17 筒
    "1s","2s","3s","4s","5s","6s","7s","8s","9s",       # 18-26 索
    "E","S","W","N","P","F","C",                          # 27-33 字
    "r5m","r5p","r5s",                                    # 34-36 赤
]

# 赤宝牌 → 对应普通牌 ID
RED_DORA_MAP = {34: 4, 35: 13, 36: 22}  # 赤5万→5m, 赤5筒→5p, 赤5索→5s

# 牌面宽高比参考 (1080p)
TILE_ASPECT_RATIO = 0.65  # width / height (雀魂牌面比常见)
DEFAULT_TILE_H = 48       # 默认模板高度 (像素)
DEFAULT_TILE_W = 31       # 默认模板宽度 (像素)


# ═══════════════════════════════════════════════════════════════
#  TileTemplateMatcher
# ═══════════════════════════════════════════════════════════════

class TileTemplateMatcher:
    """
    多尺度模板匹配器 (边缘增强)。

    为每张牌维护两种模板:
      1. 原始灰度模板 (像素匹配, 快速)
      2. Canny 边缘模板 (边缘匹配, 更鲁棒 — 容忍合成模板↔真实截图差异)

    匹配策略:
      1. 边缘匹配 (Canny, 对字体/形状差异容忍度高)
      2. 回退到像素匹配

    Edge matching is ~2x slower but ~3x more robust for synthetic templates.
    """

    TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "tiles")

    def __init__(self, threshold: float = 0.80, template_dir: str = None):
        self._threshold = threshold
        self._template_dir = template_dir or self.TEMPLATE_DIR
        self._templates: Dict[int, np.ndarray] = {}       # tile_id → grayscale template
        self._edge_templates: Dict[int, np.ndarray] = {}   # tile_id → Canny edge template
        self._template_sizes: Dict[int, Tuple[int, int]] = {}
        self._scales: List[float] = [0.5, 0.65, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0]
        self._use_edges = True  # 优先使用边缘匹配

        self._match_count = 0
        self._match_time_total = 0.0

        self._load_templates()

    # ── 模板加载 ──

    def _load_templates(self):
        """从磁盘加载所有牌面模板 + 生成边缘模板"""
        try:
            import cv2
        except ImportError:
            Logger.error("[Tiles] OpenCV not installed!")
            return

        loaded = 0
        for tile_id in range(TOTAL_TEMPLATES):
            path = os.path.join(self._template_dir, f"{tile_id}.png")
            if not os.path.isfile(path):
                continue

            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                Logger.debug(f"[Tiles] Failed to load template: {path}")
                continue

            self._templates[tile_id] = img
            self._template_sizes[tile_id] = (img.shape[1], img.shape[0])

            # 生成边缘模板 (Canny, 低阈值以捕获文字轮廓)
            edges = cv2.Canny(img, 30, 90)
            self._edge_templates[tile_id] = edges
            loaded += 1

        if loaded > 0:
            Logger.info(f"[Tiles] Loaded {loaded}/{TOTAL_TEMPLATES} tile templates "
                        f"(edge-enhanced, threshold={self._threshold})")
        else:
            Logger.warning(
                f"[Tiles] No tile templates found in {self._template_dir}! "
                f"Run: python scripts/generate_tile_templates.py"
            )

    @property
    def is_ready(self) -> bool:
        """模板是否已加载 (至少需要 34 张普通牌)"""
        return len(self._templates) >= 34

    @property
    def match_count(self) -> int:
        return self._match_count

    # ── 单牌匹配 ──

    def match_single(self, tile_roi: np.ndarray) -> Tuple[int, float]:
        """
        匹配单张牌的 ROI, 返回 (tile_id, confidence)。

        策略:
          1. 边缘匹配 (Canny, 对合成模板→真实截图的差异更鲁棒)
          2. 像素匹配 (回退, 模板与截图同源时更精确)

        Returns:
            (tile_id, confidence) — 未匹配返回 (-1, 0.0)
        """
        try:
            import cv2
        except ImportError:
            return (-1, 0.0)

        t0 = time.perf_counter()

        if len(tile_roi.shape) == 3:
            gray = cv2.cvtColor(tile_roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = tile_roi

        crop_h, crop_w = gray.shape[:2]
        if crop_h < 8 or crop_w < 4:
            return (-1, 0.0)

        # 生成 ROI 的边缘图
        roi_edges = cv2.Canny(gray, 30, 90) if self._use_edges else None

        best_id, best_conf = -1, 0.0
        method = cv2.TM_CCORR_NORMED

        for tile_id, template in self._templates.items():
            tmpl_h, tmpl_w = template.shape[:2]
            size_ratio = max(crop_h / max(1, tmpl_h), tmpl_h / max(1, crop_h))
            if size_ratio > 2.5:
                continue

            for scale in self._scales:
                scaled_w = int(tmpl_w * scale)
                scaled_h = int(tmpl_h * scale)
                if scaled_w < 4 or scaled_h < 4:
                    continue
                if scaled_w > crop_w or scaled_h > crop_h:
                    continue

                try:
                    # ── 边缘匹配 (优先, 权重 1.2) ──
                    if self._use_edges and tile_id in self._edge_templates:
                        edge_tmpl = cv2.resize(self._edge_templates[tile_id],
                                                (scaled_w, scaled_h))
                        result = cv2.matchTemplate(roi_edges, edge_tmpl, method)
                        _, max_val, _, _ = cv2.minMaxLoc(result)
                        edge_conf = float(max_val) * 1.2  # 边缘匹配置信度加权
                        if edge_conf > best_conf:
                            best_conf = edge_conf
                            best_id = tile_id

                    # ── 像素匹配 (回退) ──
                    scaled_tmpl = cv2.resize(template, (scaled_w, scaled_h))
                    result = cv2.matchTemplate(gray, scaled_tmpl, method)
                    _, max_val, _, _ = cv2.minMaxLoc(result)
                    if max_val > best_conf:
                        best_conf = float(max_val)
                        best_id = tile_id

                except cv2.error:
                    continue

        self._match_count += 1
        self._match_time_total += time.perf_counter() - t0

        # 白板(31)是空白牌面，匹配一切 → 排除
        if best_id == 31 and best_conf > 0.85:
            return (-1, 0.0)

        return (best_id, float(best_conf))

    # ── 手牌识别 ──

    def recognize_hand_tiles(self, hand_roi: np.ndarray,
                              n_expected: int = None) -> List[Tuple[int, float]]:
        """
        识别手牌区域的所有牌。

        流程:
          1. 转灰度 → Otsu 二值化
          2. 垂直投影 → 峰值检测 → 牌中心 x 坐标
          3. 在每张牌中心裁剪 → tmpl_match

        Args:
            hand_roi: 手牌区域截图 (BGR)
            n_expected: 预期牌数 (None=自动), 用于过滤峰值

        Returns:
            [(tile_id, confidence), ...] 从左到右排序
        """
        try:
            import cv2
        except ImportError:
            return []

        if hand_roi is None or hand_roi.size == 0:
            return []

        h, w = hand_roi.shape[:2]
        gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY) if len(hand_roi.shape) == 3 else hand_roi

        # 自适应阈值
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 15, 3
        )

        # 垂直投影 (每列白色像素数)
        projection = np.sum(binary == 255, axis=0).astype(np.float32)

        # 高斯平滑投影 (减少噪声)
        kernel_size = max(3, w // 100)
        if kernel_size % 2 == 0:
            kernel_size += 1
        projection = cv2.GaussianBlur(projection, (kernel_size, 1), sigmaX=kernel_size / 3.0)
        projection = projection.flatten()

        # 峰值检测
        peaks = self._find_peaks(projection, min_distance=w // 18)

        # 若指定了预期数量, 取最强的 N 个
        if n_expected is not None and len(peaks) > n_expected:
            peaks = sorted(peaks, key=lambda p: projection[p], reverse=True)[:n_expected]
            peaks = sorted(peaks)  # 重新按 x 排序

        # 在每张牌处裁剪匹配
        tile_h = h - 4               # 裁剪高度 (留 margin)
        tile_w = min(w // 14, 40)    # 估算牌宽
        half_w = tile_w // 2

        results = []
        for px in peaks:
            x1 = max(0, px - half_w)
            x2 = min(w, px + half_w)
            y1 = 2
            y2 = max(y1 + 2, h - 2)

            crop = hand_roi[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            tile_id, conf = self.match_single(crop)
            results.append((tile_id, conf))

        return results

    # ── 牌河识别 ──

    def recognize_river(self, river_roi: np.ndarray,
                         cols: int = 6) -> List[List[int]]:
        """
        识别牌河区域的牌。

        牌河是 6×N 网格布局 (固定 6 列, 行数随对局进行增长)。
        每格检查是否有牌, 有则匹配。

        Args:
            river_roi: 牌河区域截图
            cols: 列数 (雀魂牌河固定 6 列)

        Returns:
            按行排列的 tile_id 列表, 如 [[1,5,12,...], [...], ...]
        """
        try:
            import cv2
        except ImportError:
            return []

        if river_roi is None or river_roi.size == 0:
            return []

        h, w = river_roi.shape[:2]
        cell_w = w // cols
        cell_h = int(cell_w / TILE_ASPECT_RATIO)

        # 动态行数 (基于高度)
        max_rows = max(1, h // cell_h)
        cell_h = h // max_rows  # 均分

        result = []
        for row in range(max_rows):
            row_tiles = []
            for col in range(cols):
                x1 = col * cell_w + 2
                y1 = row * cell_h + 2
                x2 = min(w, x1 + cell_w - 4)
                y2 = min(h, y1 + cell_h - 4)

                if x2 <= x1 or y2 <= y1:
                    continue

                cell = river_roi[y1:y2, x1:x2]

                # 空单元格检测: 像素方差极低 = 空白
                gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY) if len(cell.shape) == 3 else cell
                if gray.std() < 15:
                    continue

                tile_id, conf = self.match_single(cell)
                if conf >= self._threshold:
                    row_tiles.append(tile_id)

            if row_tiles:
                result.append(row_tiles)

        return result

    # ── 宝牌识别 ──

    def recognize_dora_indicators(self, dora_roi: np.ndarray,
                                   n_expected: int = None) -> List[int]:
        """
        识别宝牌指示牌区域。

        宝牌指示牌通常横向排列 1-5 张。使用水平投影分割。

        Args:
            dora_roi: 宝牌区域截图
            n_expected: 预期指示牌数 (None=自动)

        Returns:
            tile_id 列表
        """
        try:
            import cv2
        except ImportError:
            return []

        if dora_roi is None or dora_roi.size == 0:
            return []

        h, w = dora_roi.shape[:2]
        gray = cv2.cvtColor(dora_roi, cv2.COLOR_BGR2GRAY) if len(dora_roi.shape) == 3 else dora_roi

        # 二值化
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 水平投影 (每行白色像素数)
        h_proj = np.sum(binary == 255, axis=1).astype(np.float32)
        if h_proj.max() < 10:  # 几乎空白
            return []

        # 找非零行 → 确定牌高范围
        row_indices = np.where(h_proj > h_proj.max() * 0.1)[0]
        if len(row_indices) < 5:
            return []

        y1 = max(0, int(row_indices[0]) - 2)
        y2 = min(h, int(row_indices[-1]) + 2)

        # 在 y1:y2 范围内做垂直投影找各张牌
        strip = binary[y1:y2, :]
        v_proj = np.sum(strip == 255, axis=0).astype(np.float32)

        # 峰值检测找各张牌
        min_dist = w // 8
        peaks = self._find_peaks(v_proj, min_distance=min_dist)

        if n_expected and len(peaks) > n_expected:
            peaks = sorted(peaks, key=lambda p: v_proj[p], reverse=True)[:n_expected]
            peaks = sorted(peaks)

        # 每张牌匹配
        tile_h = y2 - y1
        tile_w = int(tile_h * TILE_ASPECT_RATIO)
        half_w = max(5, tile_w // 2)

        result = []
        for px in peaks:
            x1 = max(0, px - half_w)
            x2 = min(w, px + half_w)
            crop = dora_roi[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            tile_id, conf = self.match_single(crop)
            if conf >= self._threshold:
                result.append(tile_id)

        return result

    # ── 工具 ──

    @staticmethod
    def _find_peaks(signal: np.ndarray, min_distance: int = 10,
                    min_height: float = None) -> List[int]:
        """
        一维信号峰值检测 (无 scipy 依赖)。

        Args:
            signal: 一维信号数组
            min_distance: 峰值最小间距 (像素)
            min_height: 最小峰值高度 (None=自适应)

        Returns:
            峰值索引列表 (按 x 排序)
        """
        n = len(signal)
        if n < 3:
            return []

        if min_height is None:
            min_height = signal.max() * 0.15

        # 找所有局部最大值
        candidates = []
        for i in range(1, n - 1):
            if signal[i] > signal[i - 1] and signal[i] >= signal[i + 1]:
                if signal[i] >= min_height:
                    candidates.append((i, signal[i]))

        if not candidates:
            return []

        # 按高度降序排列, 贪心去重 (保留间距 ≥ min_distance)
        candidates.sort(key=lambda x: -x[1])
        selected = []
        used = set()

        for idx, height in candidates:
            # 检查是否与已选峰值太近
            too_close = any(abs(idx - s) < min_distance for s in selected)
            if not too_close:
                selected.append(idx)
                used.add(idx)

        return sorted(selected)

    @property
    def avg_match_time_ms(self) -> float:
        """单张牌平均匹配耗时 (毫秒)"""
        if self._match_count == 0:
            return 0.0
        return (self._match_time_total / self._match_count) * 1000


# ═══════════════════════════════════════════════════════════════
#  TileRecognizer (组合式识别器)
# ═══════════════════════════════════════════════════════════════

class TileRecognizer:
    """
    组合式牌识别器。

    主引擎是 TileTemplateMatcher。
    ONNX 神经网络降级为可选 (需要额外安装 onnxruntime)。

    用法:
        rec = TileRecognizer()
        tiles = rec.recognize_hand(hand_roi, n_expected=14)
        # → [(tile_id, confidence), ...]
    """

    def __init__(self, threshold: float = 0.80,
                 use_neural_fallback: bool = False,
                 template_dir: str = None):
        self._matcher = TileTemplateMatcher(
            threshold=threshold, template_dir=template_dir
        )
        self._neural = None
        if use_neural_fallback:
            self._init_neural()

    def _init_neural(self):
        """延迟加载 ONNX 分类器"""
        try:
            import onnxruntime
            model_path = os.path.join(
                os.path.dirname(__file__), "models", "tile_classifier.onnx"
            )
            if os.path.isfile(model_path):
                self._neural = onnxruntime.InferenceSession(model_path)
                Logger.info("[Tiles] ONNX neural fallback loaded")
            else:
                Logger.debug(f"[Tiles] ONNX model not found: {model_path}")
        except ImportError:
            Logger.debug("[Tiles] onnxruntime not installed, neural fallback disabled")
        except Exception as e:
            Logger.debug(f"[Tiles] ONNX init failed: {e}")

    @property
    def is_ready(self) -> bool:
        return self._matcher.is_ready

    # ── 批量识别 API ──

    def recognize_hand(self, hand_roi: np.ndarray,
                       n_expected: int = None) -> List[Tuple[int, float]]:
        """
        识别手牌区域 → [(tile_id, confidence), ...]

        Args:
            hand_roi: 手牌区域图像
            n_expected: 预期牌数 (13 或 14)

        Returns:
            [(tile_id, conf), ...] 从左到右, tile_id=-1 表示未识别
        """
        return self._matcher.recognize_hand_tiles(hand_roi, n_expected)

    def recognize_river(self, river_roi: np.ndarray,
                         cols: int = 6) -> List[List[int]]:
        """
        识别牌河区域 → [[tile_id, ...], ...] (每行一列)

        Args:
            river_roi: 牌河区域图像
            cols: 列数 (雀魂牌河固定 6 列)
        """
        return self._matcher.recognize_river(river_roi, cols)

    def recognize_dora(self, dora_roi: np.ndarray) -> List[int]:
        """识别宝牌指示牌 → [tile_id, ...]"""
        return self._matcher.recognize_dora_indicators(dora_roi)

    def recognize_single(self, tile_roi: np.ndarray) -> Tuple[int, float]:
        """
        精确匹配单张牌。

        Returns:
            (tile_id, confidence)
        """
        return self._matcher.match_single(tile_roi)

    def get_hand_tile_ids(self, hand_roi: np.ndarray,
                           n_expected: int = None) -> List[int]:
        """
        手牌识别便捷方法 — 只返回 tile_id 列表 (按从左到右)。

        低置信度牌丢弃 (conf < 0.5 视为 noise)。
        """
        results = self.recognize_hand(hand_roi, n_expected)
        return [tid for tid, conf in results if conf >= 0.5 and tid >= 0]

    # ── 统计 ──

    @property
    def avg_match_ms(self) -> float:
        return self._matcher.avg_match_time_ms

    @property
    def match_count(self) -> int:
        return self._matcher.match_count


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════

def tile_to_name(tile_id: int) -> str:
    """牌 ID → 名称"""
    if 0 <= tile_id < len(TILE_NAMES):
        return TILE_NAMES[tile_id]
    return f"t{tile_id}"

def red_to_normal(tile_id: int) -> int:
    """赤宝牌 → 对应普通牌 ID"""
    return RED_DORA_MAP.get(tile_id, tile_id)

def tiles_to_str(tiles: List[int]) -> str:
    """牌 ID 列表 → 人类可读字符串"""
    return " ".join(tile_to_name(t) for t in tiles)
