"""
回归测试 — unittest.TestCase 格式 (原 test_regression.py)

覆盖: Bug#1-#3 修复, GameTracker 集成, AI 决策, MobileExecutor
15 tests total
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from game_state.tracker import GameTracker, GameState, Player, MeldType
from ai.engine import (
    AIDecisionMaker, GameAction, ActionType,
    ShantenCalculator, DoraCalculator,
    DefenseAnalysis, StrategyParams,
    cached_shanten, clear_shanten_cache,
    to_count_array,
)
from ai.shanten import TILE_COUNT
from proto import tile_to_str, tile_id


def make_hand(*tiles: str) -> list:
    """字符串表示 → 手牌列表"""
    result = []
    for s in tiles:
        s = s.strip().lower()
        num = int(s[:-1])
        suit_char = s[-1]
        if suit_char == 'm':
            idx = num - 1
        elif suit_char == 'p':
            idx = 9 + num - 1
        elif suit_char == 's':
            idx = 18 + num - 1
        elif suit_char == 'z':
            idx = 27 + num - 1
        else:
            raise ValueError(f"Invalid tile: {s}")
        result.append(idx)
    return result


class TestBugFixDrawAction(unittest.TestCase):
    """Bug #1: _on_draw_tile 设置 last_action = 'draw'"""

    def test_draw_tile_sets_last_action(self):
        """摸牌后 GameState.last_action 应为 'draw'"""
        tracker = GameTracker()
        tracker.on_game_event("new_round", {
            "chang": 0, "ju": 0, "ben": 0, "oya": 0,
            "tiles": make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p"),
            "dora_indicator": 27,
            "scores": [25000, 25000, 25000, 25000],
            "self_seat": 0,
        })
        tracker.on_game_event("draw_tile", {
            "seat": 0, "tile": tile_id(0, 5), "left_count": 69,
        })
        self.assertEqual(tracker.state.last_action, "draw")
        self.assertEqual(len(tracker.state.players[0].hand), 14)

    def test_opponent_draw_does_not_set_last_action_draw(self):
        """对手摸牌不应设置 last_action = 'draw'"""
        tracker = GameTracker()
        tracker.on_game_event("new_round", {
            "chang": 0, "ju": 0, "ben": 0, "oya": 0,
            "tiles": make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p"),
            "dora_indicator": 27,
            "scores": [25000, 25000, 25000, 25000],
            "self_seat": 0,
        })
        tracker.on_game_event("draw_tile", {
            "seat": 1, "tile": tile_id(2, 5), "left_count": 69,
        })
        self.assertNotEqual(tracker.state.last_action, "draw")


class TestBugFixKan(unittest.TestCase):
    """Bug #2: _should_kan 检查 3 张而不是 4 张"""

    def test_should_kan_with_3_copies(self):
        """手中有3张相同牌时应允许明杠"""
        ai = AIDecisionMaker()
        ai.params.risk_tolerance = 0.5
        state = GameState()
        hand = make_hand("1m","1m","1m","2m","4m","6m","8m","1p","3p","5p","2s","5s","8s")
        state.players[0].hand = hand
        state.self_seat = 0
        clear_shanten_cache()
        result = ai._should_kan(state, tile_id(0, 1), hand)
        self.assertTrue(result)

    def test_should_kan_rejects_2_copies(self):
        """手中只有2张相同牌时不应杠"""
        ai = AIDecisionMaker()
        ai.params.risk_tolerance = 0.5
        state = GameState()
        hand = make_hand("1m","1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p")
        state.players[0].hand = hand
        result = ai._should_kan(state, tile_id(0, 1), hand)
        self.assertFalse(result)


class TestBugFixOwnDiscard(unittest.TestCase):
    """Bug #3: 自家舍牌不触发鸣牌"""

    def test_discard_tile_sets_last_discard_seat(self):
        """舍牌后 last_discard_seat 应正确设置"""
        tracker = GameTracker()
        tracker.on_game_event("new_round", {
            "chang": 0, "ju": 0, "ben": 0, "oya": 0,
            "tiles": make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p"),
            "dora_indicator": 27,
            "scores": [25000, 25000, 25000, 25000],
            "self_seat": 0,
        })
        tracker.on_game_event("discard_tile", {
            "seat": 1, "tile": tile_id(0, 5), "is_liqi": False, "moqie": 0,
        })
        self.assertEqual(tracker.state.last_discard_seat, 1)
        self.assertEqual(tracker.state.last_discard, tile_id(0, 5))

    def test_own_discard_sets_last_discard_seat(self):
        """自家舍牌后 last_discard_seat 应为 self_seat"""
        tracker = GameTracker()
        tracker.on_game_event("new_round", {
            "chang": 0, "ju": 0, "ben": 0, "oya": 0,
            "tiles": make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p"),
            "dora_indicator": 27,
            "scores": [25000, 25000, 25000, 25000],
            "self_seat": 0,
        })
        tracker.on_game_event("discard_tile", {
            "seat": 0, "tile": tile_id(1, 9), "is_liqi": False, "moqie": 1,
        })
        self.assertEqual(tracker.state.last_discard_seat, 0)


