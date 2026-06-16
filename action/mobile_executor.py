"""
移动端 (APP) 动作执行器

通过 ADB (Android Debug Bridge) 在手机/平板上模拟触屏操作。
替代桌面版 pyautogui 鼠标模拟，实现雀魂 APP 的自动打牌。

支持:
  - ADB 设备检测和连接
  - 屏幕尺寸自动获取
  - 触屏点击 (input tap)
  - 滑动操作 (input swipe)
  - 拟人化延迟和随机偏移
  - 多种雀魂 APP 布局自适应 (竖屏/横屏)
"""

import time
import random
import subprocess
import os
import re
from typing import Optional, Dict, Tuple, List

from utils.log import Logger


# ═══════════════════════════════════════════════════════════════
#  ADB 工具
# ═══════════════════════════════════════════════════════════════

class ADB:
    """ADB 命令封装"""

    @staticmethod
    def devices() -> List[str]:
        """获取已连接设备列表"""
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True, text=True, timeout=10
            )
            devices = []
            for line in result.stdout.strip().split("\n")[1:]:
                if "\tdevice" in line:
                    devices.append(line.split("\t")[0])
            return devices
        except FileNotFoundError:
            Logger.warning("ADB not found. 请安装 Android SDK Platform Tools")
            return []
        except Exception as e:
            Logger.error(f"ADB error: {e}")
            return []

    @staticmethod
    def shell(device_id: str, cmd: str, timeout: int = 10) -> Optional[str]:
        """在指定设备上执行 shell 命令"""
        try:
            result = subprocess.run(
                ["adb", "-s", device_id, "shell"] + cmd.split(),
                capture_output=True, text=True, timeout=timeout
            )
            return result.stdout.strip()
        except Exception as e:
            Logger.error(f"ADB shell error: {e}")
            return None

    @staticmethod
    def tap(device_id: str, x: int, y: int) -> bool:
        """在指定设备上点击 (x, y)"""
        try:
            result = subprocess.run(
                ["adb", "-s", device_id, "shell", "input", "tap", str(x), str(y)],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            Logger.error(f"ADB tap error: {e}")
            return False

    @staticmethod
    def swipe(device_id: str, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300) -> bool:
        """在指定设备上滑动"""
        try:
            result = subprocess.run(
                ["adb", "-s", device_id, "shell", "input", "swipe",
                 str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            Logger.error(f"ADB swipe error: {e}")
            return False

    @staticmethod
    def screenshot(device_id: str, output_path: str) -> bool:
        """截取设备屏幕"""
        try:
            # 在设备上截图，然后拉取到本地
            subprocess.run(
                ["adb", "-s", device_id, "shell", "screencap", "-p", "/sdcard/screen.png"],
                capture_output=True, timeout=10
            )
            subprocess.run(
                ["adb", "-s", device_id, "pull", "/sdcard/screen.png", output_path],
                capture_output=True, timeout=10
            )
            return os.path.isfile(output_path)
        except Exception as e:
            Logger.error(f"ADB screenshot error: {e}")
            return False

    @staticmethod
    def get_screen_size(device_id: str) -> Optional[Tuple[int, int]]:
        """获取设备屏幕尺寸 (width, height)"""
        output = ADB.shell(device_id, "wm size")
        if output:
            match = re.search(r"(\d+)x(\d+)", output)
            if match:
                return int(match.group(1)), int(match.group(2))
        return None


# ═══════════════════════════════════════════════════════════════
#  移动端按钮位置配置
# ═══════════════════════════════════════════════════════════════

class MobileLayout:
    """
    雀魂 APP 移动端布局参数

    坐标均为屏幕比例 (0.0 ~ 1.0)，
    原点在左上角 (竖屏模式)。
    """

    # 竖屏模式 (Portrait) — 默认布局
    PORTRAIT = {
        # 手牌区域 (底部)
        "hand_y_top": 0.72,       # 手牌区顶部
        "hand_y_bottom": 0.92,    # 手牌区底部
        "hand_x_left": 0.03,      # 手牌区左边距
        "hand_x_right": 0.97,     # 手牌区右边距

        # 按钮区域 (手牌上方)
        "buttons_y_ratio": 0.65,  # 主按钮行 Y 坐标

        # 各按钮 X 坐标 (相对于屏幕宽度的比例)
        "pon_x": 0.20,
        "chi_x": 0.35,
        "kan_x": 0.50,
        "riichi_x": 0.25,
        "ron_x": 0.65,
        "tsumo_x": 0.75,
        "pass_x": 0.50,

        # 摸到的牌位置 (手牌区最右)
        "drawn_tile_x_ratio": 0.88,  # 刚摸的牌在手牌最右侧
    }

    # 横屏模式 (Landscape) — 平板/横屏手机
    LANDSCAPE = {
        "hand_y_top": 0.78,
        "hand_y_bottom": 0.95,
        "hand_x_left": 0.10,
        "hand_x_right": 0.90,

        "buttons_y_ratio": 0.72,

        "pon_x": 0.25,
        "chi_x": 0.38,
        "kan_x": 0.51,
        "riichi_x": 0.30,
        "ron_x": 0.64,
        "tsumo_x": 0.77,
        "pass_x": 0.55,

        "drawn_tile_x_ratio": 0.85,
    }


# ═══════════════════════════════════════════════════════════════
#  MobileActionExecutor
# ═══════════════════════════════════════════════════════════════

class MobileActionExecutor:
    """
    移动端动作执行器

    通过 ADB 在雀魂 APP 上模拟触屏操作。
    使用方法:
        exec = MobileActionExecutor()
        exec.connect()  # 连接第一个可用设备
        exec.execute(action)
    """

    def __init__(self, device_id: str = None):
        self._device_id = device_id
        self._screen_width = 0
        self._screen_height = 0
        self._is_landscape = False
        self._layout = MobileLayout.PORTRAIT
        self._last_action_time = 0.0
        self._enabled = True

        # 统计数据
        self._action_count = 0
        self._fail_count = 0

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def fail_count(self) -> int:
        return self._fail_count

    @property
    def connected(self) -> bool:
        return self._device_id is not None and self._screen_width > 0

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        Logger.info(f"[MobileAction] {'ENABLED' if enabled else 'DISABLED'}")

    def connect(self, device_id: str = None) -> bool:
        """
        连接设备

        Args:
            device_id: 设备序列号。为 None 时自动选择第一个可用设备。
        """
        if device_id:
            self._device_id = device_id
        else:
            devices = ADB.devices()
            if not devices:
                Logger.error("[MobileAction] No ADB devices found")
                return False
            self._device_id = devices[0]
            Logger.info(f"[MobileAction] Auto-selected device: {self._device_id}")

        # 获取屏幕尺寸
        size = ADB.get_screen_size(self._device_id)
        if not size:
            Logger.error(f"[MobileAction] Cannot get screen size for {self._device_id}")
            return False

        self._screen_width, self._screen_height = size

        # 判断横竖屏
        self._is_landscape = self._screen_width > self._screen_height
        self._layout = MobileLayout.LANDSCAPE if self._is_landscape else MobileLayout.PORTRAIT

        Logger.info(
            f"[MobileAction] Device: {self._device_id} "
            f"({self._screen_width}x{self._screen_height}, "
            f"{'landscape' if self._is_landscape else 'portrait'})"
        )
        return True

    def execute(self, action) -> bool:
        """执行一个游戏动作"""
        from ai.engine import GameAction, ActionType

        if not self._enabled:
            Logger.info(f"[MobileAction] Skipped — disabled ({action.action.value})")
            return False

        if not self.connected:
            Logger.warning("[MobileAction] Not connected to device")
            self._fail_count += 1
            return False

        self._action_count += 1

        try:
            # 拟人化延迟
            self._human_delay()

            # 分发动作
            if action.action == ActionType.DISCARD:
                return self._tap_tile(action.tile)
            elif action.action == ActionType.RIICHI:
                ok = self._tap_tile(action.tile)
                time.sleep(random.uniform(0.3, 0.6))
                return ok and self._tap_button("riichi")
            elif action.action == ActionType.PON:
                return self._tap_button("pon")
            elif action.action == ActionType.CHI:
                return self._tap_button("chi")
            elif action.action == ActionType.KAN:
                return self._tap_button("kan")
            elif action.action == ActionType.RON:
                return self._tap_button("ron")
            elif action.action == ActionType.TSUMO:
                return self._tap_button("tsumo")
            elif action.action == ActionType.PASS:
                return self._tap_button("pass")
            else:
                Logger.warning(f"[MobileAction] Unknown action: {action.action}")
                self._fail_count += 1
                return False

        except Exception as e:
            Logger.error(f"[MobileAction] Failed: {e}")
            self._fail_count += 1
            return False

    # ── 手牌点击 ──

    def _tap_tile(self, tile_index: int) -> bool:
        """
        点击手牌中的第 tile_index 张牌

        手牌从屏幕左侧排列到右侧，刚摸的牌在最右边。
        """
        w = self._screen_width
        h = self._screen_height

        # 手牌区域
        tile_area_x = int(w * self._layout["hand_x_left"])
        tile_area_w = int(w * (self._layout["hand_x_right"] - self._layout["hand_x_left"]))
        tile_area_y_top = int(h * self._layout["hand_y_top"])
        tile_area_y_bottom = int(h * self._layout["hand_y_bottom"])

        # 手牌最多 14 张，均匀分布
        max_tiles = 14
        tile_step = tile_area_w // max_tiles
        idx = min(tile_index, max_tiles - 1)

        # 计算点击坐标 (加随机偏移以拟人化)
        tx = tile_area_x + tile_step * idx + random.randint(
            max(3, tile_step // 4),
            max(5, tile_step - tile_step // 4)
        )
        ty = tile_area_y_top + random.randint(
            max(3, (tile_area_y_bottom - tile_area_y_top) // 4),
            max(5, (tile_area_y_bottom - tile_area_y_top) - (tile_area_y_bottom - tile_area_y_top) // 4)
        )

        # 额外小随机偏移
        tx += random.randint(-6, 6)
        ty += random.randint(-4, 4)

        # 边界裁剪
        tx = max(0, min(w - 1, tx))
        ty = max(0, min(h - 1, ty))

        ok = ADB.tap(self._device_id, tx, ty)
        if ok:
            Logger.debug(f"[MobileAction] Tapped tile #{tile_index} at ({tx}, {ty})")
        return ok

    # ── 按钮点击 ──

    def _tap_button(self, button_name: str) -> bool:
        """点击游戏 UI 按钮"""
        w = self._screen_width
        h = self._screen_height

        # 按钮 Y 坐标
        by = int(h * self._layout["buttons_y_ratio"])

        # 按钮 X 坐标
        x_key = f"{button_name}_x"
        if x_key in self._layout:
            bx = int(w * self._layout[x_key]) + random.randint(-8, 8)
        else:
            bx = w // 2  # 默认居中

        bx += random.randint(-3, 3)
        by += random.randint(-3, 3)

        bx = max(0, min(w - 1, bx))
        by = max(0, min(h - 1, by))

        ok = ADB.tap(self._device_id, bx, by)
        if ok:
            Logger.debug(f"[MobileAction] Tapped '{button_name}' at ({bx}, {by})")
        return ok

    # ── 拟人化延迟 ──

    def _human_delay(self):
        """
        拟人化延迟

        模拟人类的反应时间:
          - 基础间隔: 200ms
          - 随机延迟: 300-1200ms (正态分布)
        """
        elapsed = time.time() - self._last_action_time

        # 最小间隔
        min_gap = 0.2
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)

        # 正态分布延迟 (mean=700ms, sigma=250ms)
        delay = abs(random.gauss(0.7, 0.25))
        delay = max(0.3, min(1.8, delay))
        time.sleep(delay)

        self._last_action_time = time.time()

    # ── 工具 ──

    def tap_at(self, x: int, y: int):
        """在指定绝对坐标点击 (调试用)"""
        ADB.tap(self._device_id, x, y)
        Logger.debug(f"[MobileAction] Manual tap at ({x}, {y})")

    def swipe_hand(self, direction: str = "left"):
        """
        滑动切换手牌视角 (适用于手牌过多需要滚动的情况)

        Args:
            direction: "left" 或 "right"
        """
        y = self._screen_height // 2
        x1 = self._screen_width * 3 // 4
        x2 = self._screen_width // 4

        if direction == "right":
            x1, x2 = x2, x1

        ADB.swipe(self._device_id, x1, y, x2, y, duration_ms=200)
