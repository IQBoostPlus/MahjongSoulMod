"""
帧差分 — 从连续 VisionFrame 推断游戏事件

比较前后两帧的差异, 生成 VisionEvent 列表。
这些事件随后由 VisionEventProcessor 喂给 GameTracker,
与 MITM 模式使用完全相同的接口。

检测策略:
  - GAME_START: 首次检测到手牌 (空→非空)
  - NEW_ROUND: 手牌重置 (13张 → 13张但内容大变)
  - DRAW_TILE: 手牌 13→14 且摸牌区非空
  - DISCARD_TILE: 任意牌河 +1
  - CHI/PON/KAN: 副露区新 meld + 手牌减少
  - RIICHI: 立直按钮出现→消失 / 分数减1000
  - TSUMO/RON: 和牌按钮出现
  - GAME_END: 所有区域变空

用法:
    differ = StatefulDiffer()
    events = differ.diff(prev_frame, curr_frame)
    # → [VisionEvent("draw_tile", {"seat": 0, "tile": 5}), ...]
"""

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from utils.log import Logger


# ═══════════════════════════════════════════════════════════════
#  VisionEvent
# ═══════════════════════════════════════════════════════════════

@dataclass
class VisionEvent:
    """
    从帧差分推断出的游戏事件。

    type:  事件类型字符串 — 与 GameTracker.on_game_event() 的 msg_name 对应
    data:  事件数据字典 — 与 GameTracker 各处理器的参数对应
    conf:  推断置信度 (0.0~1.0), 用于调试/过滤
    """
    event_type: str
    data: dict = field(default_factory=dict)
    confidence: float = 0.0
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def __repr__(self):
        return f"VisionEvent({self.event_type}, conf={self.confidence:.2f})"


# ═══════════════════════════════════════════════════════════════
#  StateDiffer (基础版)
# ═══════════════════════════════════════════════════════════════

