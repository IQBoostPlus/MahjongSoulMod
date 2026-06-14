"""
AI 决策引擎

根据牌局状态(GameState)做出打牌/鸣牌/立直/和牌决策。

核心模块:
  - ShantenCalculator: 向听数计算 (3种: 标准/七对子/国士)
  - DoraCalculator:     宝牌价值评估
  - DefenseAnalysis:    防守分析 (现物/筋/壁/早巡安全度)
  - AIDecisionMaker:    主决策器
"""

from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from random import random, choice as rand_choice

from game_state.tracker import GameState, Player, MeldType
from ai.shanten import ShantenCalculator, to_count_array, TILE_COUNT, MAX_PER_TILE
from utils.log import Logger


class ActionType(Enum):
    DISCARD = "discard"
    RIICHI = "riichi"
    PON = "pon"
    CHI = "chi"
    KAN = "kan"
    RON = "ron"
    TSUMO = "tsumo"
    PASS = "pass"
    NONE = "none"


@dataclass
class GameAction:
    action: ActionType = ActionType.NONE
    tile: int = -1
    call_seat: int = -1


@dataclass
class CandidateDiscard:
    tile: int
    shanten: int
    waits: List[int] = field(default_factory=list)
    wait_count: int = 0
    good_shape_rate: float = 0.0
    dora_value: float = 0.0
    safety: float = 0.5
    score: float = 0.0


@dataclass
class StrategyParams:
    """策略参数 — 每局从 Config 基准值重新计算"""
    aggression: float = 0.5
    speed: float = 0.5
    risk_tolerance: float = 0.5


# ═══════════════════════════════════════════════════════════════
#  Dora 计算器
# ═══════════════════════════════════════════════════════════════

