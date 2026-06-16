"""
Airtest 图像识别动作执行器

使用网易 Airtest 框架替代原始 OpenCV 模板匹配，优势:
  - 多尺度特征匹配 (SIFT/ORB): 适应窗口大小变化
  - 内置截图引擎: 速度快于 pyautogui
  - 自适应阈值: 减少误匹配
  - 统一桌面/移动 API

回退策略:
  1. Airtest 模板匹配 (最高精度)
  2. OpenCV 模板匹配 (兼容旧版)
  3. 窗口相对坐标估算 (兜底)
"""

import time
import random
import os
import sys
from typing import Optional, Dict, Tuple, List

from utils.log import Logger

# ── Airtest 导入 ──
try:
    from airtest.core.api import Template, touch, exists, snapshot as air_snapshot
    from airtest.core.settings import Settings as AirSettings
    AirSettings.THRESHOLD = 0.65        # 默认匹配阈值
    AirSettings.FIND_TIMEOUT = 2        # 查找超时
    AirSettings.CVSTRATEGY = ["surf", "sift", "orb"]  # 特征匹配策略
    HAS_AIRTEST = True
except ImportError:
    HAS_AIRTEST = False
    Template = None
    Logger.warning("Airtest not installed — falling back to OpenCV")

# ── 传统 GUI 库 ──
try:
    import pyautogui
    import pygetwindow as gw
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

try:
    import cv2
    import numpy as np
    HAS_CV = True
except ImportError:
    HAS_CV = False


# ═══════════════════════════════════════════════════════════════
#  AirtestActionExecutor
# ═══════════════════════════════════════════════════════════════