class StateDiffer:
    """
    基础帧差分器。

    比较连续两帧, 返回检测到的事件列表。
    不对噪声做处理 — 每帧差异都如实报告。
    """

    def __init__(self):
        self._prev: Optional["VisionFrame"] = None  # 上一帧

    def diff(self, current: "VisionFrame") -> List[VisionEvent]:
        """
        比较当前帧与上一帧, 返回事件列表。

        第一次调用时只缓存, 不产生事件。
        """
        if self._prev is None:
            self._prev = current
            # 首帧: 检测是否已在游戏中
            if current.hand_count >= 13:
                return [VisionEvent("game_start", {}, 0.8)]
            return []

        events = []

        # ── 游戏生命周期 ──
        if self._detect_game_start(self._prev, current):
            events.append(VisionEvent("game_start", {}, 0.9))

        if self._detect_new_round(self._prev, current):
            events.append(self._build_new_round_event(current))

        if self._detect_game_end(self._prev, current):
            events.append(VisionEvent("game_end", {}, 0.9))

        # ── 摸牌 (自家手牌 13→14) ──
        draw_event = self._detect_draw(self._prev, current)
        if draw_event:
            events.append(draw_event)

        # ── 舍牌 (任意座位牌河增长) ──
        for seat in range(4):
            disc_event = self._detect_discard_at_seat(self._prev, current, seat)
            if disc_event:
                events.append(disc_event)

        # ── 鸣牌 (副露增长) ──
        meld_events = self._detect_melds(self._prev, current)
        events.extend(meld_events)

        # ── 按钮事件 ──
        btn_events = self._detect_button_events(self._prev, current)
        events.extend(btn_events)

        self._prev = current
        return events

    def reset(self):
        """重置状态 (新对局开始时调用)"""
        self._prev = None

    # ── 检测方法 ──

    def _detect_game_start(self, prev: "VisionFrame", cur: "VisionFrame") -> bool:
        """检测游戏开始: 从无牌→有牌"""
        return (prev.hand_count < 5 and cur.hand_count >= 13)

    def _detect_new_round(self, prev: "VisionFrame", cur: "VisionFrame") -> bool:
        """
        检测新局: 手牌从非空重置为 13 张且大部分牌变了。

        通过比较手牌集合的交集比例判断:
          如果交集 < 30% → 手牌被完全替换 → 新局
        """
        if prev.hand_count >= 10 and cur.hand_count == 13:
            # 计算手牌重叠度
            prev_set = set(prev.hand_tiles)
            cur_set = set(cur.hand_tiles)
            if prev_set and cur_set:
                overlap = len(prev_set & cur_set)
                max_size = max(len(prev_set), len(cur_set))
                if max_size > 0 and overlap / max_size < 0.3:
                    return True

            # 额外条件: 所有牌河都清空了
            all_empty = all(len(cur.discards[s]) == 0 for s in range(4))
            if all_empty:
                return True

        return False

    def _detect_game_end(self, prev: "VisionFrame", cur: "VisionFrame") -> bool:
        """检测游戏结束: 手牌从有→无"""
        return (prev.hand_count >= 10 and cur.hand_count < 5)

    def _detect_draw(self, prev: "VisionFrame", cur: "VisionFrame") -> Optional[VisionEvent]:
        """检测自家摸牌: 手牌 13→14"""
        if prev.hand_count == 13 and cur.hand_count == 14:
            # 找新增的牌
            prev_set = set(prev.hand_tiles)
            cur_list = cur.hand_tiles
            new_tiles = []

            # 用计数方式找差异 (处理对子场景)
            from collections import Counter
            prev_c = Counter(prev.hand_tiles)
            cur_c = Counter(cur.hand_tiles)

            for tile, count in cur_c.items():
                diff = count - prev_c.get(tile, 0)
                for _ in range(diff):
                    new_tiles.append(tile)

            tile = new_tiles[0] if new_tiles else (cur.draw_tile or cur.hand_tiles[-1])

            return VisionEvent("draw_tile", {
                "seat": 0,
                "tile": tile,
                "left_count": max(0, 70 - cur.hand_count),
            }, 0.85)

        return None

    def _detect_discard_at_seat(self, prev: "VisionFrame", cur: "VisionFrame",
                                  seat: int) -> Optional[VisionEvent]:
        """检测某座位的舍牌"""
        prev_river = set(prev.discards[seat]) if seat < len(prev.discards) else set()
        cur_river = cur.discards[seat] if seat < len(cur.discards) else []

        # 牌河增长
        if len(cur_river) > len(prev_river):
            # 找新增牌
            for tile in cur_river:
                if tile not in prev_river:
                    # 检测是否立直宣言 (自家分-1000, 立直棒+1)
                    is_liqi = 0
                    if cur.riichi_sticks > prev.riichi_sticks:
                        is_liqi = 1

                    return VisionEvent("discard_tile", {
                        "seat": seat,
                        "tile": tile,
                        "is_liqi": is_liqi,
                        "moqie": 0,  # 视觉难判断手切/摸切
                    }, 0.9)

        return None

    def _detect_melds(self, prev: "VisionFrame", cur: "VisionFrame") -> List[VisionEvent]:
        """检测副露变化"""
        events = []

        for seat in range(4):
            prev_count = len(prev.melds[seat]) if seat < len(prev.melds) else 0
            cur_count = len(cur.melds[seat]) if seat < len(cur.melds) else 0

            if cur_count > prev_count:
                # 新副露
                new_meld = cur.melds[seat][-1] if cur.melds[seat] else None
                meld_type = new_meld.meld_type if new_meld else "pon"

                # 鸣牌事件类型
                event_type_map = {
                    "chi": "chi", "pon": "pon",
                    "kan_ming": "kan", "kan_an": "an_kan", "kan_jia": "add_kan",
                }
                evt_type = event_type_map.get(meld_type, "pon")

                events.append(VisionEvent(evt_type, {
                    "seat": seat,
                    "tile": new_meld.tiles[0] if new_meld and new_meld.tiles else -1,
                    "from": new_meld.called_from if new_meld else -1,
                }, 0.8))

        return events

    def _detect_button_events(self, prev: "VisionFrame", cur: "VisionFrame") -> List[VisionEvent]:
        """检测按钮出现/消失事件"""
        events = []

        prev_btns = set(prev.visible_buttons)
        cur_btns = set(cur.visible_buttons)

        # 新出现的按钮
        appeared = cur_btns - prev_btns

        # 自摸/荣和按钮出现 → 和了机会
        if "tsumo" in appeared:
            events.append(VisionEvent("hu", {
                "seat": 0, "zimo": True, "tile": -1,
            }, 0.85))
        elif "ron" in appeared:
            events.append(VisionEvent("hu", {
                "seat": 0, "zimo": False, "tile": -1,
            }, 0.85))

        # 立直按钮出现
        if "riichi" in appeared:
            events.append(VisionEvent("liqi_candidate", {
                "seat": 0,
            }, 0.8))

        return events

    def _build_new_round_event(self, cur: "VisionFrame") -> VisionEvent:
        """构造新局事件"""
        data = {
            "chang": cur.round_info.round_wind if cur.round_info else 0,
            "ju": cur.round_info.round_number if cur.round_info else 0,
            "ben": cur.round_info.honba if cur.round_info else 0,
            "tiles": cur.hand_tiles,
            "dora_indicator": cur.dora_indicators[0] if cur.dora_indicators else -1,
            "scores": [25000, 25000, 25000, 25000],  # 默认, 后续可 OCR 分数
            "oya": cur.round_info.dealer if cur.round_info else 0,
            "tile_count": 70,
            "self_seat": 0,
        }
        return VisionEvent("new_round", data, 0.85)


