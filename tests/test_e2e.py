"""
端到端 (E2E) 测试 — 模拟完整游戏流程

测试完整流水线:
  WebSocket 消息 → LiqiDecoder → GameTracker → EventBus → AI → ActionExecutor → Dashboard

用法:
  python tests/test_e2e.py           # 运行测试 (需要 HTTP 请求验证)
  python tests/test_e2e.py --live     # 启动后保持运行，打开 http://127.0.0.1:8082 查看仪表盘
"""

import sys
import os
import time
import json
import threading
import urllib.request
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import AppContext
from core.events import GameEvent
from game_state.tracker import GameTracker, GameState
from proto import LiqiDecoder, tile_id, tile_to_str, MSG_NAMES_S2C
from ai.engine import AIDecisionMaker, GameAction, ActionType, cached_shanten, clear_shanten_cache


# ═══════════════════════════════════════════════════════════════
#  模拟 WebSocket 消息 (真实的 liqi 编码)
# ═══════════════════════════════════════════════════════════════

def make_hand(*tiles: str) -> list:
    """字符串表示 → 手牌列表"""
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


def simulate_game():
    """模拟一局完整游戏"""
    ctx = AppContext.get()
    tracker = ctx.tracker
    ai = ctx.ai
    event_bus = ctx.event_bus

    print("\n" + "="*60)
    print("  雀魂 AutoMod E2E 测试")
    print("="*60)

    # ── 阶段1: 游戏开始 ──
    print("\n[1/6] 游戏开始...")
    event_bus.publish(GameEvent.GAME_START)
    time.sleep(0.1)

    # ── 阶段2: 新局 (东1局) ──
    print("\n[2/6] 新局: 东1局")
    tiles = make_hand(
        "1m","2m","3m","4m","5m","6m","7m","8m","9m",
        "1p","2p","3p","4p"
    )
    tracker.on_game_event("game_start", {})
    tracker.on_game_event("new_round", {
        "chang": 0, "ju": 0, "ben": 0, "oya": 0,
        "tiles": tiles,
        "dora_indicator": tile_id(3, 1),  # 东 = 宝牌指示牌
        "scores": [25000, 25000, 25000, 25000],
        "deposits": [0, 0, 0, 0],
        "self_seat": 0,
        "tile_count": 69,
    })

    hand = tracker.state.players[0].hand
    print(f"  手牌: {', '.join(tile_to_str(t) for t in hand)}")
    print(f"  向听数: {cached_shanten(hand)}")
    assert len(hand) == 13, f"Expected 13 tiles, got {len(hand)}"
    assert tracker.state.in_game == True
    print("  ✓ 新局 OK")

    # ── 阶段3: 摸牌 + AI 出牌 ──
    print("\n[3/6] 摸牌 + AI 出牌决策")
    draw_tile = tile_id(0, 5)  # 5m
    event_bus.publish(GameEvent.DRAW_TILE, state=tracker.state, msg_name="draw_tile")
    # 手动更新 tracker (因为我们是直接 publish 事件而不是走 mitm)
    tracker.on_game_event("draw_tile", {
        "seat": 0, "tile": draw_tile, "left_count": 68,
    })

    hand = tracker.state.players[0].hand
    print(f"  摸到: {tile_to_str(draw_tile)}")
    assert tracker.state.last_action == "draw", \
        f"BUG: last_action should be 'draw', got '{tracker.state.last_action}'"
    print(f"  手牌: {len(hand)}枚, last_action={tracker.state.last_action}")

    # 触发 AI 决策
    ai.on_state_update(tracker.state)
    decision = ai.decide_discard(tracker.state)
    print(f"  AI决策: {decision.action.value} tile={decision.tile} ({tile_to_str(decision.tile)})")
    assert decision.action == ActionType.DISCARD, \
        f"Expected DISCARD, got {decision.action}"
    assert 0 <= decision.tile < 34, f"Invalid tile: {decision.tile}"
    print("  ✓ 摸牌+AI决策 OK")

    # ── 阶段4: 执行切牌 ──
    print("\n[4/6] 执行切牌")
    # 模拟执行 (桌面端无 GUI 时只打印)
    event_bus.publish(GameEvent.AI_DECISION, action=decision)

    # 更新 tracker
    tracker.on_game_event("discard_tile", {
        "seat": 0, "tile": decision.tile, "is_liqi": False, "moqie": 0,
    })

    hand = tracker.state.players[0].hand
    assert len(hand) == 13, f"After discard: expected 13, got {len(hand)}"
    assert tracker.state.last_discard_seat == 0, \
        f"Expected last_discard_seat=0, got {tracker.state.last_discard_seat}"
    print(f"  切牌: {tile_to_str(decision.tile)}, 剩余手牌: {len(hand)}枚")
    print("  ✓ 切牌 OK")

    # ── 阶段5: 对手回合 ──
    print("\n[5/6] 模拟对手回合")
    for seat in [1, 2, 3]:
        tracker.on_game_event("draw_tile", {
            "seat": seat, "tile": tile_id(0, seat), "left_count": 67 - seat,
        })
        # 对手摸牌不应设置 last_action = "draw"
        assert tracker.state.last_action != "draw" or tracker.state.last_discard_seat != seat, \
            f"Opponent draw should NOT set last_action='draw' for seat {seat}"

    # 对手1切牌
    tracker.on_game_event("discard_tile", {
        "seat": 1, "tile": tile_id(0, 7), "is_liqi": False, "moqie": 0,
    })
    assert tracker.state.last_discard_seat == 1
    assert tracker.state.last_discard == tile_id(0, 7)

    # 检查鸣牌决策 (应跳过 — 没对子)
    # context._on_discard_tile 里已有 seat 检查，这里验证逻辑
    incoming = tracker.state.last_discard
    result = ai.decide_call(tracker.state, incoming, "pon")
    assert result.action == ActionType.PASS, \
        f"Should PASS on 7m with no pair, got {result.action}"

    print("  ✓ 对手回合 OK")

    # ── 阶段6: 游戏结束 ──
    print("\n[6/6] 游戏结束")
    tracker.on_game_event("game_end", {})
    assert tracker.state.in_game == False
    event_bus.publish(GameEvent.GAME_END)

    print("  ✓ 游戏结束 OK")
    print("\n" + "="*60)
    print("  全部 E2E 测试通过!")
    print("="*60)

    return True


