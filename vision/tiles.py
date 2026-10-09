"""
牌面识别引擎

通过 SIFT 特征匹配 + 多尺度模板匹配识别麻将牌 (34 种普通牌 + 3 种赤宝牌)。

核心技术 (v2.4):
  - SIFT 特征匹配 (主引擎) — 亮度/对比度/主题不变, 匹配形状关键点
  - ORB 特征匹配 (轻量降级) — CPU 友好, 实时帧率
  - 模板匹配 (兜底) — TM_CCORR_NORMED + 灰度反转 + 多尺度
  - Canny 边缘模板 + 像素模板双通道并行 (边缘降权 0.95×)
  - Top-2 margin 检查 (差距 < 0.05 → uncertain)
  - 赤宝牌严格验证 (conf < 0.88 → 降级为普通 5)
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

# SIFT 特征匹配参数
SIFT_MIN_MATCHES = 8        # 最少 good matches 才能算有效匹配
# v2.5: SIFT 彻底失败、仅靠 CCOEFF 时的置信下限 (实测判对>=0.584, 误判<=0.513)
SIFT_FAIL_CCOEFF_MIN = 0.55
SIFT_LOWE_RATIO = 0.75      # Lowe's ratio test 阈值
SIFT_SCORE_CONFIDENCE = 1.0 # SIFT 结果置信度 (特征匹配不产生连续分数)


@dataclass
class SiftMatchResult:
    """SIFT 特征匹配结果"""
    tile_id: int           # 匹配的牌 ID, -1 表示未匹配
    good_matches: int      # 通过 Lowe ratio test 的匹配数
    total_kp: int          # ROI 中的总关键点数
    score: float           # good_matches / min(tmpl_kp, roi_kp)
    confidence: float      # 归一化置信度 (0-1)

# 牌面宽高比参考 (1080p)
TILE_ASPECT_RATIO = 0.65  # width / height (雀魂牌面比常见)
# v2.3: 基于实际模板尺寸 (80x129), 非旧金山合成版 (31x48)
DEFAULT_TILE_H = 129      # 实际模板高度 (像素)
DEFAULT_TILE_W = 80       # 实际模板宽度 (像素)
# v2.5: 实测游戏内牌面宽高比 (2557 宽画面真实牌面 122x190 ≈ 0.64)
TILE_REAL_ASPECT = 0.64   # 手牌切分按此比例, 完整包住牌面后再归一化


# ═══════════════════════════════════════════════════════════════
#  TileTemplateMatcher
# ═══════════════════════════════════════════════════════════════

class TileTemplateMatcher:
    """
    多策略牌面匹配器 (SIFT 特征 + 边缘模板 + 深色主题自适应)。

    为每张牌维护多种表示:
      1. 原始灰度模板 (像素匹配, 快速)
      2. Canny 边缘模板 (边缘匹配, 更鲁棒 — 容忍合成模板↔真实截图差异)
      3. SIFT 关键点 + 描述符 (特征匹配, 亮度/对比度/主题不变)

    匹配策略 (v2.4 — SIFT 主引擎):
      1. SIFT 特征匹配 (主) — 匹配形状关键点, 对深色/浅色主题不变
      2. ORB 特征匹配 (轻量降级) — CPU 友好, 实时帧率下使用
      3. 模板匹配 (兜底) — CCORR_NORMED + 灰度反转 + 多尺度
      4. Top-2 margin 检查 — 差距 < margin_threshold 时标记 uncertain
      5. 赤宝牌严格验证 — 置信度不够时降级为普通 5

    SIFT is ~2-3x slower than template matching but invariant to rendering
    differences (synthetic templates vs real game screenshots).
    """

    TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "tiles")
    LIVE_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "tiles_live")

    def __init__(self, threshold: float = 0.80, template_dir: str = None,
                 margin_threshold: float = 0.005,
                 invert_dark: bool = True,
                 red_dora_strict: bool = True,
                 adaptive_scales: bool = True,
                 use_sift: bool = True,
                 use_orb_fallback: bool = True):
        self._threshold = threshold
        self._template_dir = template_dir or self.TEMPLATE_DIR
        self._templates: Dict[int, np.ndarray] = {}       # tile_id → grayscale template
        self._edge_templates: Dict[int, np.ndarray] = {}   # tile_id → Canny edge template
        self._template_sizes: Dict[int, Tuple[int, int]] = {}
        self._scales: List[float] = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.75, 2.0, 2.5]
        self._use_edges = True  # 优先使用边缘匹配
        self._adaptive_scales = adaptive_scales  # v2.3: 自适应 scale 裁剪

        # v2.3: 深色主题兼容参数
        self._margin_threshold = margin_threshold  # top-2 最小置信度差
        self._invert_dark = invert_dark            # 自动灰度反转深色 ROI
        self._red_dora_strict = red_dora_strict    # 赤宝牌严格阈值

        self._match_count = 0
        self._match_time_total = 0.0

        # v2.3: 中心聚焦模板 (裁剪背景, 保留区分特征)
        self._focus_templates: Dict[int, np.ndarray] = {}
        self._focus_edge_templates: Dict[int, np.ndarray] = {}
        self._focus_ratio = 0.55  # 保留中央 55%

        # v2.4: SIFT 特征匹配
        self._use_sift = use_sift
        self._use_orb_fallback = use_orb_fallback
        self._sift = None           # cv2.SIFT_create()
        self._orb = None            # cv2.ORB_create() — 轻量降级
        self._sift_kp: Dict[int, tuple] = {}     # tile_id → (keypoints, descriptors)
        self._sift_edge_kp: Dict[int, tuple] = {} # tile_id → (keypoints, descriptors) on Canny edges
        self._orb_kp: Dict[int, tuple] = {}      # tile_id → (keypoints, descriptors)
        self._flann = None          # FLANN matcher for SIFT (逐模板, 回退用)
        self._raw_desc_mat = None      # v2.5 numpy 描述子索引 (原始)
        self._raw_desc_sq = None
        self._raw_desc_labels = None
        self._edge_desc_mat = None    # v2.5 numpy 描述子索引 (Canny 边缘)
        self._edge_desc_sq = None
        self._edge_desc_labels = None
        self._raw_id_order: List[int] = []
        self._edge_id_order: List[int] = []
        self._bf_matcher = None     # Brute-Force matcher for ORB
        self._sift_match_count = 0  # SIFT 匹配成功次数
        self._sift_fallback_count = 0  # SIFT 失败降级次数
        self._init_feature_detectors()

        self._load_templates()

    def _init_feature_detectors(self):
        """初始化 SIFT/ORB 特征检测器和匹配器"""
        if not self._use_sift:
            return
        try:
            import cv2
        except ImportError:
            self._use_sift = False
            return

        try:
            self._sift = cv2.SIFT_create(
                nfeatures=0,            # 保留所有特征
                nOctaveLayers=3,
                contrastThreshold=0.04,
                edgeThreshold=10,
                sigma=1.6,
            )
            # FLANN 参数 (适用于 SIFT float descriptors)
            index_params = dict(algorithm=1, trees=5)   # KD-tree
            search_params = dict(checks=50)
            self._flann = cv2.FlannBasedMatcher(index_params, search_params)
            Logger.debug("[Tiles] SIFT feature detector initialized")
        except Exception as e:
            Logger.debug(f"[Tiles] SIFT init failed: {e}")
            self._sift = None
            self._flann = None

        # ORB 作为轻量降级
        if self._use_orb_fallback:
            try:
                self._orb = cv2.ORB_create(
                    nfeatures=500,
                    scaleFactor=1.2,
                    nlevels=8,
                )
                self._bf_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
                Logger.debug("[Tiles] ORB fallback detector initialized")
            except Exception as e:
                Logger.debug(f"[Tiles] ORB init failed: {e}")
                self._orb = None

    # ── 模板加载 ──

    def _load_templates(self):
        """从磁盘加载所有牌面模板 + 生成边缘模板 + live 模板"""
        try:
            import cv2
        except ImportError:
            Logger.error("[Tiles] OpenCV not installed!")
            return

        loaded = 0

        # ── 主模板库 (预制牌面) ──
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
            edges = cv2.Canny(img, 30, 90)
            self._edge_templates[tile_id] = edges

            # 中心聚焦版 (裁剪中央 55%, 去背景)
            h_t, w_t = img.shape
            cx, cy = w_t // 2, h_t // 2
            fw, fh = int(w_t * self._focus_ratio), int(h_t * self._focus_ratio)
            fx1, fy1 = cx - fw // 2, cy - fh // 2
            self._focus_templates[tile_id] = img[fy1:fy1+fh, fx1:fx1+fw]
            self._focus_edge_templates[tile_id] = edges[fy1:fy1+fh, fx1:fx1+fw]

            # v2.4: SIFT 关键点 + 描述符 (预计算, 亮度/对比度不变)
            if self._sift is not None:
                kp, desc = self._sift.detectAndCompute(img, None)
                if desc is not None and len(kp) >= 4:
                    self._sift_kp[tile_id] = (kp, desc)
                # 边缘图 SIFT (Canny edges — 颜色反转不变)
                kp_e, desc_e = self._sift.detectAndCompute(edges, None)
                if desc_e is not None and len(kp_e) >= 4:
                    self._sift_edge_kp[tile_id] = (kp_e, desc_e)

            # v2.4: ORB 关键点 + 描述符 (轻量降级)
            if self._orb is not None:
                kp, desc = self._orb.detectAndCompute(img, None)
                if desc is not None and len(kp) >= 4:
                    self._orb_kp[tile_id] = (kp, desc)

            loaded += 1

        # ── Live 模板 (游戏实采, 优先级高于预制) ──
        #    ID 范围 100-199, 匹配时自动胜出 (高分 1.0 vs 0.9)
        import glob as _glob
        import json as _json
        self._live_labels: Dict[int, int] = {}  # live_id → premade tile_id

        labels_path = os.path.join(self.LIVE_TEMPLATE_DIR, "labels.json")
        if os.path.isfile(labels_path):
            try:
                with open(labels_path, 'r') as f:
                    label_data = _json.load(f)
                for fname, info in label_data.items():
                    if info.get('tile_id', -1) >= 0:
                        live_path = os.path.join(self.LIVE_TEMPLATE_DIR, fname)
                        if os.path.isfile(live_path):
                            img = cv2.imread(live_path, cv2.IMREAD_GRAYSCALE)
                            if img is not None:
                                live_id = 100 + info['tile_id']
                                self._templates[live_id] = img
                                self._template_sizes[live_id] = (img.shape[1], img.shape[0])
                                edges = cv2.Canny(img, 30, 90)
                                self._edge_templates[live_id] = edges
                                # v2.4: SIFT/ORB for live templates
                                if self._sift is not None:
                                    kp, desc = self._sift.detectAndCompute(img, None)
                                    if desc is not None and len(kp) >= 4:
                                        self._sift_kp[live_id] = (kp, desc)
                                    kp_e, desc_e = self._sift.detectAndCompute(edges, None)
                                    if desc_e is not None and len(kp_e) >= 4:
                                        self._sift_edge_kp[live_id] = (kp_e, desc_e)
                                if self._orb is not None:
                                    kp, desc = self._orb.detectAndCompute(img, None)
                                    if desc is not None and len(kp) >= 4:
                                        self._orb_kp[live_id] = (kp, desc)
                                self._live_labels[live_id] = info['tile_id']
                                loaded += 1
            except Exception as e:
                Logger.debug(f"[Tiles] Failed to load live labels: {e}")

        self._build_desc_index()

        live_count = len(self._live_labels)
        sift_count = len(self._sift_kp)
        orb_count = len(self._orb_kp)
        if loaded > 0:
            Logger.info(f"[Tiles] Loaded {loaded}/{TOTAL_TEMPLATES} tile templates "
                        f"(live: {live_count}, SIFT: {sift_count}, ORB: {orb_count}, "
                        f"threshold={self._threshold})")
        else:
            Logger.warning(
                f"[Tiles] No tile templates found! "
                f"Run: python scripts/generate_tile_templates.py"
            )

    @property
    def is_ready(self) -> bool:
        """模板是否已加载 (至少需要 34 张普通牌)"""
        return len(self._templates) >= 34

    @property
    def match_count(self) -> int:
        return self._match_count

    @property
    def sift_match_count(self) -> int:
        """SIFT 成功匹配次数"""
        return self._sift_match_count

    @property
    def sift_fallback_count(self) -> int:
        """SIFT 失败降级到模板匹配的次数"""
        return self._sift_fallback_count

    @property
    def sift_ready(self) -> bool:
        """SIFT 是否可用 (检测器 + 模板描述符都已就绪)"""
        return self._sift is not None and self._flann is not None and len(self._sift_kp) >= 34

    # ── v2.4: SIFT 特征匹配 ──

    def _match_sift(self, tile_roi: np.ndarray) -> SiftMatchResult:
        """
        SIFT 特征匹配 — 匹配形状关键点, 对亮度/对比度/主题不变。

        算法:
          1. 在 ROI 中检测 SIFT 关键点 + 计算描述符
          2. 先尝试直接匹配 (同主题: 浅→浅 或 深→深)
          3. 若失败, 在 Canny 边缘图上匹配 (跨主题: 浅↔深)
             Canny 边缘对颜色反转不变 — 边界就是边界
          4. 得分 = good_matches / roi_kp_count (固定分母)
          5. 返回得分最高的模板

        这是 v2.4 的主匹配引擎 — 解决了模板匹配在深色/浅色
        主题间完全失效的问题 (合成模板 vs 真实游戏渲染)。

        Returns:
            SiftMatchResult — tile_id=-1 表示未匹配
        """
        try:
            import cv2
        except ImportError:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

        if not self.sift_ready or tile_roi is None or tile_roi.size == 0:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

        # 转灰度
        if len(tile_roi.shape) == 3:
            gray = cv2.cvtColor(tile_roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = tile_roi.copy()

        h, w = gray.shape[:2]
        if h < 20 or w < 10:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

        # 检测 ROI 关键点 (原始 + Canny 边缘)
        roi_kp, roi_desc = self._sift.detectAndCompute(gray, None)
        roi_edges = cv2.Canny(gray, 30, 90)
        roi_edge_kp, roi_edge_desc = self._sift.detectAndCompute(roi_edges, None)

        # ═══════════════════════════════════════════════════
        # 第一阶段: 原始图像 SIFT 匹配 (同主题)
        # 浅色模板 + 浅色游戏 → 直接匹配, 高分
        # ═══════════════════════════════════════════════════
        if roi_desc is not None and len(roi_kp) >= 4:
            result = self._sift_match_stage(
                roi_desc, len(roi_kp), self._raw_desc_mat, self._raw_desc_sq,
                self._raw_desc_labels, self._raw_id_order, self._sift_kp
            )
            if result.tile_id >= 0:
                return result

        # ═══════════════════════════════════════════════════
        # 第二阶段: Canny 边缘 SIFT 匹配 (跨主题)
        # 浅色模板 → 深色游戏 (或反之)
        # Canny 边缘对颜色反转完全不变, 50/50 matches
        # ═══════════════════════════════════════════════════
        if roi_edge_desc is not None and len(roi_edge_kp) >= 4:
            result = self._sift_match_stage(
                roi_edge_desc, len(roi_edge_kp), self._edge_desc_mat, self._edge_desc_sq,
                self._edge_desc_labels, self._edge_id_order, self._sift_edge_kp
            )
            if result.tile_id >= 0:
                return result

        return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

    def _build_desc_index(self):
        """v2.5: 把全部模板 SIFT 描述子拼成 numpy 大矩阵 (精确 L2, 一次矩阵乘)。"""
        try:
            for src, mat_a, sq_a, lab_a, ids_a in [
                (self._sift_kp, "_raw_desc_mat", "_raw_desc_sq",
                 "_raw_desc_labels", "_raw_id_order"),
                (self._sift_edge_kp, "_edge_desc_mat", "_edge_desc_sq",
                 "_edge_desc_labels", "_edge_id_order"),
            ]:
                descs, labels, id_order = [], [], []
                for tid in sorted(src.keys()):
                    if tid == 31:                          # 白板无特征
                        continue
                    _, desc = src[tid]
                    if desc is None or len(desc) < 8:
                        continue
                    d = np.ascontiguousarray(desc, dtype=np.float32)
                    descs.append(d)
                    labels.append(np.full(len(d), tid, dtype=np.int32))
                    id_order.append(tid)
                if descs:
                    mat = np.vstack(descs)
                    setattr(self, mat_a, mat)
                    setattr(self, sq_a, np.einsum("ij,ij->i", mat, mat))
                    setattr(self, lab_a, np.concatenate(labels))
                    setattr(self, ids_a, id_order)
        except Exception as e:
            Logger.debug(f"[Tiles] desc index build failed: {e}")

    def _sift_match_stage(self, roi_desc, roi_kp_count, desc_mat, desc_sq,
                          desc_labels, id_order, fallback_dict):
        """numpy 精确批量优先; 不可用时回退逐模板 FLANN。"""
        if desc_mat is not None and id_order:
            return self._sift_match_numpy(
                roi_desc, roi_kp_count, desc_mat, desc_sq, desc_labels, id_order)
        return self._sift_match_internal(roi_desc, roi_kp_count, fallback_dict)

    def _sift_match_numpy(self, roi_desc, roi_kp_count, mat, m_sq, labels, id_order):
        """
        v2.5 性能版: L2 距离矩阵一次算出, 每个模板内取最近两点做 Lowe。
        与逐模板 FLANN k=2 语义一致, 但精确(非近似)且向量化, 单张毫秒级。
        """
        if roi_desc is None or roi_kp_count < 4 or mat is None:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)
        q = np.ascontiguousarray(roi_desc, dtype=np.float32)
        q_sq = np.einsum("ij,ij->i", q, q)[:, None]
        d2 = q_sq + m_sq[None, :] - 2.0 * (q @ mat.T)
        np.maximum(d2, 0.0, out=d2)
        ratio2 = SIFT_LOWE_RATIO ** 2          # 平方距离上的 Lowe 阈值

        best_id, best_score, best_matches = -1, 0.0, 0
        second_id, second_score = -1, 0.0
        for tid in id_order:
            cols = labels == tid
            if int(cols.sum()) < 2:
                continue
            sub = d2[:, cols]
            two = np.partition(sub, 1, axis=1)[:, :2]   # 该模板内最近两点
            d0, d1 = two[:, 0], two[:, 1]
            good = int(np.count_nonzero(d0 < ratio2 * d1))
            if good < SIFT_MIN_MATCHES:
                continue
            score = good / roi_kp_count
            if score > best_score:
                second_id, second_score = best_id, best_score
                best_id, best_score, best_matches = tid, score, good
            elif score > second_score and tid != best_id:
                second_id, second_score = tid, score

        confidence = min(1.0, best_score)
        if best_id >= 0 and second_id >= 0 and best_score < 0.80 \
                and best_score - second_score < 0.03:
            Logger.debug(
                f"[Tiles:SIFT-np] Low margin: best=({best_id},{best_score:.3f}) "
                f"second=({second_id},{second_score:.3f})"
            )
            return SiftMatchResult(-1, best_matches, roi_kp_count, best_score, 0.0)
        return SiftMatchResult(best_id, best_matches, roi_kp_count, best_score, confidence)

    def _sift_match_internal(self, roi_desc, roi_kp_count,
                              template_kp_dict) -> SiftMatchResult:
        """
        SIFT 匹配核心 — 给定 ROI 描述符和模板字典, 返回最佳匹配。

        与 _match_sift 分离以便复用 (原始 + 边缘两种通道)。
        """
        if roi_desc is None or roi_kp_count < 4:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

        best_id, best_score, best_matches = -1, 0.0, 0
        second_id, second_score = -1, 0.0

        for tile_id, (tmpl_kp, tmpl_desc) in template_kp_dict.items():
            # 跳过白板 (几乎无特征) 和特征过少的模板
            if tile_id == 31 or len(tmpl_kp) < 8:
                continue

            try:
                # FLANN 匹配 (k=2 for Lowe's ratio test)
                matches = self._flann.knnMatch(roi_desc, tmpl_desc, k=2)

                # Lowe's ratio test
                good = []
                for match_pair in matches:
                    if len(match_pair) == 2:
                        m, n = match_pair
                        if m.distance < SIFT_LOWE_RATIO * n.distance:
                            good.append(m)

                good_count = len(good)
                if good_count < SIFT_MIN_MATCHES:
                    continue

                # 得分: good_matches / roi_kp_count
                # 使用固定分母 (ROI 特征数), 避免小模板偏置
                score = good_count / roi_kp_count

                if score > best_score:
                    second_id, second_score = best_id, best_score
                    best_score = score
                    best_id = tile_id
                    best_matches = good_count
                elif score > second_score and tile_id != best_id:
                    second_id = tile_id
                    second_score = score

            except cv2.error:
                continue

        # Confidence: cap at 1.0
        confidence = min(1.0, best_score)

        # Margin check: 只在低分区域检查 (高分时 margin 不重要)
        if best_id >= 0 and second_id >= 0:
            margin = best_score - second_score
            if best_score < 0.80 and margin < 0.03:
                Logger.debug(
                    f"[Tiles:SIFT] Low margin: best=({best_id},{best_score:.3f}) "
                    f"second=({second_id},{second_score:.3f}) margin={margin:.3f}"
                )
                return SiftMatchResult(-1, best_matches, roi_kp_count, best_score, 0.0)

        return SiftMatchResult(best_id, best_matches, roi_kp_count, best_score, confidence)

    # ── v2.4: ORB 特征匹配 (轻量降级) ──

    def _match_orb(self, tile_roi: np.ndarray) -> SiftMatchResult:
        """
        ORB 特征匹配 — CPU 友好的轻量降级。

        使用 ORB (binary descriptors) + Brute-Force Hamming distance。
        精度低于 SIFT 但速度快 ~3-5x, 适合实时帧率场景。

        Returns:
            SiftMatchResult — tile_id=-1 表示未匹配
        """
        try:
            import cv2
        except ImportError:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

        if self._orb is None or not self._orb_kp:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

        if tile_roi is None or tile_roi.size == 0:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

        if len(tile_roi.shape) == 3:
            gray = cv2.cvtColor(tile_roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = tile_roi.copy()

        h, w = gray.shape[:2]
        if h < 20 or w < 10:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

        roi_kp, roi_desc = self._orb.detectAndCompute(gray, None)
        if roi_desc is None or len(roi_kp) < 4:
            return SiftMatchResult(-1, 0, 0, 0.0, 0.0)

        roi_kp_count = len(roi_kp)
        best_id, best_score, best_matches = -1, 0.0, 0
        second_id, second_score = -1, 0.0

        for tile_id, (tmpl_kp, tmpl_desc) in self._orb_kp.items():
            # 跳过白板和特征过少的模板
            if tile_id == 31 or len(tmpl_kp) < 8:
                continue

            try:
                matches = self._bf_matcher.knnMatch(roi_desc, tmpl_desc, k=2)
                good = []
                for match_pair in matches:
                    if len(match_pair) == 2:
                        m, n = match_pair
                        if m.distance < 0.75 * n.distance:
                            good.append(m)

                good_count = len(good)
                if good_count < SIFT_MIN_MATCHES:
                    continue

                # 使用固定分母 (ROI 特征数), 避免小模板偏置
                score = good_count / roi_kp_count

                if score > best_score:
                    second_id, second_score = best_id, best_score
                    best_score = score
                    best_id = tile_id
                    best_matches = good_count
                elif score > second_score and tile_id != best_id:
                    second_id = tile_id
                    second_score = score

            except cv2.error:
                continue

        confidence = min(1.0, best_score)

        if best_id >= 0 and second_id >= 0:
            margin = best_score - second_score
            if best_score < 0.80 and margin < 0.03:
                return SiftMatchResult(-1, best_matches, roi_kp_count, best_score, 0.0)

        return SiftMatchResult(best_id, best_matches, roi_kp_count, best_score, confidence)

    # ── 单牌匹配 ──

    def match_single(self, tile_roi: np.ndarray, center_focus: bool = False) -> Tuple[int, float]:
        """
        匹配单张牌的 ROI, 返回 (tile_id, confidence)。

        策略 (v2.4 — SIFT 主引擎):
          1. SIFT 特征匹配 (主) — 形状关键点, 对深色/浅色主题不变
          2. ORB 特征匹配 (轻量降级) — SIFT 不可用时启用
          3. 模板匹配 (兜底) — CCORR_NORMED + 灰度反转 + 多尺度
          4. Top-2 margin 检查 — 差距不足时标记 uncertain (-1)
          5. 赤宝牌严格验证 — 低置信度自动降级为普通 5

        Returns:
            (tile_id, confidence) — 未匹配返回 (-1, 0.0)
        """
        try:
            import cv2
        except ImportError:
            return (-1, 0.0)

        t0 = time.perf_counter()

        if tile_roi is None or tile_roi.size == 0:
            return (-1, 0.0)

        if len(tile_roi.shape) == 3:
            gray = cv2.cvtColor(tile_roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = tile_roi.copy()

        crop_h, crop_w = gray.shape[:2]
        if crop_h < 8 or crop_w < 4:
            return (-1, 0.0)

        # White dragon has no glyph keypoints. Require both a neutral, uniform
        # face and the complete template rim; plain empty regions must reject.
        blank = self._templates.get(31)
        if blank is not None:
            face = cv2.resize(gray, (blank.shape[1], blank.shape[0]))
            if self._invert_dark and face.mean() < 127:
                face = cv2.bitwise_not(face)
            center = face[face.shape[0] // 4:3 * face.shape[0] // 4,
                          face.shape[1] // 4:3 * face.shape[1] // 4]
            neutral = True
            if len(tile_roi.shape) == 3:
                ch, cw = tile_roi.shape[:2]
                color = tile_roi[ch // 4:3 * ch // 4, cw // 4:3 * cw // 4]
                means = color.mean(axis=(0, 1))
                neutral = float(means.max() - means.min()) < 12
            if neutral and center.mean() > 150 and center.std() < 8 and face.std() > 8:
                error = float(cv2.matchTemplate(face, blank, cv2.TM_SQDIFF_NORMED)[0, 0])
                if error < 0.02:
                    return (31, 1.0 - error)

        # ═══════════════════════════════════════════════════════
        # v2.4: CLAHE 对比度增强
        #
        # 真实游戏截图的牌面对比度很低 (std ~21 vs 模板 std ~58),
        # 因为游戏引擎应用了主题着色、抗锯齿和缩放。
        # CLAHE 自适应直方图均衡化 — 局部增强对比度, 保留边缘。
        # 对比度提升: std 21→29, mean 132→191 (接近模板水平)
        # ═══════════════════════════════════════════════════════
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        # ═══════════════════════════════════════════════════════
        # v2.5: 归一化到模板尺寸 — 消除分辨率/缩放差异 (核心修复)
        #   实机单牌可能是 122x190 等任意尺寸, 统一 resize 到 80x129,
        #   让 SIFT 与模板匹配都在与模板相同的尺度上进行。
        # ═══════════════════════════════════════════════════════
        if crop_w != DEFAULT_TILE_W or crop_h != DEFAULT_TILE_H:
            interp = cv2.INTER_AREA if crop_w > DEFAULT_TILE_W else cv2.INTER_LINEAR
            norm = cv2.resize(gray, (DEFAULT_TILE_W, DEFAULT_TILE_H), interpolation=interp)
        else:
            norm = gray

        # v2.5: 自适应反转 — 仅深色牌面(mean<127)反转; 浅色实机(mean~170)不反转
        do_invert = bool(self._invert_dark and float(norm.mean()) < 127)
        norm_cc = cv2.bitwise_not(norm) if do_invert else norm

        # ── 通道 A: SIFT/ORB 特征候选 (归一化图上, 不再立即返回) ──
        # 模板是浅色: 深色 ROI 先反转回浅色再提特征, 保证 SIFT 与模板同主题
        sift_input = norm_cc if do_invert else norm
        sift_id, sift_good, sift_conf = -1, 0, 0.0
        nkp = len(self._sift.detect(sift_input, None)) if self._sift is not None else 0
        if self._use_sift and self.sift_ready:
            sift_result = self._match_sift(sift_input)
            if sift_result.tile_id >= 0 and sift_result.confidence > 0.15:
                sift_id = sift_result.tile_id
                sift_good = sift_result.good_matches
                sift_conf = sift_result.confidence
                self._sift_match_count += 1
            else:
                self._sift_fallback_count += 1
                if self._use_orb_fallback and self._orb is not None:
                    orb_result = self._match_orb(sift_input)
                    if orb_result.tile_id >= 0 and orb_result.confidence > 0.15:
                        sift_id = orb_result.tile_id
                        sift_good = orb_result.good_matches
                        sift_conf = orb_result.confidence
                        self._sift_match_count += 1

        # ── 通道 B: 归一化单尺度 CCOEFF (筒/索/字更准) ──
        cc_id, cc_conf = self._normalized_ccoeff(norm_cc)

        # ── v2.5 融合: SIFT 万子准 / CCOEFF 筒索字准 (实测 13/13) ──
        # 背面/空块: SIFT 关键点严重不足 → 拒识 (CCOEFF 会被白板高分误导)
        if self._use_sift and self.sift_ready and nkp < SIFT_MIN_MATCHES and sift_id < 0:
            Logger.debug(f"[Tiles] Reject blank/empty tile: SIFT kp={nkp}")
            self._match_count += 1
            self._match_time_total += time.perf_counter() - t0
            return (-1, 0.0)

        fused_id, fused_conf = -1, 0.0
        if sift_id >= 0 and cc_id >= 0 and sift_id == cc_id:
            fused_id, fused_conf = sift_id, max(sift_conf, cc_conf)   # 两路一致
        elif sift_id >= 0 and (0 <= sift_id <= 8 or sift_id == 34):
            fused_id, fused_conf = sift_id, sift_conf                # 万子共享"萬"字 → 信 SIFT
        elif sift_id >= 0 and cc_id >= 0:
            fused_id, fused_conf = cc_id, cc_conf     # SIFT 有候选(非万子), 筒/索/字信 CCOEFF
        elif cc_id >= 0 and cc_conf >= SIFT_FAIL_CCOEFF_MIN:
            fused_id, fused_conf = cc_id, cc_conf     # SIFT 失败仅靠 CCOEFF, 须达置信下限, 否则安全拒识
        elif sift_id >= 0:
            fused_id, fused_conf = sift_id, sift_conf

        if fused_id >= 0:
            if fused_id == 31:                                      # 白板排除
                self._match_count += 1
                self._match_time_total += time.perf_counter() - t0
                return (-1, 0.0)
            if fused_id in RED_DORA_MAP and ((self._red_dora_strict and fused_conf < 0.88) or do_invert):
                # 深色反转后红色信息丢失, 灰度无法可靠区分赤宝红点 → 反转时一律回落普通牌
                normal_id = RED_DORA_MAP[fused_id]
                Logger.debug(f"[Tiles] Red dora {fused_id} conf={fused_conf:.3f} -> {normal_id}")
                self._match_count += 1
                self._match_time_total += time.perf_counter() - t0
                return (normal_id, fused_conf)
            self._match_count += 1
            self._match_time_total += time.perf_counter() - t0
            return (fused_id, float(fused_conf))

        # 融合无结果 → 落到 v2.3 多尺度兜底 (在归一化图上, 按已决定的反转)
        gray = norm
        crop_h, crop_w = DEFAULT_TILE_H, DEFAULT_TILE_W

        # ═══════════════════════════════════════════════════════
        # v2.3: 模板匹配 (兜底)
        # SIFT/ORB 不可用或失败时 → 回退到传统模板匹配
        # ═══════════════════════════════════════════════════════
        if center_focus:
            cx, cy = crop_w // 2, crop_h // 2
            focus_w, focus_h = int(crop_w * 0.55), int(crop_h * 0.55)
            fx1, fy1 = cx - focus_w // 2, cy - focus_h // 2
            fx2, fy2 = fx1 + focus_w, fy1 + focus_h
            # 裁剪 ROI (保留原图用于边缘检测)
            gray_focus = gray[fy1:fy2, fx1:fx2]
            if gray_focus.size > 0:
                gray = gray_focus
                crop_h, crop_w = gray.shape[:2]
        else:
            gray_focus = None

        # ── v2.3: 自适应 scale 范围 ──
        #   根据 ROI 实际尺寸裁剪 scale 列表, 减少 40-50% matchTemplate 调用
        if self._adaptive_scales:
            scales = self._get_adaptive_scales(crop_w, crop_h)
        else:
            scales = self._scales

        # ── v2.3: 灰度反转 ──
        #   模板为浅色主题 (像素 ~200), 游戏实际渲染为深色 (~70)
        #   始终反转 — 实测反转后 CCORR 从 0.79 提升到 0.94
        inverted_gray = cv2.bitwise_not(gray) if do_invert else None

        # 生成 ROI 的边缘图 (用原始灰度, 边缘对颜色不敏感)
        roi_edges = cv2.Canny(gray, 30, 90) if self._use_edges else None

        best_id, best_conf = -1, 0.0
        second_id, second_conf = -1, 0.0

        # v2.3: 使用 TM_CCORR_NORMED — 对模板与真实截图的
        #        结构性差异比 TM_CCOEFF_NORMED 更鲁棒。
        #        实测: CCORR 0.855 vs CCOEFF 0.156 (同 tile, 同模板)
        method = cv2.TM_CCORR_NORMED

        # 选择模板集: 中心聚焦 vs 完整
        templates = self._focus_templates if center_focus and self._focus_templates else self._templates
        edge_templates = self._focus_edge_templates if center_focus and self._focus_edge_templates else self._edge_templates

        for tile_id, template in templates.items():
            tmpl_h, tmpl_w = template.shape[:2]
            size_ratio = max(crop_h / max(1, tmpl_h), tmpl_h / max(1, crop_h))
            if size_ratio > 2.5:
                continue

            for scale in scales:
                scaled_w = int(tmpl_w * scale)
                scaled_h = int(tmpl_h * scale)
                if scaled_w < 4 or scaled_h < 4:
                    continue
                if scaled_w > crop_w + 2 or scaled_h > crop_h + 2:
                    continue

                try:
                    # ── 边缘匹配 (Canny, 对形状差异容忍度高) ──
                    #    v2.3: 降权 0.95× (原 1.2×) — 边缘匹配不应
                    #    过度主导, 因为深色主题文字边缘可能与模板不同
                    if self._use_edges and tile_id in edge_templates:
                        edge_tmpl = cv2.resize(edge_templates[tile_id],
                                                (scaled_w, scaled_h))
                        result = cv2.matchTemplate(roi_edges, edge_tmpl, method)
                        _, max_val, _, _ = cv2.minMaxLoc(result)
                        edge_conf = float(max_val) * 0.95

                        if edge_conf > best_conf:
                            if best_id != tile_id:
                                second_id, second_conf = best_id, best_conf
                            best_conf = edge_conf
                            best_id = tile_id
                        elif edge_conf > second_conf and tile_id != best_id:
                            second_id = tile_id
                            second_conf = edge_conf

                    # ── 像素匹配 (反转优先 — 模板浅色/游戏深色) ──
                    scaled_tmpl = cv2.resize(template, (scaled_w, scaled_h))

                    # 反转后的 ROI 优先 (深色→浅色, 匹配浅色模板)
                    if inverted_gray is not None:
                        result = cv2.matchTemplate(inverted_gray, scaled_tmpl, method)
                        _, max_val, _, _ = cv2.minMaxLoc(result)
                        if max_val > best_conf:
                            if best_id != tile_id:
                                second_id, second_conf = best_id, best_conf
                            best_conf = float(max_val)
                            best_id = tile_id
                        elif max_val > second_conf and tile_id != best_id:
                            second_id = tile_id
                            second_conf = float(max_val)

                    # 原始灰度匹配 (兜底 — 浅色主题或模板自带深色)
                    result = cv2.matchTemplate(gray, scaled_tmpl, method)
                    _, max_val, _, _ = cv2.minMaxLoc(result)
                    if max_val > best_conf:
                        if best_id != tile_id:
                            second_id, second_conf = best_id, best_conf
                        best_conf = float(max_val)
                        best_id = tile_id
                    elif max_val > second_conf and tile_id != best_id:
                        second_id = tile_id
                        second_conf = float(max_val)

                except cv2.error:
                    continue

        self._match_count += 1
        self._match_time_total += time.perf_counter() - t0

        # ── v2.3: Margin 检查 ──
        #   top-2 置信度差距太小 → 模型无法可靠区分 → 标记 uncertain
        #   例外: 普通 5 ↔ 赤 5 对 — 仅靠红点区分, 本质上难以分辨,
        #         由赤宝牌降级逻辑处理, 不触发 margin 拒绝
        if best_id >= 0 and second_id >= 0:
            margin = best_conf - second_conf
            if margin < self._margin_threshold:
                is_red_pair = (
                    (best_id in RED_DORA_MAP and second_id == RED_DORA_MAP.get(best_id)) or
                    (second_id in RED_DORA_MAP and best_id == RED_DORA_MAP.get(second_id))
                )
                if not is_red_pair:
                    Logger.debug(
                        f"[Tiles] Low margin: best=({best_id},{best_conf:.3f}) "
                        f"second=({second_id},{second_conf:.3f}) margin={margin:.3f}"
                    )
                    return (-1, 0.0)

        # 白板(31)是空白牌面，匹配一切 → 排除
        if best_id == 31:
            return (-1, 0.0)

        # ── v2.3: 赤宝牌严格验证 ──
        #   赤 5 与普通 5 差异极小 (仅角落红点), 低置信度时不可靠
        #   自动降级为对应普通牌
        if self._red_dora_strict and best_id in RED_DORA_MAP:
            if best_conf < 0.88:  # 赤宝牌需要更高置信度
                normal_id = RED_DORA_MAP[best_id]
                Logger.debug(
                    f"[Tiles] Red dora {best_id}({TILE_NAMES[best_id]}) "
                    f"conf={best_conf:.3f} < 0.88 → downgrade to {normal_id}"
                )
                return (normal_id, best_conf)

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
        self._last_hand_boxes = []
        try:
            import cv2
        except ImportError:
            return []

        if hand_roi is None or hand_roi.size == 0:
            return []

        h, w = hand_roi.shape[:2]
        gray = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2GRAY) if len(hand_roi.shape) == 3 else hand_roi

        # v2.5: 优先用亮牌面连通域精确定位
        #   垂直投影峰受牌面左半黑色文字影响会系统性偏左约半张牌,
        #   连通域直接给出每张牌的精确外接框 (实测 14/14 对齐)。
        boxes = self._locate_hand_tiles(gray, n_expected)
        if boxes:
            results = []
            for (bx, by, bw, bh) in boxes:
                crop = hand_roi[by:by + bh, bx:bx + bw]
                if crop.size == 0:
                    continue
                tile_id, conf = self.match_single(crop)
                results.append((tile_id, conf))
                self._last_hand_boxes.append((bx, by, bw, bh))
            if results:
                return results

        # ── 回退: 自适应阈值 + 垂直投影峰值法 (连通域不可靠时) ──
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

        # 峰值检测 — 间距设为预期牌宽 (避免误检牌间空隙)
        peaks = self._find_peaks(projection, min_distance=max(10, w // 16))

        # 若指定了预期数量, 取最强的 N 个
        if n_expected is not None and len(peaks) > n_expected:
            peaks = sorted(peaks, key=lambda p: projection[p], reverse=True)[:n_expected]
            peaks = sorted(peaks)  # 重新按 x 排序

        n_tiles = n_expected or 14
        spacing = w / n_tiles
        tile_w = int(spacing * 0.94)
        tile_h = int(tile_w / TILE_REAL_ASPECT)
        if tile_h > h - 2:
            tile_h = h - 2
            tile_w = int(tile_h * TILE_REAL_ASPECT)
        tile_w = max(30, tile_w)
        half_w = tile_w // 2
        y_offset = max(0, (h - tile_h) // 2)
        peaks = [px for px in peaks if half_w <= px <= w - half_w]

        results = []
        for px in peaks:
            x1 = max(0, px - half_w)
            x2 = min(w, px + half_w)
            y1 = y_offset
            y2 = min(h, y1 + tile_h)
            crop = hand_roi[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            tile_id, conf = self.match_single(crop)
            results.append((tile_id, conf))
            self._last_hand_boxes.append((x1, y1, x2 - x1, y2 - y1))

        return results

    def _locate_hand_tiles(self, gray: np.ndarray,
                           n_expected: int = None) -> List[Tuple[int, int, int, int]]:
        """
        v2.5: 亮牌面连通域定位 (雀魂牌面浅色、桌面深色)。
        Otsu 分出亮牌面 → 外轮廓 → 按牌面尺寸/宽高比过滤 → 按 x 排序。
        Returns: [(x,y,w,h), ...] 从左到右; 不可靠返回 [] 由调用方回退投影法。
        """
        try:
            import cv2
        except ImportError:
            return []
        h, w = gray.shape[:2]
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        med_w = w / (n_expected or 14)
        boxes = []
        for c in contours:
            bx, by, bw, bh = cv2.boundingRect(c)
            if bw < med_w * 0.45 or bh < h * 0.5:   # 太小 → 噪点
                continue
            ar = bw / max(1, bh)
            if not (0.35 <= ar <= 0.95):            # 牌面宽高比约束
                continue
            boxes.append((int(bx), int(by), int(bw), int(bh)))
        boxes.sort(key=lambda b: b[0])
        if not (3 <= len(boxes) <= 15):             # 手牌数量合理区间
            return []
        if n_expected is not None and len(boxes) > n_expected:
            boxes = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)[:n_expected]
            boxes.sort(key=lambda b: b[0])
        return boxes

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

    def _normalized_ccoeff(self, norm_gray: np.ndarray) -> Tuple[int, float]:
        """
        v2.5: 归一化单尺度 CCOEFF 匹配。
        输入 norm_gray 已 resize 到 80x129 并按需反转, 与模板同尺度直接比较。
        筒/索/字牌上比 SIFT 更稳; 白板(31)排除以免霸榜。
        Returns: (tile_id, confidence>=0); 无模板返回 (-1, 0.0)
        """
        try:
            import cv2
        except ImportError:
            return (-1, 0.0)
        scores = {}
        gh, gw = norm_gray.shape[:2]
        for tid, tmpl in self._templates.items():
            if tid == 31:  # 白板空白, 匹配一切 → 排除
                continue
            if tmpl.shape != norm_gray.shape:
                tmpl = cv2.resize(tmpl, (gw, gh))
            r = cv2.matchTemplate(norm_gray, tmpl, cv2.TM_CCOEFF_NORMED)
            _, mv, _, _ = cv2.minMaxLoc(r)
            scores[tid] = float(mv)
        best_id = max(scores, key=lambda k: scores[k])
        best_val = scores[best_id]
        # 赤宝仅比普通牌多一个红点: 若赤宝以极弱优势(<0.02)压过对应普通牌, 取普通牌
        if best_id in RED_DORA_MAP:
            normal_id = RED_DORA_MAP[best_id]
            if normal_id in scores and best_val - scores[normal_id] < 0.02:
                best_id, best_val = normal_id, scores[normal_id]
        return best_id, max(0.0, best_val)

    # ── 自适应 scale ──

    def _get_adaptive_scales(self, crop_w: int, crop_h: int) -> List[float]:
        """
        根据 ROI 实际尺寸裁剪 scale 搜索范围。

        模板参考尺寸: 31×48 px (100% scale)
        ROI 尺寸: crop_w × crop_h

        只搜索估计 scale ±35% 范围内的等级, 减少 ~50% 的 matchTemplate 调用。

        Returns:
            裁剪后的 scale 列表 (至少 3 个)
        """
        # 估计 scale: ROI 宽度 / 模板参考宽度
        est_scale = crop_w / DEFAULT_TILE_W

        # 保留估计值 ±35% 内的 scale
        lo = est_scale * 0.65
        hi = est_scale * 1.35

        filtered = [s for s in self._scales if lo <= s <= hi]

        # 最少保留 3 个 scale (最接近估计值的)
        if len(filtered) < 3:
            # 补最近的 scale
            all_sorted = sorted(self._scales, key=lambda s: abs(s - est_scale))
            filtered = all_sorted[:5]  # 取最接近的 5 个

        return sorted(filtered)

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
                 template_dir: str = None,
                 margin_threshold: float = 0.005,
                 invert_dark: bool = True,
                 red_dora_strict: bool = True,
                 adaptive_scales: bool = True):
        self._matcher = TileTemplateMatcher(
            threshold=threshold,
            template_dir=template_dir,
            margin_threshold=margin_threshold,
            invert_dark=invert_dark,
            red_dora_strict=red_dora_strict,
            adaptive_scales=adaptive_scales,
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

    @property
    def hand_boxes(self):
        return list(getattr(self._matcher, '_last_hand_boxes', []))

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