# ═══════════════════════════════════════════════════════════════
#  StatefulDiffer (带迟滞)
# ═══════════════════════════════════════════════════════════════

class StatefulDiffer(StateDiffer):
    """
    带迟滞的状态差分器。

    事件必须跨 N 帧持续存在才会被发出, 过滤识别噪声 (一张牌短暂
    被误识别为另一张又恢复, 不应该产生"舍牌然后摸回来"的假事件)。

    参数:
      confirmation_frames: 事件需持续的帧数 (默认 2)
      max_pending_age: 待确认事件最大存活帧数 (默认 5)
    """

    def __init__(self, confirmation_frames: int = 2, max_pending_age: int = 5):
        super().__init__()
        self._confirmation_frames = confirmation_frames
        self._max_pending_age = max_pending_age
        self._pending: Dict[str, dict] = {}  # event_signature → {event, count, age}
        self._last_emitted: List[VisionEvent] = []  # 上一批已发出事件

    def diff(self, current: "VisionFrame") -> List[VisionEvent]:
        """带迟滞的帧差分"""
        # 获取原始候选事件
        candidates = super().diff(current)

        if not candidates:
            # 衰减所有 pending
            expired = []
            for sig, entry in self._pending.items():
                entry["age"] += 1
                if entry["age"] >= self._max_pending_age:
                    expired.append(sig)
            for sig in expired:
                del self._pending[sig]
            return []

        # 对每个候选事件, 检查是否与 pending 匹配
        confirmed = []
        for event in candidates:
            sig = self._event_signature(event)

            if sig in self._pending:
                # 已在 pending: 增加计数
                entry = self._pending[sig]
                entry["count"] += 1
                entry["age"] = 0

                if entry["count"] >= self._confirmation_frames:
                    confirmed.append(event)
                    del self._pending[sig]
            else:
                # 新事件: 加入 pending
                self._pending[sig] = {
                    "event": event,
                    "count": 1,
                    "age": 0,
                }

        # 清理过期 pending
        expired = []
        for sig, entry in self._pending.items():
            entry["age"] += 1
            if entry["age"] >= self._max_pending_age:
                expired.append(sig)
        for sig in expired:
            del self._pending[sig]

        # 去重: 不长连发同类型事件
        filtered = self._dedup(confirmed)

        self._last_emitted = filtered
        return filtered

    def reset(self):
        """重置 -- 清除 pending 事件"""
        super().reset()
        self._pending.clear()
        self._last_emitted.clear()

    @staticmethod
    def _event_signature(event: VisionEvent) -> str:
        """生成事件的唯一签名 (用于 pending 匹配)"""
        seat = event.data.get("seat", -1)
        tile = event.data.get("tile", -1)
        return f"{event.event_type}:{seat}:{tile}"

    def _dedup(self, events: List[VisionEvent]) -> List[VisionEvent]:
        """过滤重复的同类事件"""
        if not events:
            return events

        # 移除与上一批完全重复的事件
        last_sigs = {self._event_signature(e) for e in self._last_emitted}
        return [e for e in events if self._event_signature(e) not in last_sigs]
