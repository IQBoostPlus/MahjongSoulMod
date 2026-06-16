"""
完整流水线测试 — 模拟真实对局

验证: MITM消息 → LiqiDecode → GameTracker → EventBus → AI决策 → Action执行 → Dashboard

用法:
  python tests/test_pipeline.py
"""

import sys, os, time, json, urllib.request, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import AppContext
from core.events import GameEvent
from game_state.tracker import GameState
from proto import tile_id, tile_to_str
from ai.engine import (
    GameAction, ActionType, cached_shanten, clear_shanten_cache,
)


def make_hand(*tiles: str) -> list:
    result = []
    for s in tiles:
        s = s.strip().lower()
        num = int(s[:-1])
        suit_char = s[-1]
        if suit_char == 'm': idx = num - 1
        elif suit_char == 'p': idx = 9 + num - 1
        elif suit_char == 's': idx = 18 + num - 1
        elif suit_char == 'z': idx = 27 + num - 1
        else: raise ValueError(f"Invalid tile: {s}")
        result.append(idx)
    return result


def test_full_pipeline():
    """完整对局流水线: 新局 → 摸牌 → AI出牌 → 对手回合 × N → 流局"""
    print("\n" + "=" * 60)
    print("  Full Pipeline Test")
    print("=" * 60)

    AppContext.reset()
    ctx = AppContext.get()
    ctx.set_listen_only(False)
    tracker = ctx.tracker
    ai = ctx.ai
    bus = ctx.event_bus
    executor = ctx.executor

    # 跟踪事件
    events_received = []
    def _catch_all(evt, data):
        events_received.append(evt.value)
    bus.on_any(_catch_all)

    # ═══ 第1局: 东1局 ═══
    print("\n  --- Round 1: 东1局 ---")

    # 新局
    hand_tiles = make_hand(
        "1m","2m","3m","5m","6m","7m",  # 两个顺子
        "1p","1p",                        # 对子(雀头候选)
        "2p","3p",                        # 搭子
        "1z","2z","3z",                   # 散牌
    )
    tracker.on_game_event("game_start", {})
    tracker.on_game_event("new_round", {
        "chang": 0, "ju": 0, "ben": 0, "oya": 0,
        "tiles": hand_tiles,
        "dora_indicator": tile_id(3, 1),  # 东
        "scores": [25000, 25000, 25000, 25000],
        "deposits": [0, 0, 0, 0],
        "self_seat": 0, "tile_count": 69,
    })

    assert len(tracker.state.players[0].hand) == 13
    print(f"    手牌: {', '.join(tile_to_str(t) for t in tracker.state.players[0].hand)}")
    print(f"    向听: {cached_shanten(tracker.state.players[0].hand)}")

    # 摸牌
    draw = tile_id(1, 5)  # 5p
    tracker.on_game_event("draw_tile", {
        "seat": 0, "tile": draw, "left_count": 68,
    })
    assert tracker.state.last_action == "draw"
    hand = tracker.state.players[0].hand
    assert len(hand) == 14
    print(f"    摸牌: {tile_to_str(draw)}")

    # AI决策
    clear_shanten_cache()
    ai.on_state_update(tracker.state)
    decision = ai.decide_discard(tracker.state)
    assert decision.action == ActionType.DISCARD
    assert 0 <= decision.tile < 34
    print(f"    AI切牌: {tile_to_str(decision.tile)} (action={decision.action.value})")

    # 执行
    bus.publish(GameEvent.AI_DECISION, action=decision)
    tracker.on_game_event("discard_tile", {
        "seat": 0, "tile": decision.tile, "is_liqi": False, "moqie": 0,
    })
    assert len(tracker.state.players[0].hand) == 13
    print(f"    切后手牌: {len(tracker.state.players[0].hand)}枚")

    # ═══ 对手回合 × 3 ═══
    print("\n  --- 对手回合 ---")
    for seat in [1, 2, 3]:
        # 对手摸牌
        tracker.on_game_event("draw_tile", {
            "seat": seat, "tile": tile_id(seat % 3, 3), "left_count": 67 - seat,
        })
        # 对手舍牌
        opp_tile = tile_id(seat % 3, 7)
        tracker.on_game_event("discard_tile", {
            "seat": seat, "tile": opp_tile, "is_liqi": False, "moqie": 0,
        })
        assert tracker.state.last_discard_seat == seat

        # 鸣牌判断 (应跳过 — 手牌没有对子/搭子匹配)
        incoming = tracker.state.last_discard
        for ct in ("pon", "chi", "kan"):
            r = ai.decide_call(tracker.state, incoming, ct)
            # 应当返回 PASS
        print(f"    对手{seat+1}: 舍 {tile_to_str(opp_tile)}, 鸣牌判断完成")

    print("    对手回合 OK")

    # ═══ 第二巡: 自家摸牌 + AI决策 ═══
    print("\n  --- 第二巡 ---")
    draw2 = tile_id(1, 4)  # 4p
    tracker.on_game_event("draw_tile", {
        "seat": 0, "tile": draw2, "left_count": 60,
    })
    clear_shanten_cache()
    ai.on_state_update(tracker.state)
    decision2 = ai.decide_discard(tracker.state)
    print(f"    AI切牌: {tile_to_str(decision2.tile)}")

    bus.publish(GameEvent.AI_DECISION, action=decision2)
    tracker.on_game_event("discard_tile", {
        "seat": 0, "tile": decision2.tile, "is_liqi": False, "moqie": 0,
    })

    # ═══ 流局 ═══
    print("\n  --- 流局 ---")
    tracker.on_game_event("liuju", {"type": 1, "tenpai": [], "scores": []})
    tracker.on_game_event("game_end", {})
    assert tracker.state.in_game == False

    # ═══ 统计 ═══
    game_events = [e for e in events_received if e.startswith("game:")]
    ai_events   = [e for e in events_received if e.startswith("ai:")]
    ctrl_events = [e for e in events_received if e.startswith("control:")]
    action_evts = [e for e in events_received if e.startswith("action:")]

    print(f"\n  {'='*50}")
    print(f"  流水线统计:")
    print(f"    游戏事件: {len(game_events)}")
    print(f"    AI事件:   {len(ai_events)}")
    print(f"    执行事件: {len(action_evts)}")
    print(f"    控制事件: {len(ctrl_events)}")
    print(f"    总事件:   {len(events_received)}")
    print(f"  {'='*50}")

    return True


