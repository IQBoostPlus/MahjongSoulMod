"""
按钮检测器 — Airtest 特征匹配 + OpenCV 模板匹配 + 坐标回退

只负责"按钮在不在屏幕"和"在哪", 不涉及其它识别。

保留 Airtest 的原因: 其 SIFT/SURF 特征匹配对文字按钮的缩放不变性,
在不同窗口大小下表现明显优于纯模板匹配。

Tier 链:
  1. Airtest Template.exists() — SIFT/SURF 多尺度, ~50ms
  2. OpenCV cv2.matchTemplate() — 像素级模板匹配, ~5ms
  3. 窗口相对坐标估算 — 数学计算, ~0ms

用法:
    detector = ButtonDetector()
    visible = detector.detect_buttons(screen_frame)
    pos = detector.find_button_position("riichi", screen_frame)
"""

import os
import time
import random
from typing import Dict, List, Optional, Tuple

import numpy as np

from utils.log import Logger


# ═══════════════════════════════════════════════════════════════
#  ButtonDetector
# ═══════════════════════════════════════════════════════════════

class ButtonDetector:
    """
    游戏 UI 按钮检测器。

    检测 7 种操作按钮: pon, chi, kan, riichi, ron, tsumo, pass
    """

    # 模板目录
    TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

    # 已知按钮
    BUTTON_NAMES = ["pon", "chi", "kan", "riichi", "ron", "tsumo", "pass"]

    # 按钮模板文件名
    BUTTON_TEMPLATES = {
        "pon": "pon.png", "chi": "chi.png", "kan": "kan.png",
        "riichi": "riichi.png", "ron": "ron.png",
        "tsumo": "tsumo.png", "pass": "pass.png",
    }

    # 窗口相对坐标回退 (x_ratio, y_ratio)
    FALLBACK_POSITIONS = {
        "pon":    (0.20, 0.85),
        "chi":    (0.34, 0.85),
        "kan":    (0.48, 0.85),
        "riichi": (0.28, 0.85),
        "ron":    (0.62, 0.85),
        "tsumo":  (0.76, 0.85),
        "pass":   (0.50, 0.65),
    }

    def __init__(self, template_dir: str = None):
        self._template_dir = template_dir or self.TEMPLATE_DIR

        # Airtest 模板
        self._air_templates: Dict[str, object] = {}
        self._has_airtest = False

        # OpenCV 模板 (回退)
        self._cv_templates: Dict[str, np.ndarray] = {}
        self._has_cv = False

        self._load_templates()

    # ── 模板加载 ──

    def _load_templates(self):
        """加载 Airtest 和 OpenCV 模板"""
        # OpenCV
        try:
            import cv2
            self._has_cv = True
        except ImportError:
            Logger.debug("[Buttons] OpenCV not available")

        # Airtest
        try:
            from airtest.core.api import Template
            self._has_airtest = True
        except ImportError:
            Logger.debug("[Buttons] Airtest not available, using OpenCV only")

        if not os.path.isdir(self._template_dir):
            Logger.warning(f"[Buttons] Template dir not found: {self._template_dir}")
            return

        loaded = 0
        for name, filename in self.BUTTON_TEMPLATES.items():
            path = os.path.join(self._template_dir, filename)
            if not os.path.isfile(path):
                continue

            try:
                if self._has_airtest:
                    from airtest.core.api import Template
                    self._air_templates[name] = Template(path, threshold=0.65)

                if self._has_cv:
                    import cv2
                    img = cv2.imread(path, cv2.IMREAD_COLOR)
                    if img is not None:
                        self._cv_templates[name] = img

                loaded += 1
            except Exception as e:
                Logger.debug(f"[Buttons] Failed to load {name}: {e}")

        if loaded > 0:
            Logger.info(f"[Buttons] Loaded {loaded}/{len(self.BUTTON_TEMPLATES)} button templates")
        else:
            Logger.warning("[Buttons] No button templates loaded — using coordinate fallback only")

    # ── 检测 API ──

    def detect_buttons(self, screen: np.ndarray) -> List[str]:
        """
        检测屏幕中可见的操作按钮。

        Args:
            screen: 按钮区域截图 (或全屏截图)

        Returns:
            可见按钮名列表 (按优先级排序: pon, chi, kan, riichi, ron, tsumo, pass)
        """
        visible = []

        for name in self.BUTTON_NAMES:
            pos = self._find_button_internal(name, screen)
            if pos is not None:
                visible.append(name)

        return visible

    def find_button_position(self, name: str,
                               screen: np.ndarray) -> Optional[Tuple[int, int]]:
        """查找指定按钮的屏幕坐标 (中心点)"""
        return self._find_button_internal(name, screen)

    # ── 内部三级匹配 ──

    def _find_button_internal(self, name: str,
                                 screen: np.ndarray) -> Optional[Tuple[int, int]]:
        """
        Tier 1: Airtest feature matching
        Tier 2: OpenCV template matching
        Tier 3: Coordinate fallback
        """
        # Tier 1: Airtest SIFT/SURF
        if self._has_airtest and name in self._air_templates:
            pos = self._match_airtest(name, screen)
            if pos is not None:
                return pos

        # Tier 2: OpenCV template matching
        if self._has_cv and name in self._cv_templates:
            pos = self._match_opencv(name, screen)
            if pos is not None:
                return pos

        # Tier 3: 坐标估算 (需要窗口位置)
        if name in self.FALLBACK_POSITIONS:
            h, w = screen.shape[:2]
            rx, ry = self.FALLBACK_POSITIONS[name]
            return (int(w * rx), int(h * ry))

        return None

    def _match_airtest(self, name: str,
                        screen: np.ndarray) -> Optional[Tuple[int, int]]:
        """Airtest 特征匹配"""
        try:
            from airtest.core.api import exists

            template = self._air_templates.get(name)
            if template is None:
                return None

            # Airtest 的 exists() 不支持 screen= 参数, 改用 match_in()
            try:
                pos = template.match_in(screen)
            except AttributeError:
                # 回退: 直接传入屏幕截图
                import cv2
                pos = exists(template)

            if pos:
                # exists 返回 (left, top, right, bottom)
                if len(pos) == 4:
                    cx = (pos[0] + pos[2]) // 2
                    cy = (pos[1] + pos[3]) // 2
                    return (cx, cy)
                elif len(pos) == 2:
                    return (int(pos[0]), int(pos[1]))
        except Exception as e:
            Logger.debug(f"[Buttons] Airtest match failed for '{name}': {e}")

        return None

    def _match_opencv(self, name: str,
                       screen: np.ndarray) -> Optional[Tuple[int, int]]:
        """OpenCV 模板匹配"""
        try:
            import cv2

            template = self._cv_templates.get(name)
            if template is None or screen is None:
                return None

            h_t, w_t = template.shape[:2]
            h_s, w_s = screen.shape[:2]

            # 模板不能大于目标图像
            if h_t > h_s or w_t > w_s:
                # 缩小模板以匹配
                scale = min(h_s / h_t, w_s / w_t) * 0.9
                if scale < 0.3:
                    return None
                new_w, new_h = int(w_t * scale), int(h_t * scale)
                template = cv2.resize(template, (new_w, new_h))
                h_t, w_t = template.shape[:2]

            if h_t > h_s or w_t > w_s:
                return None

            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val > 0.70:
                cx = max_loc[0] + w_t // 2
                cy = max_loc[1] + h_t // 2
                return (cx, cy)
        except Exception as e:
            Logger.debug(f"[Buttons] OpenCV match failed for '{name}': {e}")

        return None

    @property
    def has_airtest(self) -> bool:
        return self._has_airtest

    @property
    def has_cv(self) -> bool:
        return self._has_cv


# ═══════════════════════════════════════════════════════════════
#  NullButtonDetector — 监听模式无操作
# ═══════════════════════════════════════════════════════════════

class NullButtonDetector:
    """空操作按钮检测器 (--listen-only 模式)"""
    def detect_buttons(self, screen) -> List[str]:
        return []

    def find_button_position(self, name, screen) -> Optional[Tuple[int, int]]:
        return None
