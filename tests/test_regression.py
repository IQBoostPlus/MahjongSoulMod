"""
回归测试 — 验证 Bug 修复和移动端适配

测试覆盖:
  1. Bug #1: _on_draw_tile 设置 last_action = "draw"
  2. Bug #2: _should_kan 检查 3 张而不是 4 张
  3. Bug #3: 自家舍牌不触发鸣牌
  4. GameTracker 集成流程
  5. AI 决策生成 GameAction
  6. MobileActionExecutor 基本功能 (ADB 不可用时)
"""

import sys
import os
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


# ═══════════════════════════════════════════════════════════════
#  Bug #1: last_action = "draw" 修复验证
# ═══════════════════════════════════════════════════════════════

def test_draw_tile_sets_last_action():
    """摸牌后 GameState.last_action 应为 'draw'"""
    tracker = GameTracker()

    # 模拟新局开始
    tracker.on_game_event("new_round", {
        "chang": 0, "ju": 0, "ben": 0, "oya": 0,
        "tiles": make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p"),
        "dora_indicator": 27,
        "scores": [25000, 25000, 25000, 25000],
        "self_seat": 0,
    })

    # 模拟自家摸牌
    tracker.on_game_event("draw_tile", {
        "seat": 0,
        "tile": tile_id(0, 5),  # 5m
        "left_count": 69,
    })

    assert tracker.state.last_action == "draw", \
        f"Expected last_action='draw', got '{tracker.state.last_action}'"
    assert len(tracker.state.players[0].hand) == 14, \
        f"Expected 14 tiles in hand, got {len(tracker.state.players[0].hand)}"


def test_opponent_draw_does_not_set_last_action_draw():
    """对手摸牌不应设置 last_action = 'draw'"""
    tracker = GameTracker()

    tracker.on_game_event("new_round", {
        "chang": 0, "ju": 0, "ben": 0, "oya": 0,
        "tiles": make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p"),
        "dora_indicator": 27,
        "scores": [25000, 25000, 25000, 25000],
        "self_seat": 0,
    })

    # 模拟对手 (seat=1) 摸牌
    tracker.on_game_event("draw_tile", {
        "seat": 1,
        "tile": tile_id(2, 5),  # 5s
        "left_count": 69,
    })

    # 对手摸牌时 last_action 不应是 "draw"
    # (只有自家摸牌才设置)
    # 此时 last_action 仍是 "new_round"
    assert tracker.state.last_action != "draw", \
        "Opponent draw should NOT set last_action='draw'"


# ═══════════════════════════════════════════════════════════════
#  Bug #2: _should_kan 修复验证
# ═══════════════════════════════════════════════════════════════

def test_should_kan_with_3_copies():
    """_should_kan: 手中有3张相同牌时应允许明杠 (来自对手舍牌)"""
    ai = AIDecisionMaker()
    ai.params.risk_tolerance = 0.5

    state = GameState()
    # 13张手牌 (对手舍牌时的正常状态)
    # 3张1m + 其他不构成和了形的散牌
    hand = make_hand("1m","1m","1m",
                     "2m","4m","6m","8m",
                     "1p","3p","5p",
                     "2s","5s","8s")
    state.players[0].hand = hand
    state.self_seat = 0

    clear_shanten_cache()
    result = ai._should_kan(state, tile_id(0, 1), hand)
    assert result == True, \
        f"_should_kan with 3 copies should return True (shanten={cached_shanten(hand)})"


def test_should_kan_rejects_2_copies():
    """_should_kan: 手中只有2张相同牌时不应杠"""
    ai = AIDecisionMaker()
    ai.params.risk_tolerance = 0.5

    state = GameState()
    hand = make_hand("1m","1m",  # 只有2张
                     "2m","3m","4m","5m","6m","7m","8m","9m",
                     "1p","2p","3p","4p")
    state.players[0].hand = hand

    result = ai._should_kan(state, tile_id(0, 1), hand)
    assert result == False, \
        f"_should_kan with 2 copies should return False"


# ═══════════════════════════════════════════════════════════════
#  Bug #3: 自家舍牌跳过鸣牌验证
# ═══════════════════════════════════════════════════════════════

def test_discard_tile_sets_last_discard_seat():
    """舍牌后 last_discard_seat 应正确设置"""
    tracker = GameTracker()

    tracker.on_game_event("new_round", {
        "chang": 0, "ju": 0, "ben": 0, "oya": 0,
        "tiles": make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p"),
        "dora_indicator": 27,
        "scores": [25000, 25000, 25000, 25000],
        "self_seat": 0,
    })

    # 对手 seat=1 舍牌
    tracker.on_game_event("discard_tile", {
        "seat": 1,
        "tile": tile_id(0, 5),
        "is_liqi": False,
        "moqie": 0,
    })

    assert tracker.state.last_discard_seat == 1, \
        f"Expected last_discard_seat=1, got {tracker.state.last_discard_seat}"
    assert tracker.state.last_discard == tile_id(0, 5), \
        f"Expected last_discard=5m"


