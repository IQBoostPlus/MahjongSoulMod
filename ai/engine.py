"""
AI 决策引擎

根据牌局状态(GameState)做出打牌/鸣牌/立直/和牌决策。
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from random import random, choice as rand_choice

from game_state import GameState, Player
from ai.shanten import ShantenCalculator, to_count_array, TILE_COUNT, MAX_PER_TILE
from utils.log import Logger


class ActionType(Enum):
    DISCARD = "discard"       # 出牌
    RIICHI = "riichi"        # 立直
    PON = "pon"              # 碰
    CHI = "chi"              # 吃
    KAN = "kan"              # 杠
    RON = "ron"              # 荣和
    TSUMO = "tsumo"          # 自摸
    PASS = "pass"            # 跳过
    NONE = "none"            # 无动作


@dataclass
class GameAction:
    action: ActionType = ActionType.NONE
    tile: int = -1         # 关联牌ID
    call_seat: int = -1     # 鸣牌来源


@dataclass
class CandidateDiscard:
    tile: int               # 牌ID
    shanten: int            # 切后向听数
    waits: List[int] = field(default_factory=list)
    wait_count: int = 0
    good_shape_rate: float = 0.0
    score: float = 0.0


@dataclass
class StrategyParams:
    aggression: float = 0.5       # 0.0-1.0 攻击性
    speed: float = 0.5            # 0.0-1.0 速度偏好
    risk_tolerance: float = 0.5   # 0.0-1.0 风险容忍度


class DefenseAnalysis:
    """防守分析器"""

    def __init__(self, params: StrategyParams):
        self.params = params

    def evaluate_risks(self, state: GameState) -> List[float]:
        """评估34种牌的放铳风险 (0.0=安全 ~ 1.0=危险)"""
        risks = [0.5] * TILE_COUNT
        self_seat = state.self_seat

        for pid in range(4):
            if pid == self_seat:
                continue

            player = state.players[pid]
            discards_set = set(player.discards)
            my_discards = set(state.players[self_seat].discards)

            for tile_id in range(TILE_COUNT):
                # 现物 = 绝对安全
                if tile_id in discards_set:
                    risks[tile_id] = min(risks[tile_id], 0.0)

                # 自家切过 = 接近安全
                if tile_id in my_discards:
                    risks[tile_id] = min(risks[tile_id], 0.05)

                # 筋牌
                if self._is_suji(tile_id, list(discards_set)):
                    risks[tile_id] = min(risks[tile_id], 0.15)

        return risks

    def get_safe_discards(self, state: GameState, hand: List[int]) -> List[int]:
        """按安全度排序手牌"""
        risks = self.evaluate_risks(state)
        return sorted(hand, key=lambda t: risks[t] if 0 <= t < TILE_COUNT else 1.0)

    def _is_suji(self, tile_id: int, opponent_discards: List[int]) -> bool:
        if tile_id >= 27:
            return False
        v = tile_id % 9 + 1
        for d in opponent_discards:
            if d >= 27:
                continue
            dv = d % 9 + 1
            if abs(v - dv) == 3:
                return True
        return False


class AIDecisionMaker:
    """AI 决策器 — 主入口"""

    def __init__(self):
        self.params = StrategyParams()
        self._last_hand: List[int] = []

    def on_state_update(self, state: GameState):
        """游戏状态更新时检查是否需要决策"""
        self._update_strategy(state)
        self._last_hand = list(state.players[state.self_seat].hand)

    def decide_discard(self, state: GameState) -> GameAction:
        """
        出牌决策 (自家摸牌后)
        返回要执行的 GameAction
        """
        hand = state.players[state.self_seat].hand
        if not hand:
            return GameAction(ActionType.NONE)

        hand_counts = to_count_array(hand)
        shanten = ShantenCalculator.calculate(hand)

        Logger.info(f"[AI] Hand: {len(hand)} tiles, shanten={shanten}")

        # 听牌 → 考虑立直
        if shanten == -1:
            if self._should_riichi(state):
                # 立直出牌: 选安全度最高的
                discard = self._choose_riichi_discard(state, hand)
                Logger.info(f"[AI] Riichi, discard: {discard}")
                return GameAction(ActionType.RIICHI, discard)

        # 牌效率分析
        candidates = self._evaluate_discards(hand, hand_counts, state)

        if candidates:
            best = candidates[0]

            # 人机化: 小概率随机选
            if random() < 0.02 and len(candidates) > 1:
                best = rand_choice(candidates[:3])

            Logger.info(f"[AI] Discard: tile={best.tile} "
                        f"(shanten={best.shanten}, score={best.score:.1f})")
            return GameAction(ActionType.DISCARD, best.tile)

        # 兜底: 切第一张
        Logger.info(f"[AI] Fallback discard: {hand[0]}")
        return GameAction(ActionType.DISCARD, hand[0])

    def decide_call(self, state: GameState, incoming_tile: int,
                    call_type: str) -> GameAction:
        """鸣牌决策"""
        hand = state.players[state.self_seat].hand

        if call_type == "pon":
            if self._should_pon(state, incoming_tile, hand):
                return GameAction(ActionType.PON, incoming_tile)

        elif call_type == "chi":
            if self._should_chi(state, incoming_tile, hand):
                return GameAction(ActionType.CHI, incoming_tile)

        elif call_type == "kan":
            if self._should_kan(state, incoming_tile, hand):
                return GameAction(ActionType.KAN, incoming_tile)

        return GameAction(ActionType.PASS)

    def decide_agari(self, state: GameState, is_tsumo: bool) -> GameAction:
        """和牌决策"""
        # 默认总是和牌
        return GameAction(ActionType.TSUMO if is_tsumo else ActionType.RON)

    # ── 内部方法 ──

    def _update_strategy(self, state: GameState):
        """根据局况调整策略参数"""
        scores = [p.score for p in state.players]
        self_seat = state.self_seat
        my_score = scores[self_seat]

        max_score = max(scores) if scores else 25000
        min_score = min(scores) if scores else 25000

        # 领先时保守
        if my_score == max_score and max_score > min_score:
            self.params.aggression -= 0.15
            self.params.risk_tolerance -= 0.15

        # 落后时激进
        if my_score == min_score and min_score < max_score:
            self.params.aggression += 0.15
            self.params.risk_tolerance += 0.15

        # 最终局
        if state.round_wind == 1:  # 南场
            diff = max_score - my_score
            if diff > 10000 and my_score < max_score:
                self.params.aggression = 1.0
                self.params.risk_tolerance = 1.0

        # 裁剪
        self.params.aggression = max(0.0, min(1.0, self.params.aggression))
        self.params.risk_tolerance = max(0.0, min(1.0, self.params.risk_tolerance))
        self.params.speed = max(0.0, min(1.0, self.params.speed))

    def _should_riichi(self, state: GameState) -> bool:
        """检查是否应立直"""
        if self.params.aggression < 0.3:
            return False
        if state.players[state.self_seat].score < 1000:
            return False
        return True

    def _evaluate_discards(self, hand: List[int], counts: List[int],
                           state: GameState) -> List[CandidateDiscard]:
        """评估所有可能的切牌"""
        results = []

        # 按唯一牌ID去重
        seen = set()
        for tile in hand:
            if tile in seen:
                continue
            seen.add(tile)

            # 移除一张
            new_hand = [t for t in hand]
            if tile in new_hand:
                new_hand.remove(tile)
            new_counts = to_count_array(new_hand)

            shanten = ShantenCalculator.calculate(new_hand)
            waits = []
            wait_count = 0

            if shanten == -1:
                waits = ShantenCalculator.get_waiting_tiles(new_counts)
                wait_count = sum(
                    MAX_PER_TILE - counts[t]
                    for t in waits
                    if 0 <= t < TILE_COUNT
                )

            # 评分
            score = self._score_discard(shanten, wait_count, 0.3)
            results.append(CandidateDiscard(
                tile=tile, shanten=shanten,
                waits=waits, wait_count=wait_count,
                good_shape_rate=0.3, score=score
            ))

        results.sort(key=lambda r: -r.score)
        return results

    def _score_discard(self, shanten: int, wait_count: int,
                       shape_rate: float) -> float:
        """评分"""
        shanten_score = {
            -1: 100,   # 听牌
            0: 80,      # 1向听
            1: 40,      # 2向听
            2: -10,     # 3向听
        }.get(shanten, -50)

        wait_bonus = min(wait_count, 40) * 1.0
        shape_bonus = shape_rate * 20

        return shanten_score + wait_bonus + shape_bonus

    def _choose_riichi_discard(self, state: GameState,
                               hand: List[int]) -> int:
        """立直时选择安全牌"""
        defense = DefenseAnalysis(self.params)
        safe = defense.get_safe_discards(state, hand)
        return safe[0] if safe else hand[0]

    def _should_pon(self, state: GameState, tile: int, hand: List[int]) -> bool:
        """判断是否碰"""
        if hand.count(tile) < 2:
            return False
        if self.params.aggression < 0.3:
            return False

        # 碰后向听前进？
        before = ShantenCalculator.calculate(hand)
        after_hand = [t for t in hand]
        for _ in range(2):
            if tile in after_hand:
                after_hand.remove(tile)
        after = ShantenCalculator.calculate(after_hand)

        return after < before

    def _should_chi(self, state: GameState, tile: int, hand: List[int]) -> bool:
        """判断是否吃"""
        if tile >= 27:  # 字牌不能吃
            return False
        if self.params.aggression < 0.3:
            return False

        before = ShantenCalculator.calculate(hand)

        # 检查是否能组成顺子
        suit_start = (tile // 9) * 9
        offset = tile % 9

        patterns = [[-2, -1], [-1, +1], [+1, +2]]
        for p in patterns:
            a = tile + p[0]
            b = tile + p[1]
            if a < suit_start or b > suit_start + 8:
                continue
            if a < 0 or b > 26:
                continue
            if hand.count(a) > 0 and hand.count(b) > 0:
                after_hand = [t for t in hand]
                if a in after_hand:
                    after_hand.remove(a)
                if b in after_hand:
                    after_hand.remove(b)
                after = ShantenCalculator.calculate(after_hand)
                if after < before:
                    return True

        return False

    def _should_kan(self, state: GameState, tile: int, hand: List[int]) -> bool:
        """判断是否杠"""
        if hand.count(tile) < 4:
            return False
        return True
