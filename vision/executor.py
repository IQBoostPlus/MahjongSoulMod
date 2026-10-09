"""
视觉驱动的动作执行器

集成了 VisionPipeline + ActionVerifier, 提供与现有 ActionExecutor
相同的 execute(action) -> bool 接口。

执行流程:
  1. 捕获执行前帧 (VisionPipeline.process_frame)
  2. Plan: 确定点击目标坐标
  3. Execute: 鼠标点击 + 拟人化延迟
  4. Verify: 截后帧验证效果
  5. 轮询确认；未确认则停止，不重复点击

管线、窗口或动作结果不可确认时停止执行。

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
        self._can_execute = lambda: True
        self._executing_rect = None
        self._verifier._click = self._click_at
        self._verifier._can_execute = self._is_active

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

    def _is_active(self):
        return self._enabled and self._can_execute()

    def execute(self, action):
        from ai.engine import ActionType
        if action.action == ActionType.NONE:
            return True
        if not self._is_active():
            return False
        self._action_count += 1
        self._human_delay()
        if not self._is_active():
            return False
        win_rect = self._find_window()
        if win_rect is None or self._pipeline is None or not self._pipeline.running:
            self._fail_count += 1
            self._enabled = False
            return False
        self._executing_rect = win_rect
        try:
            self._pipeline.set_window_rect(*win_rect)
            pre_state = self._pipeline.process_frame()
            ok = pre_state is not None and self._verifier.execute_with_verify(action, pre_state, win_rect)
        except Exception as exc:
            Logger.error(f'[VisionExec] Unconfirmed action: {exc}')
            ok = False
        finally:
            self._executing_rect = None
        if not ok:
            self._fail_count += 1
            self._enabled = False
        return bool(ok)

    # Mouse operations always recheck cancellation and window geometry.

    def _click_at(self, x: int, y: int) -> bool:
        """拟人化鼠标移动 + 点击"""
        if not self._is_active():
            return False
        if self._executing_rect is None or self._find_window() != self._executing_rect:
            return False
        try:
            import pyautogui
        except ImportError:
            Logger.debug(f"[VisionExec] WOULD click ({x}, {y})")
            return False

        try:
            cur_x, cur_y = pyautogui.position()

            # 两段贝塞尔式曲线移动
            mid_x = cur_x + (x - cur_x) * random.uniform(0.4, 0.7)
            mid_y = cur_y + (y - cur_y) * random.uniform(0.3, 0.6)

            pyautogui.moveTo(mid_x, mid_y, duration=random.uniform(0.03, 0.10))
            pyautogui.moveTo(x, y, duration=random.uniform(0.02, 0.08))

            time.sleep(random.uniform(0.01, 0.05))
            if not self._is_active() or self._find_window() != self._executing_rect:
                return False
            pyautogui.click()
            return True
        except Exception:
            return False

    # ── 窗口查找 ──

    def _find_window(self) -> Optional[Tuple[int, int, int, int]]:
        """查找游戏窗口 (带缓存)"""
        if self._window is not None:
            try:
                if self._window.visible and not self._window.isMinimized:
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

                if w.visible and not w.isMinimized and w.width > 600 and w.height > 400:
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