class DoraCalculator:
    """
    宝牌价值计算

    宝牌指示牌 → 宝牌: 数牌是下一张 (9→1), 字牌按顺序循环
      东→南→西→北→白→发→中→东
    """

    # 字牌宝牌映射: 指示牌 → 宝牌
    _HONOR_DORA_MAP = {
        27: 28,  # 东 → 南
        28: 29,  # 南 → 西
        29: 30,  # 西 → 北
        30: 31,  # 北 → 白
        31: 32,  # 白 → 发
        32: 33,  # 发 → 中
        33: 27,  # 中 → 东
    }

    @staticmethod
    def indicator_to_dora(indicator: int) -> int:
        """指示牌 → 宝牌 ID"""
        if indicator < 0 or indicator > 33:
            return -1
        if indicator >= 27:  # 字牌
            return DoraCalculator._HONOR_DORA_MAP.get(indicator, -1)
        # 数牌: 同花色下一张 (9→1)
        suit_start = (indicator // 9) * 9
        offset = (indicator % 9 + 1) % 9
        return suit_start + offset

    @staticmethod
    def get_dora_tiles(dora_indicators: List[int]) -> set:
        """多个指示牌 → 宝牌集合 (里宝也计入)"""
        dora_set = set()
        for ind in dora_indicators:
            d = DoraCalculator.indicator_to_dora(ind)
            if d >= 0:
                dora_set.add(d)
        return dora_set

    @staticmethod
    def count_dora_in_hand(hand: List[int], dora_indicators: List[int]) -> int:
        """手牌中有几张宝牌"""
        dora_set = DoraCalculator.get_dora_tiles(dora_indicators)
        return sum(1 for t in hand if t in dora_set)


# ═══════════════════════════════════════════════════════════════
#  防守分析器 (增强版)
# ═══════════════════════════════════════════════════════════════

class DefenseAnalysis:
    """防守分析 — 评估每张牌的放铳风险"""

    def __init__(self, params: StrategyParams):
        self.params = params

    def evaluate_risks(self, state: GameState) -> List[float]:
        """
        评估 34 种牌的放铳风险

        返回值: risks[tile_id] ∈ [0.0 (绝对安全) ~ 1.0 (极高风险)]
        """
        risks = [0.5] * TILE_COUNT
        self_seat = state.self_seat

        for pid in range(4):
            if pid == self_seat:
                continue

            player = state.players[pid]
            discards_list = player.discards
            discards_set = set(discards_list)
            my_discards = set(state.players[self_seat].discards)

            for tile_id in range(TILE_COUNT):
                # ── 层级1: 现物 = 绝对安全 ──
                if tile_id in discards_set:
                    risks[tile_id] = min(risks[tile_id], 0.0)
                    continue

                # ── 层级2: 自家现物 = 近乎安全 ──
                if tile_id in my_discards:
                    risks[tile_id] = min(risks[tile_id], 0.05)
                    continue

                # ── 层级3: 筋牌 ──
                if self._is_suji(tile_id, discards_list):
                    risks[tile_id] = min(risks[tile_id], 0.15)
                    continue

                # ── 层级4: 壁牌 (4张已见) ──
                if self._is_kabe(tile_id, state):
                    risks[tile_id] = min(risks[tile_id], 0.20)
                    continue

                # ── 层级5: 立直后安全牌 ──
                if player.is_liqi:
                    # 立直后，立直宣言牌之前的舍牌也是安全牌
                    # (立直宣言牌是最后一张舍牌)
                    if len(discards_list) >= 2:
                        pre_riichi = discards_list[:-1]
                        if tile_id in pre_riichi:
                            risks[tile_id] = min(risks[tile_id], 0.10)

                # ── 层级6: 字牌 (相对安全) ──
                if tile_id >= 27 and tile_id not in discards_set:
                    risks[tile_id] = min(risks[tile_id], 0.25)

                # ── 层级7: 早巡舍牌 — 偏安全 ──
                # 对手早巡切牌说明不需要该花色
                early_cut = self._is_early_discard_pattern(tile_id, discards_list)
                if early_cut:
                    risks[tile_id] = min(risks[tile_id], 0.30)

        return risks

    def get_safe_discards(self, state: GameState, hand: List[int]) -> List[int]:
        """按安全度排序手牌 (最安全在前)"""
        risks = self.evaluate_risks(state)
        return sorted(hand, key=lambda t: risks[t] if 0 <= t < TILE_COUNT else 1.0)

    def get_risks_for_hand(self, state: GameState, hand: List[int]) -> Dict[int, float]:
        """返回手牌中每张牌的风险值"""
        risks = self.evaluate_risks(state)
        return {t: risks[t] for t in hand if 0 <= t < TILE_COUNT}

    # ── 内部方法 ──

    def _is_suji(self, tile_id: int, opponent_discards: List[int]) -> bool:
        """
        筋牌判定: 对手舍过某张牌 → 其 ±3 的数牌相对安全
        因为对手不可能同时听两面搭子 (如舍5m→2m和8m是筋)
        """
        if tile_id >= 27:  # 字牌无筋
            return False

        discards_set = set(opponent_discards)
        suit_start = (tile_id // 9) * 9
        value = tile_id % 9 + 1  # 1-9

        # 舍5→2和8是筋, 舍2→5是筋(中), ...
        # 筋关系: 舍X→X±3是筋
        suji_indicator = value - 3
        if 1 <= suji_indicator <= 6:
            indicator_tile = suit_start + suji_indicator - 1
            if indicator_tile in discards_set:
                return True

        suji_indicator = value + 3
        if 4 <= suji_indicator <= 9:
            indicator_tile = suit_start + suji_indicator - 1
            if indicator_tile in discards_set:
                return True

        return False

    def _is_kabe(self, tile_id: int, state: GameState) -> bool:
        """
        壁牌判定: 某张牌4张已全部可见 → 该牌两侧的听牌不可能成立
        例如: 3m已见4张 → 对手不可能听 1-2m 或 4-5m 的两面
        (简化: 直接判断 tile_id 自己是否已全部出现)
        """
        if tile_id >= 34:  # 赤牌
            return False
        return state.get_remaining(tile_id) <= 0

    def _is_early_discard_pattern(self, tile_id: int,
                                   discards: List[int]) -> bool:
        """判断是否是对手早巡切出的花色 (巡目前6张)"""
        if tile_id >= 27:
            return False
        suit = tile_id // 9
        early = discards[:6]
        # 早巡切过同花色牌 → 该花色相对安全
        return any(t // 9 == suit for t in early)


# ═══════════════════════════════════════════════════════════════
#  向听数缓存 (性能优化)
# ═══════════════════════════════════════════════════════════════

# 简单的 LRU 手动缓存 (避免 functools 对 list 参数的 hash 问题)
_shanten_cache: Dict[int, int] = {}
_cache_hits = 0
_cache_misses = 0


def _hand_cache_key(hand: List[int]) -> int:
    """手牌 → 缓存键 (排序后取 hash)"""
    return hash(tuple(sorted(hand)))


def cached_shanten(hand: List[int]) -> int:
    """带缓存的向听数计算"""
    global _cache_hits, _cache_misses
    key = _hand_cache_key(hand)
    if key in _shanten_cache:
        _cache_hits += 1
        return _shanten_cache[key]
    _cache_misses += 1
    result = ShantenCalculator.calculate(hand)
    if len(_shanten_cache) > 50000:
        _shanten_cache.clear()
    _shanten_cache[key] = result
    return result


def clear_shanten_cache():
    global _cache_hits, _cache_misses
    _shanten_cache.clear()
    _cache_hits = 0
    _cache_misses = 0


# ═══════════════════════════════════════════════════════════════
#  AI 决策器 (主入口)
# ═══════════════════════════════════════════════════════════════

class AIDecisionMaker:
    """AI 决策器 — 主入口"""

    def __init__(self):
        self.params = StrategyParams()
        self._last_hand: List[int] = []
        self._dora_indicators: List[int] = []

    # ── 公共接口 ──

    def on_state_update(self, state: GameState):
        """游戏状态更新时调用"""
        self._update_strategy(state)
        self._last_hand = list(state.players[state.self_seat].hand)
        if state.dora_indicator >= 0:
            self._dora_indicators = [state.dora_indicator]
        # 新一局重置缓存
        if state.last_action == "new_round":
            clear_shanten_cache()

    def decide_discard(self, state: GameState) -> GameAction:
        """出牌决策 (自家摸牌后) → 返回 GameAction"""
        hand = state.players[state.self_seat].hand
        if not hand:
            return GameAction(ActionType.NONE)

        hand_counts = to_count_array(hand)
        shanten = cached_shanten(hand)

        Logger.info(f"[AI] Hand: {len(hand)} tiles, shanten={shanten}")

        # 听牌 → 考虑立直
        if shanten == -1:
            if self._should_riichi(state):
                discard = self._choose_riichi_discard(state, hand)
                Logger.info(f"[AI] Riichi → discard {discard}")
                return GameAction(ActionType.RIICHI, discard)
            else:
                # 默听 (damaten): 选和率最高的牌
                discard = self._choose_damaten_discard(state, hand)
                Logger.info(f"[AI] Damaten → discard {discard}")
                return GameAction(ActionType.DISCARD, discard)

        # 牌效率分析
        candidates = self._evaluate_discards(hand, hand_counts, state)

        if candidates:
            best = candidates[0]

            # 人机化: 小概率随机选择 (top3中)
            if random() < 0.02 and len(candidates) > 1:
                best = rand_choice(candidates[:min(3, len(candidates))])

            Logger.info(
                f"[AI] Discard: tile={best.tile} "
                f"(shanten={best.shanten}, safety={best.safety:.2f}, "
                f"dora={best.dora_value:.1f}, score={best.score:.1f})"
            )
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
        """和牌决策 — 默认总是和"""
        return GameAction(ActionType.TSUMO if is_tsumo else ActionType.RON)

    # ── 策略更新 ──

    def _update_strategy(self, state: GameState):
        """根据局况调整策略参数 — 从基准值重新计算，防止参数漂移"""
        # 基准值 (从配置读取)
        try:
            from config import cfg
            base_aggression = cfg.get("aggression", 3) / 5.0
            base_speed = cfg.get("speed", 3) / 5.0
            base_risk = cfg.get("risk_tolerance", 3) / 5.0
        except Exception:
            base_aggression = 0.5
            base_speed = 0.5
            base_risk = 0.5

        # 重置为基准
        self.params.aggression = base_aggression
        self.params.risk_tolerance = base_risk
        self.params.speed = base_speed

        # 根据局况调整
        scores = [p.score for p in state.players]
        self_seat = state.self_seat
        my_score = scores[self_seat] if self_seat < len(scores) else 25000

        max_score = max(scores) if scores else 25000
        min_score = min(scores) if scores else 25000
        score_range = max_score - min_score if max_score > min_score else 1

        lead_ratio = (my_score - min_score) / score_range

        # 领先时保守，落后时激进
        if lead_ratio > 0.7:
            self.params.aggression -= 0.2
            self.params.risk_tolerance -= 0.25
        elif lead_ratio < 0.3:
            self.params.aggression += 0.2
            self.params.risk_tolerance += 0.25

        # All-last: 南场且分差大时全力进攻
        is_all_last = (state.round_wind >= 1 and state.round_number >= 3)
        if is_all_last and my_score < max_score:
            diff = max_score - my_score
            if diff > 10000:
                self.params.aggression = 1.0
                self.params.risk_tolerance = 1.0

        # 裁剪
        self.params.aggression = max(0.0, min(1.0, self.params.aggression))
        self.params.risk_tolerance = max(0.0, min(1.0, self.params.risk_tolerance))
        self.params.speed = max(0.0, min(1.0, self.params.speed))

    # ── 立直判断 ──

    def _should_riichi(self, state: GameState) -> bool:
        """是否应该立直"""
        player = state.players[state.self_seat]

        # 前提条件
        if not player.is_menzen:
            return False
        if player.score < 1000:
            return False
        if self.params.aggression < 0.2:
            return False

        # 默听倾向 (高攻击性时立直)
        if self.params.aggression >= 0.6:
            return True

        # 有宝牌时倾向立直
        dora_count = DoraCalculator.count_dora_in_hand(
            player.hand, self._dora_indicators
        )
        if dora_count >= 2:
            return True

        return self.params.aggression >= 0.4

    def _choose_riichi_discard(self, state: GameState, hand: List[int]) -> int:
        """立直时选择安全牌切出"""
        defense = DefenseAnalysis(self.params)
        safe = defense.get_safe_discards(state, hand)
        return safe[0] if safe else hand[0]

    def _choose_damaten_discard(self, state: GameState, hand: List[int]) -> int:
        """默听时选择最优和率的牌"""
        defense = DefenseAnalysis(self.params)
        candidates = self._evaluate_discards(hand, to_count_array(hand), state)
        if candidates:
            # 默听: 偏向安全 + 高和率
            return candidates[0].tile
        safe = defense.get_safe_discards(state, hand)
        return safe[0] if safe else hand[0]

    # ── 牌效率分析 ──

    def _evaluate_discards(self, hand: List[int], counts: List[int],
                           state: GameState) -> List[CandidateDiscard]:
        """评估所有可能的切牌候选"""
        defense = DefenseAnalysis(self.params)
        risks = defense.evaluate_risks(state)
        dora_set = DoraCalculator.get_dora_tiles(self._dora_indicators)

        results = []
        seen = set()

        for tile in hand:
            if tile in seen:
                continue
            seen.add(tile)

            # 模拟移除一张
            new_hand = [t for t in hand]
            new_hand.remove(tile)
            new_counts = to_count_array(new_hand)

            shanten = cached_shanten(new_hand)
            waits = []
            wait_count = 0

            if shanten == -1:  # 听牌
                waits = ShantenCalculator.get_waiting_tiles(new_counts)
                wait_count = sum(
                    MAX_PER_TILE - counts[t]
                    for t in waits if 0 <= t < TILE_COUNT
                )

            # 各维度评分
            shanten_score = self._score_shanten(shanten)
            wait_bonus = min(wait_count, 40) * 1.0
            dora_val = 2.0 if tile in dora_set else 0.0
            safety = 1.0 - (risks[tile] if 0 <= tile < TILE_COUNT else 0.5)

            # 好形率: 保留顺子搭子 (简易估算)
            shape_rate = self._estimate_shape_rate(tile, new_counts)

            # 综合评分
            score = (
                shanten_score * 0.45 +
                wait_bonus * 0.15 +
                safety * 20.0 * (1.0 - self.params.risk_tolerance) +
                dora_val * 5.0 * self.params.aggression +
                shape_rate * 10.0
            )

            # 不要切宝牌 (dora) 的惩罚 — 在听牌前带宝牌有额外价值
            if tile in dora_set and shanten > -1:
                score -= 8.0 * (1.0 - self.params.aggression)

            results.append(CandidateDiscard(
                tile=tile, shanten=shanten,
                waits=waits, wait_count=wait_count,
                good_shape_rate=shape_rate,
                dora_value=dora_val,
                safety=safety,
                score=score
            ))

        results.sort(key=lambda r: -r.score)
        return results

    def _score_shanten(self, shanten: int) -> float:
        """向听数 → 基础分数"""
        return {
            -1: 100,   # 听牌
            0:  80,    # 1向听
            1:  40,    # 2向听
            2:  -10,   # 3向听
            3:  -40,   # 4向听
        }.get(shanten, -60)

    def _estimate_shape_rate(self, removed_tile: int,
                              new_counts: List[int]) -> float:
        """
        估算手牌好形率

        检查手牌中的两面搭子(ryanmen)数量 vs 愚形搭子(kanchan/penchan)数量
        """
        good = 0  # 两面
        bad = 0   # 坎张/边张

        for i in range(TILE_COUNT):
            cnt = new_counts[i]
            if cnt == 0:
                continue

            # 两面: 有 n 和 n+1 (非字牌且不跨花色)
            if i < 27 and i % 9 < 8 and new_counts[i + 1] > 0:
                if i % 9 < 7 and new_counts[i + 2] > 0:
                    good += 1
                else:
                    good += 1  # 至少是两面
            elif i < 27 and i % 9 < 7 and new_counts[i + 2] > 0:
                bad += 1  # 坎张
            elif cnt >= 2:
                good += 1  # 对子

        total = good + bad
        if total == 0:
            return 0.3
        return good / total

    # ── 鸣牌判断 ──

    def _should_pon(self, state: GameState, tile: int, hand: List[int]) -> bool:
        """判断是否碰"""
        if hand.count(tile) < 2:
            return False
        if self.params.aggression < 0.2:
            return False

        before = cached_shanten(hand)
        after_hand = [t for t in hand]
        for _ in range(2):
            if tile in after_hand:
                after_hand.remove(tile)
        after = cached_shanten(after_hand)

        # 碰后向听前进或保持听牌
        return after < before or (after == -1 and before == -1)

    def _should_chi(self, state: GameState, tile: int, hand: List[int]) -> bool:
        """判断是否吃"""
        if tile >= 27:  # 字牌不能吃
            return False
        if self.params.aggression < 0.2:
            return False

        before = cached_shanten(hand)

        suit_start = (tile // 9) * 9
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
                after = cached_shanten(after_hand)
                if after < before:
                    return True

        return False

    def _should_kan(self, state: GameState, tile: int, hand: List[int]) -> bool:
        """判断是否杠"""
        if hand.count(tile) < 4:
            return False

        # 杠会减少手牌灵活性，仅在安全时杠
        if self.params.risk_tolerance < 0.3:
            return False

        # 听牌时不杠 (除非是暗杠)
        before = cached_shanten(hand)
        if before == -1:
            return False

        return True