def test_own_discard_sets_last_discard_seat():
    """自家舍牌后 last_discard_seat 应为 self_seat"""
    tracker = GameTracker()

    tracker.on_game_event("new_round", {
        "chang": 0, "ju": 0, "ben": 0, "oya": 0,
        "tiles": make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p"),
        "dora_indicator": 27,
        "scores": [25000, 25000, 25000, 25000],
        "self_seat": 0,
    })

    # 自家舍牌
    tracker.on_game_event("discard_tile", {
        "seat": 0,
        "tile": tile_id(1, 9),
        "is_liqi": False,
        "moqie": 1,
    })

    assert tracker.state.last_discard_seat == 0, \
        f"Expected last_discard_seat=0, got {tracker.state.last_discard_seat}"


# ═══════════════════════════════════════════════════════════════
#  GameTracker 集成流程
# ═══════════════════════════════════════════════════════════════

def test_full_round_flow():
    """完整一局的 tracker 流程测试"""
    tracker = GameTracker()

    # 1. 游戏开始
    tracker.on_game_event("game_start", {})

    # 2. 新局
    tiles = make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p")
    tracker.on_game_event("new_round", {
        "chang": 0, "ju": 0, "ben": 0, "oya": 0,
        "tiles": tiles,
        "dora_indicator": 27,
        "scores": [25000, 25000, 25000, 25000],
        "self_seat": 0,
    })

    assert tracker.state.in_game == True
    assert len(tracker.state.players[0].hand) == 13
    assert tracker.state.self_seat == 0
    assert tracker.state.last_action == "new_round"

    # 3. 自家摸牌
    tracker.on_game_event("draw_tile", {"seat": 0, "tile": tile_id(0, 5), "left_count": 69})
    assert tracker.state.last_action == "draw"
    assert len(tracker.state.players[0].hand) == 14
    assert tracker.state.left_tiles == 69

    # 4. 自家切牌 (切5m, 在手牌中的牌)
    tracker.on_game_event("discard_tile", {"seat": 0, "tile": tile_id(0, 5), "is_liqi": False})
    assert tracker.state.last_action == "discard"
    assert tracker.state.last_discard_seat == 0
    # 手牌应减少1张
    assert len(tracker.state.players[0].hand) == 13

    # 5. 对手舍牌
    tracker.on_game_event("discard_tile", {"seat": 1, "tile": tile_id(0, 7), "is_liqi": False})
    assert tracker.state.last_discard_seat == 1
    assert tracker.state.last_discard == tile_id(0, 7)


# ═══════════════════════════════════════════════════════════════
#  AI 决策测试
# ═══════════════════════════════════════════════════════════════

def test_ai_decide_discard_returns_action():
    """AI 出牌决策应返回有效的 GameAction"""
    ai = AIDecisionMaker()
    state = GameState()

    hand = make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m",
                     "1p","2p","3p","4p","5m")  # 14张 (摸牌后)
    state.players[0].hand = hand
    state.self_seat = 0
    state.in_game = True
    state.last_action = "draw"
    state.dora_indicator = 27

    clear_shanten_cache()
    action = ai.decide_discard(state)

    assert isinstance(action, GameAction), "Should return GameAction"
    assert action.action == ActionType.DISCARD, \
        f"Expected DISCARD, got {action.action}"
    assert action.tile >= 0, f"Expected valid tile, got {action.tile}"


def test_ai_decide_discard_tenpai_hand():
    """听牌手牌应正常决策"""
    ai = AIDecisionMaker()
    state = GameState()

    # 听牌手牌 (14张摸牌后)
    hand = make_hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","9m","9m","9m","1m")
    state.players[0].hand = hand
    state.self_seat = 0
    state.in_game = True
    state.last_action = "draw"
    state.dora_indicator = -1

    clear_shanten_cache()
    shanten = cached_shanten(hand)
    # 九莲宝灯14枚应已和牌
    assert shanten == -1, f"Nine gates 14 tiles should be -1 (agari), got {shanten}"


def test_decide_call_pon():
    """碰牌决策: 有2张+对手打1张 → 碰后向听前进时应碰"""
    ai = AIDecisionMaker()
    ai.params.aggression = 0.8
    state = GameState()

    # 手牌: 2张5m作对子 + 散乱牌 → 向听数较高
    # 碰5m后消耗对子但得到面子，向听数减少
    hand = make_hand("5m","5m",   # 对子 (将被碰掉)
                     "1m","2m","3m",  # 顺子
                     "2p","4p",       # 坎张搭子
                     "6s","8s",       # 坎张搭子
                     "3z","5z","7z",  # 散乱字牌
                     "9m")            # 孤张
    state.players[0].hand = hand
    state.self_seat = 0
    state.in_game = True

    clear_shanten_cache()
    before = cached_shanten(hand)
    result = ai.decide_call(state, tile_id(0, 5), "pon")  # 对手打5m

    assert isinstance(result, GameAction)
    assert result.action == ActionType.PON, \
        f"Should PON on 5m (shanten {before}→?), got {result.action}"


