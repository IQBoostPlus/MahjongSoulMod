"""
动作执行器

将 GameAction 转换为实际的鼠标点击或键盘操作。
使用 pyautogui 进行屏幕坐标点击。
支持:
  - 窗口查找 (pygetwindow)
  - 按钮坐标估算 + OpenCV 模板匹配
  - 手牌区域点击
  - 拟人化延迟和随机偏移
  - 无 GUI 时的调试模式
"""

import time
import random
import os
from typing import Optional, Dict, Tuple

from utils.log import Logger

# ── GUI 库导入 ──

try:
    import pyautogui
    import pygetwindow as gw
    HAS_GUI = True
except ImportError:
    HAS_GUI = False
    Logger.warning("pyautogui/pygetwindow not installed — running in debug mode")

try:
    import cv2
    import numpy as np
    HAS_CV = True
except ImportError:
    HAS_CV = False


# ═══════════════════════════════════════════════════════════════
#  按钮模板管理器
# ═══════════════════════════════════════════════════════════════

class ButtonTemplate:
    """
    按钮图像模板

    按钮位置优先使用模板匹配，匹配失败时回退到相对坐标估算。
    模板图片放在 templates/ 目录，使用游戏截图裁剪。
    """

    TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

    # 按钮模板文件名 → 游戏动作名
    KNOWN_BUTTONS = {
        "pon":     "pon.png",
        "chi":     "chi.png",
        "kan":     "kan.png",
        "riichi":  "riichi.png",
        "ron":     "ron.png",
        "tsumo":   "tsumo.png",
        "pass":    "pass.png",
    }

    def __init__(self):
        self._templates: Dict[str, np.ndarray] = {}
        self._load_templates()

    def _load_templates(self):
        """加载所有已知按钮模板"""
        if not HAS_CV or not os.path.isdir(self.TEMPLATE_DIR):
            return
        for name, filename in self.KNOWN_BUTTONS.items():
            path = os.path.join(self.TEMPLATE_DIR, filename)
            if os.path.isfile(path):
                try:
                    img = cv2.imread(path, cv2.IMREAD_COLOR)
                    if img is not None:
                        self._templates[name] = img
                        Logger.debug(f"Loaded template: {name}")
                except Exception:
                    pass

    def find_button(self, name: str,
                    screenshot: Optional[np.ndarray] = None) -> Optional[Tuple[int, int]]:
        """在屏幕截图中查找按钮，返回 (center_x, center_y) 或 None"""
        if name not in self._templates:
            return None

        if screenshot is None and HAS_GUI:
            screenshot = self._capture_screen()

        if screenshot is None:
            return None

        template = self._templates[name]
        try:
            result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val > 0.75:  # 匹配置信度阈值
                h, w = template.shape[:2]
                center_x = max_loc[0] + w // 2
                center_y = max_loc[1] + h // 2
                return (center_x, center_y)
        except Exception:
            pass

        return None

    @staticmethod
    def _capture_screen() -> Optional[np.ndarray]:
        """获取全屏截图"""
        try:
            img = pyautogui.screenshot()
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════════
#  ActionExecutor — 主执行器
# ═══════════════════════════════════════════════════════════════

