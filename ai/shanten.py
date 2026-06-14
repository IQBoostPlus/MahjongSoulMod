"""
向听数计算器

支持标准手、七对子、国士无双三种向听数计算。
移植自 C# 版 ShantenCalculator (已通过 12 项测试)
"""

from typing import List, Tuple

# 34种牌的常量
TILE_COUNT = 34
MAX_PER_TILE = 4

# 幺九牌 ID
YAOCHU_IDS = {0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33}


def to_count_array(hand: List[int]) -> List[int]:
    """手牌列表 → 34维计数数组"""
    counts = [0] * TILE_COUNT
    for t in hand:
        if 0 <= t < TILE_COUNT:
            counts[t] += 1
    return counts


class ShantenCalculator:
    """向听数计算器"""

    @staticmethod
    def calculate(hand: List[int]) -> int:
        """
        计算最少向听数

        Returns:
            -1 = 和牌 (0向听)
            0 = 听牌 (1向听)
            1 = 2向听
            ...
        """
        if len(hand) == 0:
            return -1

        counts = to_count_array(hand)
        total = len(hand)

        normal = ShantenCalculator._normal_shanten(counts, total)
        chiitoi = ShantenCalculator._chiitoi_shanten(counts)
        kokushi = ShantenCalculator._kokushi_shanten(counts)

        return min(normal, chiitoi, kokushi)

    @staticmethod
    def _normal_shanten(counts: List[int], total_tiles: int) -> int:
        """标准手向听数"""
        needed_melds = total_tiles // 3
        min_shanten = 999

        # 枚举雀头
        for i in range(TILE_COUNT):
            if counts[i] < 2:
                continue

            counts[i] -= 2
            shanten = ShantenCalculator._calc_mentsu_shanten(
                counts, needed_melds, 0, 0
            )
            counts[i] += 2

            if shanten < min_shanten:
                min_shanten = shanten

        # 无雀头情况
        if min_shanten == 999:
            min_shanten = ShantenCalculator._calc_mentsu_shanten(
                counts, needed_melds, 0, 0
            ) + 1

        return min_shanten

    @staticmethod
    def _calc_mentsu_shanten(
        counts: List[int], target_melds: int, melds: int, partials: int
    ) -> int:
        """递归计算面子拆解向听数"""
        if melds > target_melds:
            return 999
        if partials > target_melds - melds:
            partials = target_melds - melds

        # 全部拆解完毕
        if all(c == 0 for c in counts):
            shanten = 2 * (target_melds - melds) - partials - 1
            return -1 if shanten < -1 else shanten

        # 找到第一个非零位置
        pos = 0
        while pos < TILE_COUNT and counts[pos] == 0:
            pos += 1

        min_shanten = 999
        cnt = counts[pos]

        # 1) 取顺子 (非字牌)
        if pos < 27 and pos % 9 < 7 and \
           counts[pos] > 0 and counts[pos + 1] > 0 and counts[pos + 2] > 0:
            counts[pos] -= 1
            counts[pos + 1] -= 1
            counts[pos + 2] -= 1
            s = ShantenCalculator._calc_mentsu_shanten(
                counts, target_melds, melds + 1, partials
            )
            counts[pos] += 1
            counts[pos + 1] += 1
            counts[pos + 2] += 1
            if s < min_shanten:
                min_shanten = s

        # 2) 取刻子
        if cnt >= 3:
            counts[pos] -= 3
            s = ShantenCalculator._calc_mentsu_shanten(
                counts, target_melds, melds + 1, partials
            )
            counts[pos] += 3
            if s < min_shanten:
                min_shanten = s

        # 3) 取对子 (搭子)
        if cnt >= 2:
            counts[pos] -= 2
            s = ShantenCalculator._calc_mentsu_shanten(
                counts, target_melds, melds, partials + 1
            )
            counts[pos] += 2
            if s < min_shanten:
                min_shanten = s

        # 两面/坎张
        if pos < 27 and pos % 9 < 8 and \
           counts[pos] > 0 and counts[pos + 1] > 0:
            counts[pos] -= 1
            counts[pos + 1] -= 1
            s = ShantenCalculator._calc_mentsu_shanten(
                counts, target_melds, melds, partials + 1
            )
            counts[pos] += 1
            counts[pos + 1] += 1
            if s < min_shanten:
                min_shanten = s

        if pos < 27 and pos % 9 < 7 and \
           counts[pos] > 0 and counts[pos + 2] > 0:
            counts[pos] -= 1
            counts[pos + 2] -= 1
            s = ShantenCalculator._calc_mentsu_shanten(
                counts, target_melds, melds, partials + 1
            )
            counts[pos] += 1
            counts[pos + 2] += 1
            if s < min_shanten:
                min_shanten = s

        # 4) 孤张 — 跳过
        counts[pos] = 0
        s = ShantenCalculator._calc_mentsu_shanten(
            counts, target_melds, melds, partials
        )
        counts[pos] = cnt
        if s < min_shanten:
            min_shanten = s

        return min_shanten

    @staticmethod
    def _chiitoi_shanten(counts: List[int]) -> int:
        """七对子向听数"""
        pairs = 0
        singles = 0
        for c in counts:
            pairs += c // 2
            singles += c % 2

        if pairs >= 7:
            return -1
        if pairs == 6:
            return 0
        return 6 - pairs

    @staticmethod
    def _kokushi_shanten(counts: List[int]) -> int:
        """国士无双向听数"""
        unique = sum(1 for i in YAOCHU_IDS if counts[i] >= 1)
        has_pair = any(counts[i] >= 2 for i in YAOCHU_IDS)

        shanten = 13 - unique
        if has_pair:
            shanten -= 1
        return shanten

    @staticmethod
    def get_waiting_tiles(counts: List[int]) -> List[int]:
        """获取听牌列表"""
        waits = []
        for i in range(TILE_COUNT):
            if counts[i] >= MAX_PER_TILE:
                continue

            counts[i] += 1
            total = sum(counts)

            if (ShantenCalculator._normal_shanten(counts, total) == -1 or
                ShantenCalculator._chiitoi_shanten(counts) == -1 or
                ShantenCalculator._kokushi_shanten(counts) == -1):
                waits.append(i)

            counts[i] -= 1

        return waits
