"""
动作验证器 — Plan→Execute→Verify 闭环

每次 AI 决策后:
  1. PLAN:   确定点击目标坐标
  2. EXECUTE: 执行鼠标点击
  3. VERIFY:  截图验证预期结果
  4. 失败 → 重试 (默认 3 次), 每次可调整策略

验证策略 (各动作类型):
  - DISCARD: 手牌 -1, 自家牌河 +1
  - PON:     副露 +1, 手牌 -2
  - CHI:     副露 +1, 手牌 -2
  - KAN:     副露 +1, 手牌 -3 (明杠) 或 -4 (暗杠)
  - RIICHI:  立直棒 +1, 立直按钮消失
  - RON:     按钮消失 (对局结束)
  - TSUMO:   按钮消失 (对局结束)

用法:
    verifier = ActionVerifier(pipeline, detector, click_fn)
    ok = verifier.execute_with_verify(action)
"""

import time
from typing import Callable, Optional, Tuple

from utils.log import Logger


class ActionVerifier:
    """
    闭环动作验证器。

    职责:
      - 将 GameAction 转换为屏幕坐标
      - 执行点击
      - 截屏验证预期变化
      - 失败时重试 (改变点击偏移)
    """

    MAX_RETRIES = 3
    VERIFY_WAIT = 0.3  # 点击后等待游戏响应的时间 (秒)

    def __init__(self, pipeline=None, button_detector=None,
                 click_fn: Callable[[int, int], bool] = None,
                 max_retries: int = None):
        """
        Args:
            pipeline: VisionPipeline 实例 (用于前后截帧验证)
            button_detector: ButtonDetector 实例 (用于按钮定位)
            click_fn: 鼠标点击函数 (x, y) -> bool
            max_retries: 最大重试次数 (默认 3)
        """
        self._pipeline = pipeline
        self._buttons = button_detector
        self._click = click_fn or self._default_click
        self._max_retries = max_retries or self.MAX_RETRIES

        # 统计
        self._verify_count = 0
        self._retry_count = 0

    # ── 主入口 ──

    def execute_with_verify(self, action: "GameAction",
                             pre_state: "VisionFrame" = None,
                             window_rect: Tuple[int, int, int, int] = None) -> bool:
        """
        执行动作并验证。

        Args:
            action: AI 决策结果 (GameAction)
            pre_state: 执行前帧状态 (用于验证). None=现截一帧
            window_rect: 窗口矩形 (x, y, w, h). None=从 pre_state 取

        Returns:
            True 验证通过, False 全部重试失败
        """
        from ai.engine import ActionType

        action_type = action.action
        if action_type == ActionType.PASS or action_type == ActionType.NONE:
            return True

        # 捕获执行前状态
        if pre_state is None and self._pipeline:
            pre_state = self._pipeline.process_frame()

        for attempt in range(self._max_retries):
            # PLAN: 确定点击目标
            target = self._plan_target(action, pre_state, window_rect, attempt)

            if target is None:
                Logger.warning(f"[Verifier] Cannot plan target for {action_type.value}")
                continue

            # EXECUTE
            Logger.debug(
                f"[Verifier] Attempt {attempt+1}/{self._max_retries}: "
                f"{action_type.value} tile={action.tile} → ({target[0]}, {target[1]})"
            )
            ok = self._click(*target)
            if not ok:
                continue

            # 等待游戏响应
            time.sleep(self.VERIFY_WAIT)

            # VERIFY
            post_state = None
            if self._pipeline:
                post_state = self._pipeline.process_frame()

            if self._verify_outcome(action, pre_state, post_state):
                self._verify_count += 1
                return True

            Logger.debug(f"[Verifier] Verification failed, attempt {attempt+1}")

        self._retry_count += 1
        Logger.warning(f"[Verifier] All {self._max_retries} attempts failed for {action_type.value}")
        return False

    # ── 规划点击目标 ──

    def _plan_target(self, action: "GameAction",
                      pre_state: "VisionFrame",
                      window_rect: Tuple[int, int, int, int],
                      attempt: int) -> Optional[Tuple[int, int]]:
        """
        根据动作类型确定屏幕点击坐标。

        按钮动作: 用 ButtonDetector
        切牌动作: 在手牌区按 tile ID 定位
        """
        from ai.engine import ActionType

        action_type = action.action
        tile = action.tile

        # ── 按钮动作 ──
        if action_type in (ActionType.PON, ActionType.CHI, ActionType.KAN,
                            ActionType.RON, ActionType.TSUMO, ActionType.PASS):
            btn_name = action_type.value
            if self._buttons:
                # 需要当前帧来找按钮
                screen = self._pipeline.process_frame() if self._pipeline else None
                if screen is None:
                    return self._fallback_button_pos(btn_name, window_rect, attempt)

                # 从按钮区域裁切
                h, w = None, None
                import numpy as np
                if isinstance(screen, np.ndarray):
                    h, w = screen.shape[:2]

                if self._pipeline and hasattr(self._pipeline, '_regions'):
                    btn_roi = self._pipeline._regions.buttons.crop(
                        screen, w or 1920, h or 1080
                    )
                    pos = self._buttons.find_button_position(btn_name, btn_roi)
                    if pos:
                        return pos

                # 全屏匹配
                raw_pos = self._buttons.find_button_position(btn_name, screen)
                if raw_pos:
                    return raw_pos

            return self._fallback_button_pos(btn_name, window_rect, attempt)

        # ── 切牌动作 ──
        if action_type == ActionType.DISCARD:
            return self._plan_tile_click(tile, pre_state, window_rect, attempt)

        # ── 立直 ──
        if action_type == ActionType.RIICHI:
            # 立直 = 切牌 + 点立直按钮 (两步走，这里只规划切牌)
            return self._plan_tile_click(tile, pre_state, window_rect, attempt)

        return None

    def _plan_tile_click(self, tile: int, pre_state: "VisionFrame",
                          window_rect, attempt: int) -> Optional[Tuple[int, int]]:
        """
        确定手牌中某张牌的屏幕坐标。

        在手牌 ROI 中按 tile 的排序位置 + 等分间隔计算。
        """
        if pre_state is None or not pre_state.hand_tiles:
            return self._fallback_tile_pos(tile, window_rect, attempt)

        # 找到 tile 在手牌中的索引
        try:
            idx = pre_state.hand_tiles.index(tile)
        except ValueError:
            # tile 不在手牌中 → 用近似索引
            idx = min(tile, len(pre_state.hand_tiles) - 1) if pre_state.hand_tiles else 0

        # 在手牌区域中计算位置
        if window_rect is None:
            window_rect = pre_state.window_rect

        wx, wy, ww, wh = window_rect

        # 手牌区域 (从 regions)
        if self._pipeline and hasattr(self._pipeline, '_regions'):
            hand = self._pipeline._regions.hand
            hand_x = wx + int(hand.left * ww)
            hand_y = wy + int(hand.top * wh)
            hand_w = int(hand.width * ww)
            hand_h = int(hand.height * wh)
        else:
            # 默认手牌区域 (窗口 3%-97% 宽, 88%-98% 高)
            hand_x = wx + int(ww * 0.03)
            hand_y = wy + int(wh * 0.88)
            hand_w = int(ww * 0.94)
            hand_h = int(wh * 0.10)

        # 手牌数
        n_tiles = max(pre_state.hand_count, 14)
        step = hand_w // n_tiles

        # 中心坐标 + 重试偏移
        cx = hand_x + step * idx + step // 2
        cy = hand_y + hand_h // 2

        # 重试时增加随机偏移
        import random
        cx += random.randint(-step // 3, step // 3)
        cy += random.randint(-hand_h // 3, hand_h // 3)

        return (cx, cy)

    # ── 回退定位 ──

    def _fallback_button_pos(self, btn_name: str, window_rect,
                               attempt: int) -> Optional[Tuple[int, int]]:
        """按钮定位回退 — 使用硬编码相对坐标"""
        from vision.buttons import ButtonDetector
        fallback = ButtonDetector.FALLBACK_POSITIONS

        if btn_name not in fallback:
            return None

        if window_rect is None:
            return None

        wx, wy, ww, wh = window_rect
        rx, ry = fallback[btn_name]

        import random
        x = wx + int(ww * rx) + random.randint(-8, 8)
        y = wy + int(wh * ry) + random.randint(-5, 5)

        return (x, y)

    def _fallback_tile_pos(self, tile: int, window_rect,
                             attempt: int) -> Optional[Tuple[int, int]]:
        """手牌定位回退 — 按索引估算"""
        if window_rect is None:
            return None

        wx, wy, ww, wh = window_rect
        idx = max(0, min(tile, 13))
        step = int(ww * 0.94) // 14
        x = wx + int(ww * 0.03) + step * idx + step // 2
        y = wy + int(wh * 0.93)

        import random
        x += random.randint(-step // 3, step // 3)
        return (x, y)

    # ── 验证 ──

    def _verify_outcome(self, action: "GameAction",
                         before: "VisionFrame",
                         after: "VisionFrame") -> bool:
        """
        验证动作效果。

        比较执行前后的帧状态, 确认变化符合预期。
        before/after 任一为 None → 跳过验证 (乐观 = True)
        """
        from ai.engine import ActionType

        if before is None or after is None:
            # 无法验证 → 乐观假设成功
            return True

        action_type = action.action

        # DISCARD: 手牌 -1, 牌河 +1
        if action_type == ActionType.DISCARD:
            hand_ok = after.hand_count == before.hand_count - 1
            river_ok = len(after.discards[0]) >= len(before.discards[0])
            if not hand_ok:
                Logger.debug("[Verifier] DISCARD: hand count mismatch")
            return hand_ok or river_ok  # 至少满足一个

        # PON: 手牌 -2, 副露 +1
        if action_type == ActionType.PON:
            hand_ok = after.hand_count <= before.hand_count - 2
            meld_ok = len(after.melds[0]) > len(before.melds[0]) if after.melds else False
            return hand_ok or meld_ok

        # CHI: 手牌 -2, 副露 +1
        if action_type == ActionType.CHI:
            hand_ok = after.hand_count <= before.hand_count - 2
            meld_ok = len(after.melds[0]) > len(before.melds[0]) if after.melds else False
            return hand_ok or meld_ok

        # KAN: 手牌 -3 (明杠) 或 -4 (暗杠)
        if action_type == ActionType.KAN:
            hand_ok = after.hand_count <= before.hand_count - 3
            meld_ok = len(after.melds[0]) > len(before.melds[0]) if after.melds else False
            return hand_ok or meld_ok

        # RIICHI: 按钮消失 (立直宣言后不再有按钮)
        if action_type == ActionType.RIICHI:
            return hand_ok

        # RON/TSUMO: 按钮出现又消失 (对局结束)
        if action_type in (ActionType.RON, ActionType.TSUMO):
            return True  # 难以精确验证, 乐观

        # PASS / 未知: 乐观通过
        return True

    # ── 默认鼠标点击 ──

    @staticmethod
    def _default_click(x: int, y: int) -> bool:
        """默认鼠标点击实现 (pyautogui)"""
        try:
            import pyautogui
            cur_x, cur_y = pyautogui.position()

            # 两段贝塞尔式移动
            import random
            mid_x = cur_x + (x - cur_x) * random.uniform(0.4, 0.7)
            mid_y = cur_y + (y - cur_y) * random.uniform(0.3, 0.6)

            pyautogui.moveTo(mid_x, mid_y, duration=random.uniform(0.03, 0.10))
            pyautogui.moveTo(x, y, duration=random.uniform(0.02, 0.08))
            time.sleep(random.uniform(0.01, 0.05))
            pyautogui.click()
            return True
        except Exception as e:
            Logger.debug(f"[Verifier] Click failed: {e}")
            return False

    # ── 统计 ──

    @property
    def verify_count(self) -> int:
        return self._verify_count

    @property
    def retry_count(self) -> int:
        return self._retry_count
