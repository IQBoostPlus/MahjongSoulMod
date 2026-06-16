"""
视觉驱动的动作执行器

集成了 VisionPipeline + ActionVerifier, 提供与现有 ActionExecutor
相同的 execute(action) -> bool 接口。

执行流程:
  1. 捕获执行前帧 (VisionPipeline.process_frame)
  2. Plan: 确定点击目标坐标
  3. Execute: 鼠标点击 + 拟人化延迟
  4. Verify: 截后帧验证效果
  5. 失败 → 重试 (最多 3 次)

回退策略 (vision pipeline 不可用时):
  → 降级到坐标估算 + 无验证模式 (兼容旧版 AirtestActionExecutor)

用法:
    executor = VisionActionExecutor(pipeline, button_detector)
    executor.set_enabled(True)
    ok = executor.execute(ai_action)  # 返回 True/False
"""

import time
import random
from typing import Optional, Tuple

from utils.log import Logger


class VisionActionExecutor:
    """
    视觉驱动动作执行器。

    与 AirtestActionExecutor / ActionExecutor 接口兼容,
    可直接替换为 AppContext 的 executor 后端。
    """

    def __init__(self, pipeline=None, button_detector=None,
                 verifier=None, differ=None):
        """
        Args:
            pipeline: VisionPipeline 实例 (用于截帧验证)
            button_detector: ButtonDetector 实例 (用于按钮定位)
            verifier: ActionVerifier 实例 (None=自动创建)
            differ: StateDiffer 实例 (None=自动创建)
        """
        from vision.verifier import ActionVerifier

        self._pipeline = pipeline
        self._buttons = button_detector
        self._verifier = verifier or ActionVerifier(
            pipeline=pipeline,
            button_detector=button_detector,
            click_fn=self._click_at,
        )
        self._differ = differ

        # 状态
        self._enabled = True
        self._window = None
        self._last_action_time = 0.0

        # 统计
        self._action_count = 0
        self._fail_count = 0

    # ── 属性 ──

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def fail_count(self) -> int:
        return self._fail_count

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        Logger.info(f"[VisionExec] {'ENABLED' if enabled else 'DISABLED'}")

    # ── 主执行 ──

    def execute(self, action: "GameAction") -> bool:
        """
        执行 AI 决策动作。

        Args:
            action: ai.engine.GameAction 实例

        Returns:
            True 成功, False 失败
        """
        from ai.engine import ActionType, GameAction

        if not self._enabled:
            Logger.debug(f"[VisionExec] Skipped (disabled): {action.action.value}")
            return False

        self._action_count += 1

        # 拟人化延迟
        self._human_delay()

        # 查找游戏窗口
        win_rect = self._find_window()
        if win_rect is None:
            Logger.warning("[VisionExec] Game window not found")
            # 无窗口时仍尝试点击 (可能窗口在上次查找后被最小化)
            win_rect = (0, 0, 1920, 1080)

        # ── 有 Vision Pipeline: 带验证执行 ──
        if self._pipeline and self._pipeline.running:
            # 捕获执行前状态
            pre_state = self._pipeline.process_frame()

            if pre_state is None:
                return self._fallback_execute(action, win_rect)

            # 带验证执行
            ok = self._verifier.execute_with_verify(
                action, pre_state, win_rect
            )

            if not ok:
                self._fail_count += 1

            return ok

        # ── 无 Vision Pipeline: 回退执行 ──
        return self._fallback_execute(action, win_rect)

    # ── 回退执行 (坐标估算, 无验证) ──

    def _fallback_execute(self, action: "GameAction",
                           win_rect: Tuple[int, int, int, int]) -> bool:
        """
        回退执行 — 使用按钮模板匹配 + 坐标估算, 不验证。

        复用现有 AirtestActionExecutor 的回退策略。
        """
        from ai.engine import ActionType

        wx, wy, ww, wh = win_rect

        try:
            action_type = action.action
            tile = action.tile

            # 按钮动作
            if action_type in (ActionType.PON, ActionType.CHI, ActionType.KAN,
                                ActionType.RON, ActionType.TSUMO, ActionType.PASS):
                btn_name = action_type.value
                pos = self._find_button_fallback(btn_name, win_rect)
                if pos is None:
                    Logger.warning(f"[VisionExec] Fallback: button '{btn_name}' not found")
                    self._fail_count += 1
                    return False
                self._click_at(*pos)
                return True

            # 切牌
            if action_type == ActionType.DISCARD:
                pos = self._find_tile_fallback(tile, win_rect)
                if pos is None:
                    self._fail_count += 1
                    return False
                self._click_at(*pos)
                return True

            # 立直: 先切牌再点按钮
            if action_type == ActionType.RIICHI:
                tile_pos = self._find_tile_fallback(tile, win_rect)
                if not tile_pos:
                    Logger.warning("[VisionExec] Fallback: riichi tile not found")
                    self._fail_count += 1
                    return False
                self._click_at(*tile_pos)
                time.sleep(random.uniform(0.3, 0.6))

                # 尝试点击立直按钮 (即使失败, 牌已切出)
                riichi_pos = self._find_button_fallback("riichi", win_rect)
                if riichi_pos:
                    self._click_at(*riichi_pos)
                return True

            return False

        except Exception as e:
            Logger.error(f"[VisionExec] Fallback error: {e}")
            self._fail_count += 1
            return False

    def _find_button_fallback(self, btn_name: str,
                                win_rect) -> Optional[Tuple[int, int]]:
        """按钮定位回退"""
        # 如果有 button detector, 尝试用它
        if self._buttons and self._pipeline:
            frame = self._pipeline.last_frame
            if frame is None:
                frame = self._pipeline.process_frame()
            if frame is not None:
                import numpy as np
                # 拿最新截帧
                pos = self._buttons.find_button_position(btn_name, frame if isinstance(frame, np.ndarray) else None)

        # 坐标估算
        from vision.buttons import ButtonDetector
        fallback = ButtonDetector.FALLBACK_POSITIONS
        if btn_name not in fallback:
            return None

        wx, wy, ww, wh = win_rect
        rx, ry = fallback[btn_name]
        return (
            wx + int(ww * rx) + random.randint(-8, 8),
            wy + int(wh * ry) + random.randint(-5, 5),
        )

    def _find_tile_fallback(self, tile: int,
                              win_rect) -> Optional[Tuple[int, int]]:
        """手牌定位回退"""
        wx, wy, ww, wh = win_rect
        idx = max(0, min(tile, 13))
        step = int(ww * 0.94) // 14

        x = wx + int(ww * 0.03) + step * idx + random.randint(step // 4, 3 * step // 4)
        y = wy + int(wh * 0.93) + random.randint(-8, 8)
        return (x, y)

    # ── 鼠标操作 ──

    def _click_at(self, x: int, y: int) -> bool:
        """拟人化鼠标移动 + 点击"""
        try:
            import pyautogui
        except ImportError:
            Logger.debug(f"[VisionExec] WOULD click ({x}, {y})")
            return True

        try:
            cur_x, cur_y = pyautogui.position()

            # 两段贝塞尔式曲线移动
            mid_x = cur_x + (x - cur_x) * random.uniform(0.4, 0.7)
            mid_y = cur_y + (y - cur_y) * random.uniform(0.3, 0.6)

            pyautogui.moveTo(mid_x, mid_y, duration=random.uniform(0.03, 0.10))
            pyautogui.moveTo(x, y, duration=random.uniform(0.02, 0.08))

            time.sleep(random.uniform(0.01, 0.05))
            pyautogui.click()
            return True
        except Exception:
            return False

    # ── 窗口查找 ──

    def _find_window(self) -> Optional[Tuple[int, int, int, int]]:
        """查找游戏窗口 (带缓存)"""
        if self._window is not None:
            try:
                if self._window.visible:
                    return (self._window.left, self._window.top,
                            self._window.width, self._window.height)
            except Exception:
                self._window = None

        try:
            import pygetwindow as gw
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
                    f"[VisionExec] Found window: '{w.title}' "
                    f"({w.width}x{w.height} @ {w.left},{w.top})"
                )
                return (w.left, w.top, w.width, w.height)
        except Exception:
            pass

        return None

    # ── 拟人化延迟 ──

    def _human_delay(self):
        """模拟人类反应时间"""
        elapsed = time.time() - self._last_action_time
        min_gap = 0.2
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)

        delay = abs(random.gauss(0.6, 0.2))
        delay = max(0.25, min(1.5, delay))
        time.sleep(delay)

        self._last_action_time = time.time()
