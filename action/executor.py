"""
动作执行器

将 GameAction 转换为实际的鼠标点击或键盘操作。
使用 pyautogui 进行屏幕坐标点击。
"""

import time
import random
import subprocess
import os
from typing import Optional

from ai.engine import GameAction, ActionType
from utils.log import Logger

# 尝试导入 pyautogui, 不存在则使用 fallback
try:
    import pyautogui
    import pygetwindow as gw
    HAS_GUI = True
except ImportError:
    HAS_GUI = False
    Logger.warning("pyautogui not installed, using debug mode")


class ActionExecutor:
    """
    动作执行器

    通过 pyautogui 在指定游戏窗口区域执行鼠标点击。
    支持窗口查找、区域坐标定位、随机化延迟和点击位置偏移。
    """

    def __init__(self):
        self._window = None
        self._window_title = "雀魂"
        self._last_action_time = 0.0
        self._enabled = True

        # 按钮区域缓存 (在窗口中的相对位置)
        self._button_positions = {}
        self._hand_tile_positions = {}  # 手牌位置

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def execute(self, action: GameAction) -> bool:
        """执行一个游戏动作"""
        if not self._enabled:
            Logger.info(f"[Action] Skipped ({action.action.value})")
            return False

        if not HAS_GUI:
            Logger.info(f"[Action] WOULD: {action.action.value} tile={action.tile}")
            return True

        try:
            # 人机化延迟
            self._human_delay()

            # 查找窗口
            if not self._find_window():
                Logger.error("[Action] Game window not found")
                return False

            # 执行具体动作
            if action.action == ActionType.DISCARD:
                return self._click_tile(action.tile)
            elif action.action == ActionType.RIICHI:
                return self._click_tile(action.tile) and self._click_button("riichi")
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
                return False

        except Exception as e:
            Logger.error(f"[Action] Failed: {e}")
            return False

    def _find_window(self) -> bool:
        """查找游戏窗口"""
        if self._window is not None:
            try:
                if self._window.isActive:
                    return True
            except:
                pass

        try:
            windows = gw.getWindowsWithTitle(self._window_title)
            for w in windows:
                if w.visible:
                    self._window = w
                    return True
            return False
        except:
            return False

    def _get_window_rect(self) -> Optional[tuple]:
        """获取窗口区域 (x, y, width, height)"""
        if not self._window:
            return None
        try:
            return (
                self._window.left, self._window.top,
                self._window.width, self._window.height
            )
        except:
            return None

    def _click_tile(self, tile_id: int) -> bool:
        """点击手牌中的某张牌"""
        rect = self._get_window_rect()
        if not rect:
            return False

        x, y, w, h = rect

        # 手牌区域通常在窗口底部 25% 区域
        tile_area_y = y + int(h * 0.72)
        tile_area_h = int(h * 0.22)
        tile_area_x = x + int(w * 0.05)
        tile_area_w = int(w * 0.90)

        # 手牌最多14张，均匀分布
        hand_count = 14  # 最大
        tile_step = tile_area_w // hand_count

        # 模拟选中某张牌: 点击手牌区域
        tx = tile_area_x + tile_step * (tile_id % 14) + random.randint(5, tile_step - 5)
        ty = tile_area_y + random.randint(5, tile_area_h - 5)

        # 小随机偏移更拟人
        self._move_and_click(tx + random.randint(-3, 3), ty + random.randint(-3, 3))
        Logger.info(f"[Action] Clicked tile area ({tile_id}) at ({tx}, {ty})")
        return True

    def _click_button(self, button_name: str) -> bool:
        """点击按钮"""
        rect = self._get_window_rect()
        if not rect:
            return False

        x, y, w, h = rect

        # 按钮位置基于游戏窗口相对位置估算
        button_positions = {
            "pon":    (0.35, 0.80),
            "chi":    (0.45, 0.80),
            "kan":    (0.55, 0.80),
            "riichi": (0.30, 0.80),
            "ron":    (0.60, 0.80),
            "tsumo":  (0.65, 0.80),
            "pass":   (0.40, 0.45),
            "discard": (0.50, 0.85),
        }

        pos = button_positions.get(button_name)
        if not pos:
            Logger.warning(f"[Action] Unknown button: {button_name}")
            return False

        bx = x + int(w * pos[0]) + random.randint(-5, 5)
        by = y + int(h * pos[1]) + random.randint(-5, 5)

        self._move_and_click(bx, by)
        Logger.info(f"[Action] Clicked {button_name} at ({bx}, {by})")
        return True

    def _move_and_click(self, x: int, y: int):
        """安全的鼠标移动+点击"""
        try:
            # 首先移到一个中间位置 (更自然)
            mid_x = x + random.randint(-100, 100)
            mid_y = y + random.randint(-50, 50)
            pyautogui.moveTo(mid_x, mid_y, duration=random.uniform(0.05, 0.15))

            # 移到目标
            pyautogui.moveTo(x, y, duration=random.uniform(0.05, 0.1))

            # 短暂悬停
            time.sleep(random.uniform(0.02, 0.08))

            # 点击
            pyautogui.click()
        except:
            pass

    def _human_delay(self):
        """人机化延迟 - 模拟人类反应时间"""
        elapsed = time.time() - self._last_action_time

        # 最小间隔 200ms
        if elapsed < 0.2:
            time.sleep(0.2 - elapsed)

        # 随机延迟 300-1000ms
        delay = random.uniform(0.3, 1.0)
        time.sleep(delay)

        self._last_action_time = time.time()
