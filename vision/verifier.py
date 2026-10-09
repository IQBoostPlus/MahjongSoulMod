"""Plan one action, click once, and poll for affirmative outcome evidence.

Verification retries take fresh screenshots; they never repeat an uncertain
click. Missing observations cannot count as success.
"""
import time
from collections import Counter
from typing import Callable, Optional, Tuple

from utils.log import Logger


class ActionVerifier:
    MAX_RETRIES = 3
    VERIFY_WAIT = 0.3

    def __init__(self, pipeline=None, button_detector=None, click_fn=None,
                 max_retries=None, can_execute: Callable[[], bool] = None):
        self._pipeline = pipeline
        self._buttons = button_detector
        self._click = click_fn or self._default_click
        self._max_retries = max(1, self.MAX_RETRIES if max_retries is None else max_retries)
        self._can_execute = can_execute or (lambda: True)
        self._verify_count = 0
        self._retry_count = 0
        self.last_failure = None

    @staticmethod
    def _known_hand(frame):
        return (frame is not None and bool(frame.hand_tiles)
                and all(0 <= t <= 36 for t in frame.hand_tiles)
                and len(frame.hand_confidences) == frame.hand_count
                and all(c >= 0.5 for c in frame.hand_confidences))

    def execute_with_verify(self, action, pre_state=None, window_rect=None):
        from ai.engine import ActionType
        self.last_failure = None
        if action.action == ActionType.NONE:
            return True
        if not self._can_execute() or self._pipeline is None:
            return False
        if pre_state is None:
            pre_state = self._pipeline.process_frame()
        if pre_state is None:
            return False
        if (action.expected_hand is not None
                and Counter(action.expected_hand) != Counter(pre_state.hand_tiles)):
            return False
        if window_rect is None:
            window_rect = pre_state.window_rect
        if window_rect != pre_state.window_rect or min(window_rect[2:]) <= 0:
            return False

        # Riichi is button first, then the selected legal discard. If either
        # step is uncertain, stop rather than guessing another click.
        if action.action == ActionType.RIICHI:
            button = self._button_target('riichi', pre_state)
            if (button is None or self._plan_tile_click(action.tile, pre_state, window_rect, 0) is None
                    or not self._can_execute() or not self._click(*button)):
                return False
            time.sleep(self.VERIFY_WAIT)
            selected = self._pipeline.process_frame()
            if (selected is None or selected.timestamp <= pre_state.timestamp
                    or selected.window_rect != window_rect
                    or Counter(selected.hand_tiles) != Counter(pre_state.hand_tiles)):
                return False
            target = self._plan_tile_click(action.tile, selected, window_rect, 0)
        else:
            target = self._plan_target(action, pre_state, window_rect, 0)
        if target is None or not self._can_execute() or not self._click(*target):
            return False
        after = None
        for attempt in range(self._max_retries):
            if not self._can_execute():
                return False
            time.sleep(self.VERIFY_WAIT)
            after = self._pipeline.process_frame()
            if not self._can_execute():
                return False
            if self._verify_outcome(action, pre_state, after):
                self._verify_count += 1
                return True
            if attempt:
                self._retry_count += 1
        self.last_failure = {
            'action': action.action.value, 'tile': action.tile,
            'before_hand': list(pre_state.hand_tiles),
            'after_hand': list(after.hand_tiles) if after is not None else None,
            'before_river': list(pre_state.discards[0]),
            'after_river': list(after.discards[0]) if after is not None else None,
        }
        Logger.warning(f'[Verifier] Outcome unconfirmed: {self.last_failure}')
        return False

    @staticmethod
    def _button_target(name, frame):
        if frame is None or name not in frame.visible_buttons:
            return None
        pos = frame.button_positions.get(name)
        if pos is None:
            return None
        x, y, w, h = frame.window_rect
        return pos if x <= pos[0] < x + w and y <= pos[1] < y + h else None

    def _plan_target(self, action, pre_state, window_rect, attempt):
        from ai.engine import ActionType
        if action.action in (ActionType.DISCARD, ActionType.RIICHI):
            return self._plan_tile_click(action.tile, pre_state, window_rect, attempt)
        return self._button_target(action.action.value, pre_state)

    def _plan_tile_click(self, tile, pre_state, window_rect, attempt):
        if not self._known_hand(pre_state) or tile not in pre_state.hand_tiles:
            return None
        if len(pre_state.hand_boxes) != pre_state.hand_count:
            return None
        idx = pre_state.hand_tiles.index(tile)
        if pre_state.hand_confidences and (len(pre_state.hand_confidences) != pre_state.hand_count
                                          or min(pre_state.hand_confidences) < 0.5):
            return None
        x, y, w, h = pre_state.hand_boxes[idx]
        wx, wy, ww, wh = window_rect or pre_state.window_rect
        if w <= 0 or h <= 0 or x < wx or y < wy or x + w > wx + ww or y + h > wy + wh:
            return None
        return (x + w // 2, y + h // 2)

    def _verify_outcome(self, action, before, after):
        from ai.engine import ActionType
        if before is None or after is None or after.timestamp <= before.timestamp:
            return False
        if before.window_rect != after.window_rect:
            return False
        kind = action.action
        if kind in (ActionType.DISCARD, ActionType.RIICHI):
            if not self._known_hand(before) or not self._known_hand(after):
                return False
            removed = Counter(before.hand_tiles) - Counter(after.hand_tiles)
            added = Counter(after.hand_tiles) - Counter(before.hand_tiles)
            hand_ok = (after.hand_count == before.hand_count - 1
                       and removed == Counter([action.tile]) and not added)
            old, new = before.discards[0], after.discards[0]
            river_ok = len(new) == len(old) + 1 and new[:-1] == old and new[-1] == action.tile
            result = hand_ok and river_ok
            if kind == ActionType.RIICHI:
                result = result and after.riichi_sticks == before.riichi_sticks + 1
            return result
        if kind in (ActionType.PON, ActionType.CHI, ActionType.KAN):
            if not self._known_hand(before) or not self._known_hand(after):
                return False
            expected = {ActionType.PON: 2, ActionType.CHI: 2, ActionType.KAN: 3}[kind]
            return (after.hand_count == before.hand_count - expected
                    and len(after.melds[0]) == len(before.melds[0]) + 1)
        if kind in (ActionType.RON, ActionType.TSUMO):
            # Button disappearance alone may be a timeout or recognition error.
            return (kind.value in before.visible_buttons and kind.value not in after.visible_buttons
                    and after.round_ended)
        if kind == ActionType.PASS:
            return 'pass' in before.visible_buttons and 'pass' not in after.visible_buttons
        return False

    @staticmethod
    def _default_click(x, y):
        try:
            import pyautogui
            pyautogui.click(x, y)
            return True
        except Exception as exc:
            Logger.debug(f'[Verifier] Click failed: {exc}')
            return False

    @property
    def verify_count(self):
        return self._verify_count

    @property
    def retry_count(self):
        return self._retry_count