def test_decide_call_pass_no_pair():
    """碰牌决策: 无对子 → 应跳过"""
    ai = AIDecisionMaker()
    state = GameState()

    hand = make_hand("5m",  # 只有1张
                     "1m","2m","3m","7m","8m","9m",
                     "2p","3p","4p","6s","7s","8s")
    state.players[0].hand = hand
    state.self_seat = 0

    result = ai.decide_call(state, tile_id(0, 5), "pon")
    assert result.action == ActionType.PASS, \
        f"Should PASS with only 1 copy, got {result.action}"


# ═══════════════════════════════════════════════════════════════
#  MobileActionExecutor 基本测试 (无 ADB)
# ═══════════════════════════════════════════════════════════════

def test_mobile_executor_no_device():
    """无设备时 MobileActionExecutor 应能正常初始化"""
    from action.mobile_executor import MobileActionExecutor

    executor = MobileActionExecutor()
    assert executor.connected == False
    assert executor.action_count == 0
    assert executor.fail_count == 0

    # 无设备时 execute 应安全返回 False
    action = GameAction(ActionType.DISCARD, tile_id(0, 1))
    ok = executor.execute(action)
    assert ok == False, "Should return False when not connected"
    assert executor.fail_count == 1


def test_mobile_layout_config():
    """移动端布局配置应包含必要键"""
    from action.mobile_executor import MobileLayout

    required_keys = [
        "hand_y_top", "hand_y_bottom",
        "hand_x_left", "hand_x_right",
        "buttons_y_ratio",
        "pon_x", "chi_x", "kan_x",
        "riichi_x", "ron_x", "tsumo_x", "pass_x",
    ]

    for key in required_keys:
        assert key in MobileLayout.PORTRAIT, f"PORTRAIT missing key: {key}"
        assert key in MobileLayout.LANDSCAPE, f"LANDSCAPE missing key: {key}"


# ═══════════════════════════════════════════════════════════════
#  GameState 边界情况
# ═══════════════════════════════════════════════════════════════

def test_empty_hand_shanten():
    """空手牌向听数"""
    s = ShantenCalculator.calculate([])
    assert s == -1


def test_seen_tiles_tracking():
    """已见牌追踪"""
    tracker = GameTracker()
    tracker.on_game_event("new_round", {
        "chang": 0, "ju": 0, "ben": 0, "oya": 0,
        "tiles": make_hand("1m","1m","1m"),
        "dora_indicator": 27,
        "scores": [25000, 25000, 25000, 25000],
        "self_seat": 0,
    })

    # 1m 应显示3张已见 (手牌中3张)
    assert tracker.state.get_seen_count(0) == 3
    # 已见后剩余
    assert tracker.state.get_remaining(0) == 1


# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [
        ("Bug#1: 摸牌设置last_action=draw", test_draw_tile_sets_last_action),
        ("Bug#1: 对手摸牌不设draw", test_opponent_draw_does_not_set_last_action_draw),
        ("Bug#2: _should_kan 3张明杠", test_should_kan_with_3_copies),
        ("Bug#2: _should_kan 拒绝2张", test_should_kan_rejects_2_copies),
        ("Bug#3: 舍牌设置last_discard_seat", test_discard_tile_sets_last_discard_seat),
        ("Bug#3: 自家舍牌seat记录", test_own_discard_sets_last_discard_seat),
        ("集成: 完整一局流程", test_full_round_flow),
        ("AI: 出牌决策返回GameAction", test_ai_decide_discard_returns_action),
        ("AI: 听牌九莲宝灯", test_ai_decide_discard_tenpai_hand),
        ("AI: 碰牌决策", test_decide_call_pon),
        ("AI: 碰牌跳过无对子", test_decide_call_pass_no_pair),
        ("Mobile: 无设备安全初始化", test_mobile_executor_no_device),
        ("Mobile: 布局配置完整性", test_mobile_layout_config),
        ("边界: 空手牌向听", test_empty_hand_shanten),
        ("边界: 已见牌追踪", test_seen_tiles_tracking),
    ]

    passed = 0
    failed = 0

    for name, test in tests:
        try:
            test()
            print(f"  PASS: {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  FAIL: {name}: EXCEPTION: {e}")
            failed += 1
            import traceback
            traceback.print_exc()

    print(f"\nResult: {passed}/{passed + failed} passed")
    sys.exit(0 if failed == 0 else 1)
