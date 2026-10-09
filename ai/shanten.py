"""Japanese mahjong shanten: -1 complete, 0 tenpai, 1 one away.

Red fives retain their identity in the hand, but share counts with normal fives.
Pass meld_count when evaluating a concealed hand after calls.
"""
from functools import lru_cache
from typing import List

TILE_COUNT = 34
MAX_PER_TILE = 4
YAOCHU_IDS = {0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33}
RED_TO_NORMAL = {34: 4, 35: 13, 36: 22}


def normalize_tile(tile: int) -> int:
    return RED_TO_NORMAL.get(tile, tile)


def to_count_array(hand: List[int]) -> List[int]:
    counts = [0] * TILE_COUNT
    for tile in hand:
        tile = normalize_tile(tile)
        if 0 <= tile < TILE_COUNT:
            counts[tile] += 1
    return counts


class ShantenCalculator:
    @staticmethod
    def calculate(hand: List[int], meld_count: int = 0) -> int:
        if not hand:
            return -1  # Historical API; decision callers reject empty hands.
        counts = to_count_array(hand)
        normal = ShantenCalculator._normal_shanten(counts, len(hand), meld_count)
        if meld_count:
            return normal
        return min(normal, ShantenCalculator._chiitoi_shanten(counts),
                   ShantenCalculator._kokushi_shanten(counts))

    @staticmethod
    def _normal_shanten(counts, total_tiles=None, meld_count=0):
        target = 4 - meld_count

        @lru_cache(maxsize=None)
        def search(tiles, melds, partials, head):
            if melds > target:
                return 8
            base = 2 * target - 2 * melds - min(partials, target - melds) - head
            pos = next((i for i, n in enumerate(tiles) if n), None)
            if pos is None:
                return base
            best = 8

            def take(indices, dm=0, dp=0, dh=0):
                nonlocal best
                changed = list(tiles)
                for idx in indices:
                    changed[idx] -= 1
                best = min(best, search(tuple(changed), melds + dm, partials + dp, head + dh))

            take([pos])  # An isolated tile; do not discard an entire count.
            if tiles[pos] >= 3:
                take([pos] * 3, dm=1)
            if pos < 27 and pos % 9 <= 6 and tiles[pos + 1] and tiles[pos + 2]:
                take([pos, pos + 1, pos + 2], dm=1)
            if tiles[pos] >= 2:
                if not head:
                    take([pos] * 2, dh=1)
                take([pos] * 2, dp=1)
            if pos < 27:
                if pos % 9 <= 7 and tiles[pos + 1]:
                    take([pos, pos + 1], dp=1)
                if pos % 9 <= 6 and tiles[pos + 2]:
                    take([pos, pos + 2], dp=1)
            return best

        return search(tuple(counts), 0, 0, 0)

    @staticmethod
    def _chiitoi_shanten(counts):
        pairs = sum(c >= 2 for c in counts)
        unique = sum(c > 0 for c in counts)
        return 6 - pairs + max(0, 7 - unique)

    @staticmethod
    def _kokushi_shanten(counts):
        return 13 - sum(counts[i] > 0 for i in YAOCHU_IDS) - int(any(counts[i] >= 2 for i in YAOCHU_IDS))

    @staticmethod
    def get_waiting_tiles(counts: List[int], meld_count: int = 0) -> List[int]:
        # Work on a copy so errors/callers cannot leave counts mutated.
        if sum(counts) != 13 - meld_count * 3:
            return []
        hand = [tile for tile, count in enumerate(counts) for _ in range(count)]
        return [tile for tile in range(TILE_COUNT) if counts[tile] < MAX_PER_TILE
                and ShantenCalculator.calculate(hand + [tile], meld_count) == -1]