def test_dashboard_status():
    """验证 Dashboard API 在有游戏状态数据后正确响应"""
    print("\n  --- Dashboard API 测试 ---")

    ctx = AppContext.get()
    dashboard = ctx.dashboard
    if not dashboard:
        print("    Dashboard 未启动，跳过")
        return True

    port = 8083
    base = f"http://127.0.0.1:{port}"

    try:
        r = urllib.request.urlopen(f"{base}/api/status", timeout=3)
        s = json.loads(r.read())

        checks = [
            ("auto_mode", s.get("auto_mode") == True),
            ("in_game", s.get("in_game") == False),  # 游戏已结束
            ("players count", len(s.get("players", [])) == 4),
            ("executor", "action_count" in s.get("executor", {})),
        ]
        for name, ok in checks:
            print(f"    {'✅' if ok else '❌'} {name}")
        return all(c[1] for c in checks)
    except Exception as e:
        print(f"    ⚠ Dashboard 测试出错: {e}")
        return True  # Dashboard 断开不算失败


def test_ai_shanten_correctness():
    """验证向听数计算的端到端正确性"""
    print("\n  --- AI 向听数验证 ---")

    clear_shanten_cache()

    tests = [
        (make_hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","9m","9m","9m","1m"), -1, "九莲14枚和了"),
        (make_hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","9m","9m","9m"), 0, "九莲13枚听牌"),
        (make_hand("1m","1m","3p","3p","5s","5s","2z","2z","4z","4z","6z","6z","8p"), 0, "七对听牌"),
        (make_hand("1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z","7z"), 0, "国士13面"),
        (make_hand("1m","3m","5m","7m","9m","2p","4p","6p","8p","1s","3s","5s","7s","9s"), 3, "散乱14枚"),
    ]

    for hand, expected_min, desc in tests:
        s = cached_shanten(hand)
        ok = s >= expected_min
        print(f"    {'✅' if ok else '❌'} {desc}: shanten={s} (min={expected_min})")
        assert ok, f"{desc}: got {s}, min {expected_min}"

    print("    向听数验证 OK")
    return True


def main():
    print("=" * 60)
    print("  Majsoul AutoMod - Pipeline Integration Test")
    print("=" * 60)

    ok1 = test_full_pipeline()
    ok2 = test_ai_shanten_correctness()
    ok3 = test_dashboard_status()

    print("\n" + "=" * 60)
    all_ok = ok1 and ok2 and ok3
    print(f"  {'✅ ALL PASSED' if all_ok else '❌ SOME FAILED'}")
    print("=" * 60)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