class TestGameTrackerFlow(unittest.TestCase):
    """GameTracker 集成流程"""

    def test_full_round_flow(self):
        """完整一局的 tracker 流程"""
        tracker = GameTracker()
        tracker.on_game_event("game_start", {})
        tiles = make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p")
        tracker.on_game_event("new_round", {
            "chang": 0, "ju": 0, "ben": 0, "oya": 0,
            "tiles": tiles, "dora_indicator": 27,
            "scores": [25000, 25000, 25000, 25000], "self_seat": 0,
        })
        self.assertTrue(tracker.state.in_game)
        self.assertEqual(len(tracker.state.players[0].hand), 13)
        self.assertEqual(tracker.state.self_seat, 0)
        self.assertEqual(tracker.state.last_action, "new_round")

        tracker.on_game_event("draw_tile", {"seat": 0, "tile": tile_id(0, 5), "left_count": 69})
        self.assertEqual(tracker.state.last_action, "draw")
        self.assertEqual(len(tracker.state.players[0].hand), 14)
        self.assertEqual(tracker.state.left_tiles, 69)

        tracker.on_game_event("discard_tile", {"seat": 0, "tile": tile_id(0, 5), "is_liqi": False})
        self.assertEqual(tracker.state.last_action, "discard")
        self.assertEqual(tracker.state.last_discard_seat, 0)
        self.assertEqual(len(tracker.state.players[0].hand), 13)

        tracker.on_game_event("discard_tile", {"seat": 1, "tile": tile_id(0, 7), "is_liqi": False})
        self.assertEqual(tracker.state.last_discard_seat, 1)
        self.assertEqual(tracker.state.last_discard, tile_id(0, 7))


class TestAIDecision(unittest.TestCase):
    """AI 决策测试"""

    def test_ai_decide_discard_returns_action(self):
        """AI 出牌决策应返回有效的 GameAction"""
        ai = AIDecisionMaker()
        state = GameState()
        hand = make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p","5m")
        state.players[0].hand = hand
        state.self_seat = 0
        state.in_game = True
        state.last_action = "draw"
        state.dora_indicator = 27
        clear_shanten_cache()
        action = ai.decide_discard(state)
        self.assertIsInstance(action, GameAction)
        self.assertEqual(action.action, ActionType.DISCARD)
        self.assertGreaterEqual(action.tile, 0)

    def test_ai_decide_discard_tenpai_hand(self):
        """听牌手牌 — 九莲宝灯14枚应已和牌"""
        ai = AIDecisionMaker()
        state = GameState()
        hand = make_hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","9m","9m","9m","1m")
        state.players[0].hand = hand
        state.self_seat = 0
        state.in_game = True
        state.last_action = "draw"
        state.dora_indicator = -1
        clear_shanten_cache()
        shanten = cached_shanten(hand)
        self.assertEqual(shanten, -1)

    def test_decide_call_pon(self):
        """碰牌决策: 有2张+对手打1张 → 应碰"""
        ai = AIDecisionMaker()
        ai.params.aggression = 0.8
        state = GameState()
        hand = make_hand("5m","5m","1m","2m","3m","2p","4p","6s","8s","3z","5z","7z","9m")
        state.players[0].hand = hand
        state.self_seat = 0
        state.in_game = True
        clear_shanten_cache()
        result = ai.decide_call(state, tile_id(0, 5), "pon")
        self.assertIsInstance(result, GameAction)
        self.assertEqual(result.action, ActionType.PON)

    def test_decide_call_pass_no_pair(self):
        """碰牌决策: 无对子 → 应跳过"""
        ai = AIDecisionMaker()
        state = GameState()
        hand = make_hand("5m","1m","2m","3m","7m","8m","9m","2p","3p","4p","6s","7s","8s")
        state.players[0].hand = hand
        state.self_seat = 0
        result = ai.decide_call(state, tile_id(0, 5), "pon")
        self.assertEqual(result.action, ActionType.PASS)


class TestMobileExecutor(unittest.TestCase):
    """MobileActionExecutor 基本测试"""

    def test_mobile_executor_no_device(self):
        """无设备时 MobileActionExecutor 应能正常初始化"""
        from action.mobile_executor import MobileActionExecutor
        executor = MobileActionExecutor()
        self.assertFalse(executor.connected)
        self.assertEqual(executor.action_count, 0)
        self.assertEqual(executor.fail_count, 0)
        action = GameAction(ActionType.DISCARD, tile_id(0, 1))
        ok = executor.execute(action)
        self.assertFalse(ok)
        self.assertEqual(executor.fail_count, 1)

    def test_mobile_layout_config(self):
        """移动端布局配置应包含必要键"""
        from action.mobile_executor import MobileLayout
        required_keys = [
            "hand_y_top", "hand_y_bottom", "hand_x_left", "hand_x_right",
            "buttons_y_ratio", "pon_x", "chi_x", "kan_x",
            "riichi_x", "ron_x", "tsumo_x", "pass_x",
        ]
        for key in required_keys:
            self.assertIn(key, MobileLayout.PORTRAIT)
            self.assertIn(key, MobileLayout.LANDSCAPE)


class TestBoundaryCases(unittest.TestCase):
    """边界情况"""

    def test_empty_hand_shanten(self):
        """空手牌向听数"""
        self.assertEqual(ShantenCalculator.calculate([]), -1)

    def test_seen_tiles_tracking(self):
        """已见牌追踪"""
        tracker = GameTracker()
        tracker.on_game_event("new_round", {
            "chang": 0, "ju": 0, "ben": 0, "oya": 0,
            "tiles": make_hand("1m","1m","1m"),
            "dora_indicator": 27,
            "scores": [25000, 25000, 25000, 25000],
            "self_seat": 0,
        })
        self.assertEqual(tracker.state.get_seen_count(0), 3)
        self.assertEqual(tracker.state.get_remaining(0), 1)


if __name__ == "__main__":
    unittest.main()