class ActionExecutor:
    """
    动作执行器

    通过 pyautogui 在游戏窗口区域执行鼠标点击。
    优先使用图像模板匹配查找按钮，回退到相对坐标估算。
    """

    # 按钮估测位置 (窗口相对坐标) — 模板匹配失败时的 fallback
    BUTTON_POSITIONS: Dict[str, Tuple[float, float]] = {
        "pon":     (0.32, 0.78),
        "chi":     (0.41, 0.78),
        "kan":     (0.50, 0.78),
        "riichi":  (0.28, 0.78),
        "ron":     (0.59, 0.78),
        "tsumo":   (0.68, 0.78),
        "pass":    (0.35, 0.45),
    }

    # 手牌区域 (窗口相对)
    HAND_AREA_Y_RATIO = 0.72       # 手牌区顶部 (相对窗口高度)
    HAND_AREA_H_RATIO = 0.22       # 手牌区高度
    HAND_AREA_X_RATIO = 0.05       # 手牌区左边距
    HAND_AREA_W_RATIO = 0.90       # 手牌区宽度

    def __init__(self):
        self._window = None
        self._window_title = "雀魂"
        self._last_action_time = 0.0
        self._enabled = True
        self._templates = ButtonTemplate()

        # 统计数据
        self._action_count = 0
        self._fail_count = 0

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def fail_count(self) -> int:
        return self._fail_count

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        Logger.info(f"[Action] {'ENABLED' if enabled else 'DISABLED'}")

    def execute(self, action) -> bool:
        """执行一个游戏动作"""
        from ai.engine import GameAction, ActionType

        if not self._enabled:
            Logger.info(f"[Action] Skipped — disabled ({action.action.value})")
            return False

        self._action_count += 1

        if not HAS_GUI:
            Logger.info(
                f"[Action] WOULD: {action.action.value} tile={action.tile}"
            )
            return True

        try:
            # 拟人化延迟
            self._human_delay()

            # 查找窗口
            if not self._find_window():
                Logger.warning("[Action] Game window not found")
                self._fail_count += 1
                return False

            # 分发动作
            if action.action == ActionType.DISCARD:
                return self._click_tile(action.tile)
            elif action.action == ActionType.RIICHI:
                # 先切牌，再点立直按钮
                ok = self._click_tile(action.tile)
                time.sleep(random.uniform(0.3, 0.6))
                return ok and self._click_button("riichi")
            elif action.action == ActionType.PON:
                return self._click_button("pon")
            elif action.action == ActionType.CHI:
                return self._click_button("chi")
            elif action.action == ActionType.KAN:
                return self._click_button("kan")
            elif action.action == ActionType.RON:
                return self._click_button("ron")
            elif action.action == ActionType.TSUMO:
                return self._click_button("tsumo")
            elif action.action == ActionType.PASS:
                return self._click_button("pass")
            else:
                Logger.warning(f"[Action] Unknown action: {action.action}")
                self._fail_count += 1
                return False

        except Exception as e:
            Logger.error(f"[Action] Failed: {e}")
            self._fail_count += 1
            return False

    # ── 窗口管理 ──

    def _find_window(self) -> bool:
        """查找游戏窗口 (带缓存)"""
        if self._window is not None:
            try:
                if self._window.visible:
                    return True
            except Exception:
                self._window = None

        try:
            # 尝试多个可能的窗口标题
            titles = [self._window_title, "Mahjong Soul", "雀魂麻将", "Majsoul"]
            for title in titles:
                windows = gw.getWindowsWithTitle(title)
                for w in windows:
                    if w.visible and w.width > 400 and w.height > 300:
                        self._window = w
                        Logger.info(
                            f"[Action] Found window: '{w.title}' "
                            f"({w.width}x{w.height} at {w.left},{w.top})"
                        )
                        return True
        except Exception:
            pass

        return False

    def _get_window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """获取窗口区域 (x, y, width, height)"""
        if not self._window:
            return None
        try:
            return (
                self._window.left, self._window.top,
                self._window.width, self._window.height
            )
        except Exception:
            return None

    # ── 手牌点击 ──

    def _click_tile(self, tile_index: int) -> bool:
        """
        点击手牌中的第 tile_index 张牌

        策略: 将手牌区域均匀分割, 根据 tile_index 确定位置。
        后续可结合图像识别精确定位每张牌。
        """
        rect = self._get_window_rect()
        if not rect:
            return False

        x, y, w, h = rect

        # 手牌区域
        tile_area_y = y + int(h * self.HAND_AREA_Y_RATIO)
        tile_area_h = int(h * self.HAND_AREA_H_RATIO)
        tile_area_x = x + int(w * self.HAND_AREA_X_RATIO)
        tile_area_w = int(w * self.HAND_AREA_W_RATIO)

        # 手牌最多 14 张，均匀分布
        max_tiles = 14
        tile_step = tile_area_w // max_tiles
        idx = min(tile_index, max_tiles - 1)

        # 计算点击坐标 (加随机偏移)
        tx = tile_area_x + tile_step * idx + random.randint(
            max(3, tile_step // 4),
            max(5, tile_step - tile_step // 4)
        )
        ty = tile_area_y + random.randint(
            max(3, tile_area_h // 4),
            max(5, tile_area_h - tile_area_h // 4)
        )

        # 额外小随机偏移
        tx += random.randint(-8, 8)
        ty += random.randint(-5, 5)

        self._move_and_click(tx, ty)
        Logger.debug(f"[Action] Clicked tile #{tile_index} at ({tx}, {ty})")
        return True

    # ── 按钮点击 ──

    def _click_button(self, button_name: str) -> bool:
        """点击游戏 UI 按钮"""
        rect = self._get_window_rect()
        if not rect:
            return False

        x, y, w, h = rect

        # ── 方法1: 模板匹配 ──
        if HAS_CV:
            pos = self._templates.find_button(button_name)
            if pos is not None:
                bx, by = pos
                bx += random.randint(-3, 3)
                by += random.randint(-3, 3)
                self._move_and_click(bx, by)
                Logger.debug(
                    f"[Action] Template-matched '{button_name}' at ({bx}, {by})"
                )
                return True

        # ── 方法2: 相对坐标估算 ──
        ratio_pos = self.BUTTON_POSITIONS.get(button_name)
        if ratio_pos is None:
            Logger.warning(f"[Action] Unknown button: '{button_name}'")
            return False

        bx = x + int(w * ratio_pos[0]) + random.randint(-8, 8)
        by = y + int(h * ratio_pos[1]) + random.randint(-5, 5)

        self._move_and_click(bx, by)
        Logger.debug(f"[Action] Estimated '{button_name}' at ({bx}, {by})")
        return True

    # ── 鼠标操作 ──

    def _move_and_click(self, target_x: int, target_y: int):
        """安全的鼠标移动 + 点击 (模拟人类移动轨迹)"""
        try:
            cur_x, cur_y = pyautogui.position()

            # 使用贝塞尔曲线式的两段移动 (更自然)
            mid_x = cur_x + (target_x - cur_x) * random.uniform(0.4, 0.7)
            mid_y = cur_y + (target_y - cur_y) * random.uniform(0.3, 0.6)

            pyautogui.moveTo(mid_x, mid_y, duration=random.uniform(0.04, 0.12))
            pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.03, 0.10))

            # 悬停
            time.sleep(random.uniform(0.02, 0.06))

            # 点击
            pyautogui.click()
        except Exception:
            pass

    # ── 延迟 ──

    def _human_delay(self):
        """
        拟人化延迟

        模拟人类的反应时间:
          - 基础间隔: 200ms
          - 随即延迟: 300-1000ms (正态分布偏)
          - 复杂决策额外延迟
        """
        elapsed = time.time() - self._last_action_time

        # 最小间隔
        min_gap = 0.2
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)

        # 正态分布延迟 (mean=600ms, sigma=200ms)
        delay = abs(random.gauss(0.6, 0.2))
        delay = max(0.25, min(1.5, delay))
        time.sleep(delay)

        self._last_action_time = time.time()

    # ── 工具 ──

    def click_at(self, x: int, y: int, duration: float = 0.3):
        """在指定坐标点击 (外部调用用)"""
        self._move_and_click(x, y)
        Logger.debug(f"[Action] Manual click at ({x}, {y})")