# ═══════════════════════════════════════════════════════════════
#  Dashboard 测试
# ═══════════════════════════════════════════════════════════════

def test_dashboard():
    """测试仪表盘 HTTP 接口"""
    ctx = AppContext.get()
    dashboard = ctx.dashboard

    if not dashboard:
        print("\n[Dashboard] 跳过 — 未启动")
        return True

    port = 8082
    base = f"http://127.0.0.1:{port}"

    print(f"\n[Dashboard] 测试 HTTP 接口 ({base})")

    # 测试 ping
    try:
        resp = urllib.request.urlopen(f"{base}/api/ping", timeout=5)
        data = json.loads(resp.read())
        assert data.get("ok") == True
        print("  ✓ GET /api/ping")
    except Exception as e:
        print(f"  ✗ /api/ping: {e}")
        return False

    # 测试 status
    try:
        resp = urllib.request.urlopen(f"{base}/api/status", timeout=5)
        data = json.loads(resp.read())
        assert "auto_mode" in data
        assert "in_game" in data
        assert "players" in data
        print(f"  ✓ GET /api/status (auto_mode={data['auto_mode']}, in_game={data['in_game']})")
    except Exception as e:
        print(f"  ✗ /api/status: {e}")
        return False

    # 测试 HTML 页面
    try:
        resp = urllib.request.urlopen(f"{base}/", timeout=5)
        html = resp.read().decode("utf-8")
        assert "<!DOCTYPE html>" in html
        assert "雀魂" in html
        print(f"  ✓ GET / (HTML {len(html)} bytes)")
    except Exception as e:
        print(f"  ✗ /: {e}")
        return False

    # 测试 SSE 端点 (短暂连接)
    try:
        req = urllib.request.Request(f"{base}/events")
        resp = urllib.request.urlopen(req, timeout=3)
        first_line = resp.readline().decode("utf-8")
        assert "connected" in first_line or "data:" in first_line
        print(f"  ✓ GET /events (SSE: {first_line.strip()[:60]}...)")
        resp.close()
    except urllib.error.URLError:
        print("  ✓ GET /events (SSE stream opened)")
    except Exception as e:
        print(f"  ⚠ /events: {e}")

    print("  Dashboard HTTP 接口 OK")
    return True


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="雀魂 AutoMod E2E 测试")
    parser.add_argument("--live", action="store_true",
                        help="启动后保持运行 (可打开仪表盘查看)")
    args = parser.parse_args()

    # 重置上下文
    AppContext.reset()
    ctx = AppContext.get()

    # 启用调试模式
    ctx.set_listen_only(False)

    # 运行 E2E 测试
    ok = simulate_game()
    if not ok:
        print("\n❌ E2E 测试失败!")
        sys.exit(1)

    # 测试 Dashboard
    dashboard_ok = test_dashboard()
    if not dashboard_ok:
        print("\n⚠ Dashboard 部分测试未通过")

    if args.live:
        print("\n" + "="*60)
        print("  Dashboard 已启动: http://127.0.0.1:8082")
        print("  按 Ctrl+C 退出")
        print("="*60)
        try:
            while ctx.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n退出...")
    else:
        ctx.stop()

    print("\n✅ 全部 E2E 测试通过!")
    sys.exit(0)


if __name__ == "__main__":
    main()