class AirtestActionExecutor:
    """
    基于 Airtest 的动作执行器

    支持:
      - Airtest 多尺度特征匹配 (最优)
      - OpenCV 模板匹配 (兼容)
      - 窗口坐标估算 (兜底)
      - 鼠标拟人化轨迹
    """

    # 按钮估测位置 (窗口相对坐标) — 所有识别方法都失败时的兜底
    BUTTON_POSITIONS: Dict[str, Tuple[float, float]] = {
        "pon":    (0.20, 0.72),
        "chi":    (0.34, 0.72),
        "kan":    (0.48, 0.72),
        "riichi": (0.28, 0.80),
        "ron":    (0.62, 0.72),
        "tsumo":  (0.76, 0.72),
        "pass":   (0.50, 0.60),
    }

    # 手牌区域 (窗口相对)
    HAND_AREA_Y_TOP    = 0.72
    HAND_AREA_Y_BOTTOM = 0.88
    HAND_AREA_X_LEFT   = 0.03
    HAND_AREA_X_RIGHT  = 0.97

    # 模板目录
    TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

    # 模板名 → 文件名
    BUTTON_TEMPLATES = {
        "pon": "pon.png", "chi": "chi.png", "kan": "kan.png",
        "riichi": "riichi.png", "ron": "ron.png",
        "tsumo": "tsumo.png", "pass": "pass.png",
    }

    def __init__(self):
        self._window = None
        self._window_title = "雀魂"
        self._last_action_time = 0.0
        self._enabled = True

        # Airtest 模板缓存
        self._air_templates: Dict[str, "Template"] = {}
        # OpenCV 模板缓存 (fallback)
        self._cv_templates: Dict[str, np.ndarray] = {}
        self._load_templates()

        # 统计
        self._action_count = 0
        self._fail_count = 0
        self._match_method = ""  # 记录上次用的识别方法

        # 截图缓存
        self._last_screenshot = None
        self._last_screenshot_time = 0.0

    # ── 属性 ──

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def fail_count(self) -> int:
        return self._fail_count

    @property
    def last_match_method(self) -> str:
        return self._match_method

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        Logger.info(f"[Airtest] {'ENABLED' if enabled else 'DISABLED'}")

    # ── 模板加载 ──

    def _load_templates(self):
        """加载所有按钮模板"""
        if not os.path.isdir(self.TEMPLATE_DIR):
            Logger.warning(f"[Airtest] Template dir not found: {self.TEMPLATE_DIR}")
            return

        for name, filename in self.BUTTON_TEMPLATES.items():
            path = os.path.join(self.TEMPLATE_DIR, filename)
            if not os.path.isfile(path):
                continue
            try:
                if HAS_AIRTEST:
                    self._air_templates[name] = Template(path, threshold=0.65)
                if HAS_CV:
                    img = cv2.imread(path, cv2.IMREAD_COLOR)
                    if img is not None:
                        self._cv_templates[name] = img
                Logger.debug(f"[Airtest] Loaded template: {name}")
            except Exception as e:
                Logger.debug(f"[Airtest] Failed to load {name}: {e}")

    # ── 主执行 ──

    def execute(self, action) -> bool:
        """执行游戏动作"""
        from ai.engine import GameAction, ActionType

        if not self._enabled:
            Logger.info(f"[Airtest] Skipped — disabled ({action.action.value})")
            return False

        self._action_count += 1

        if not HAS_GUI:
            Logger.info(f"[Airtest] WOULD: {action.action.value} tile={action.tile}")
            return True

        try:
            self._human_delay()

            if not self._find_window():
                Logger.warning("[Airtest] Game window not found")
                self._fail_count += 1
                return False

            if action.action == ActionType.DISCARD:
                return self._click_tile(action.tile)
            elif action.action == ActionType.RIICHI:
                ok = self._click_tile(action.tile)
                time.sleep(random.uniform(0.3, 0.6))
                return ok and self._click_button("riichi")
            elif action.action in (ActionType.PON, ActionType.CHI,
                                    ActionType.KAN, ActionType.RON,
                                    ActionType.TSUMO, ActionType.PASS):
                btn = action.action.value
                return self._click_button(btn)
            else:
                Logger.warning(f"[Airtest] Unknown action: {action.action}")
                self._fail_count += 1
                return False

        except Exception as e:
            Logger.error(f"[Airtest] Failed: {e}")
            self._fail_count += 1
            return False

    # ── 屏幕截图 ──

    def _capture(self):
        """截图 (带短缓存避免频繁截图)"""
        now = time.time()
        if self._last_screenshot is not None and now - self._last_screenshot_time < 0.3:
            return self._last_screenshot

        if HAS_AIRTEST:
            try:
                self._last_screenshot = air_snapshot()
                self._last_screenshot_time = now
                return self._last_screenshot
            except Exception:
                pass

        if HAS_GUI:
            try:
                img = pyautogui.screenshot()
                self._last_screenshot = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                self._last_screenshot_time = now
                return self._last_screenshot
            except Exception:
                pass

        return None

    # ── 按钮识别 (Airtest → OpenCV → 坐标估算) ──

    def _find_button(self, name: str) -> Optional[Tuple[int, int]]:
        """
        三级识别策略: Airtest → OpenCV → 坐标估算
        返回屏幕绝对坐标 (cx, cy)
        """
        # ── Level 1: Airtest 多尺度特征匹配 ──
        if HAS_AIRTEST and name in self._air_templates:
            try:
                self._capture()  # Airtest 内部使用最后的截图
                pos = exists(self._air_templates[name])
                if pos:
                    self._match_method = "airtest"
                    # exists 返回 (left, top, right, bottom) 的矩形中心
                    cx = (pos[0] + pos[2]) // 2
                    cy = (pos[1] + pos[3]) // 2
                    return (cx, cy)
            except Exception:
                pass

        # ── Level 2: OpenCV 模板匹配 ──
        if HAS_CV and name in self._cv_templates:
            screen = self._capture()
            if screen is not None:
                template = self._cv_templates[name]
                try:
                    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val > 0.70:
                        self._match_method = "opencv"
                        h, w = template.shape[:2]
                        return (max_loc[0] + w // 2, max_loc[1] + h // 2)
                except Exception:
                    pass

        # ── Level 3: 窗口相对坐标估算 ──
        rect = self._get_window_rect()
        if rect and name in self.BUTTON_POSITIONS:
            self._match_method = "fallback"
            rx, ry = self.BUTTON_POSITIONS[name]
            return (
                rect[0] + int(rect[2] * rx) + random.randint(-6, 6),
                rect[1] + int(rect[3] * ry) + random.randint(-4, 4),
            )

        return None

    # ── 手牌点击 ──

    def _click_tile(self, tile_index: int) -> bool:
        """点击手牌中的第 N 张牌 (0-based)"""
        rect = self._get_window_rect()
        if not rect:
            return False

        x, y, w, h = rect
        area_x = x + int(w * self.HAND_AREA_X_LEFT)
        area_w = int(w * (self.HAND_AREA_X_RIGHT - self.HAND_AREA_X_LEFT))
        area_y = y + int(h * self.HAND_AREA_Y_TOP)
        area_h = int(h * (self.HAND_AREA_Y_BOTTOM - self.HAND_AREA_Y_TOP))

        max_tiles = 14
        step = area_w // max_tiles
        idx = min(tile_index, max_tiles - 1)

        tx = area_x + step * idx + random.randint(max(3, step // 4), max(5, step - step // 4))
        ty = area_y + random.randint(max(3, area_h // 4), max(5, area_h - area_h // 4))
        tx += random.randint(-6, 6)
        ty += random.randint(-3, 3)

        self._move_and_click(tx, ty)
        Logger.debug(f"[Airtest] Tile #{tile_index} @ ({tx}, {ty})")
        return True

    # ── 按钮点击 ──

    def _click_button(self, button_name: str) -> bool:
        """识别并点击游戏按钮"""
        pos = self._find_button(button_name)
        if pos is None:
            Logger.warning(f"[Airtest] Button not found: '{button_name}'")
            self._fail_count += 1
            return False

        bx, by = pos
        bx += random.randint(-3, 3)
        by += random.randint(-3, 3)
        self._move_and_click(bx, by)
        Logger.info(
            f"[Airtest] Clicked '{button_name}' @ ({bx}, {by}) [{self._match_method}]"
        )
        return True

    # ── 窗口管理 ──

    def _find_window(self) -> bool:
        """查找游戏窗口"""
        if self._window is not None:
            try:
                if self._window.visible:
                    return True
            except Exception:
                self._window = None

        try:
            all_windows = gw.getAllWindows()
            candidates = []

            for w in all_windows:
                try:
                    title = w.title or ""
                except Exception:
                    continue

                is_game = any(kw in title for kw in [
                    "雀魂", "MahjongSoul", "Mahjong Soul",
                    "mahjongsoul", "mahjong_soul", "Jansou",
                ])
                if not is_game and "Majsoul" in title:
                    is_game = True

                if not is_game:
                    continue

                skip_kw = [
                    "Visual Studio", "Code", "Terminal", "终端",
                    "PowerShell", "cmd", "Claude", "Cursor",
                    "Sublime", "Notepad", "记事本", "AutoMod",
                    "修复", "MOD", "mod", "build", "Python",
                ]
                if any(kw in title for kw in skip_kw):
                    continue

                if w.visible and w.width > 600 and w.height > 400:
                    candidates.append((w.width * w.height, w))

            if candidates:
                candidates.sort(key=lambda x: -x[0])
                self._window = candidates[0][1]
                w = self._window
                Logger.info(
                    f"[Airtest] Found window: '{w.title}' "
                    f"({w.width}x{w.height} @ {w.left},{w.top})"
                )
                return True
        except Exception:
            pass

        return False

    def _get_window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """获取窗口区域"""
        if not self._window:
            return None
        try:
            return (self._window.left, self._window.top,
                    self._window.width, self._window.height)
        except Exception:
            return None

    # ── 鼠标操作 ──

    def _move_and_click(self, tx: int, ty: int):
        """拟人化鼠标移动 + 点击"""
        try:
            cur_x, cur_y = pyautogui.position()
            mid_x = cur_x + (tx - cur_x) * random.uniform(0.4, 0.7)
            mid_y = cur_y + (ty - cur_y) * random.uniform(0.3, 0.6)
            pyautogui.moveTo(mid_x, mid_y, duration=random.uniform(0.04, 0.12))
            pyautogui.moveTo(tx, ty, duration=random.uniform(0.03, 0.10))
            time.sleep(random.uniform(0.02, 0.06))
            pyautogui.click()
        except Exception:
            pass

    # ── 拟人化延迟 ──

    def _human_delay(self):
        """拟人化反应延迟"""
        elapsed = time.time() - self._last_action_time
        if elapsed < 0.2:
            time.sleep(0.2 - elapsed)
        delay = abs(random.gauss(0.6, 0.2))
        delay = max(0.25, min(1.5, delay))
        time.sleep(delay)
        self._last_action_time = time.time()

    # ── 工具 ──

    def click_at(self, x: int, y: int):
        """在指定坐标点击"""
        self._move_and_click(x, y)

    def save_template(self, name: str, x1: int, y1: int, x2: int, y2: int):
        """
        从当前屏幕截取区域并保存为模板
        用于一键采集新按钮图像
        """
        screen = self._capture()
        if screen is None:
            Logger.error("[Airtest] Cannot capture screen")
            return False

        region = screen[y1:y2, x1:x2]
        os.makedirs(self.TEMPLATE_DIR, exist_ok=True)
        path = os.path.join(self.TEMPLATE_DIR, f"{name}.png")
        cv2.imwrite(path, region)
        Logger.info(f"[Airtest] Template saved: {path} ({x2-x1}x{y2-y1})")

        # 重新加载
        self._load_templates()
        return True
