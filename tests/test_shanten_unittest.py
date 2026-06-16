"""
向听数计算器测试 — unittest.TestCase 格式 (原 test_shanten.py)
12 tests total
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai.shanten import ShantenCalculator, TILE_COUNT


def make_hand(*tiles: str) -> list:
    """字符串表示 → 手牌列表 (复用原 test_shanten.py / test_regression.py)"""
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


class TestShantenCalculator(unittest.TestCase):
    """向听数计算 — 12 项测试"""

    def test_nine_gate_13_tiles(self):
        """九莲宝灯 13枚 听牌"""
        hand = make_hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","9m","9m","9m")
        self.assertEqual(ShantenCalculator.calculate(hand), 0)

    def test_nine_gate_14_tiles(self):
        """九莲宝灯 14枚 和了"""
        hand = make_hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","8m","9m","9m","9m")
        self.assertEqual(ShantenCalculator.calculate(hand), -1)

    def test_kokushi_13_tiles(self):
        """国士无双 13面听"""
        hand = make_hand("1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z","7z")
        self.assertEqual(ShantenCalculator.calculate(hand), 0)

    def test_kokushi_completed(self):
        """国士无双 完成"""
        hand = make_hand("1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z","7z","1m")
        self.assertEqual(ShantenCalculator.calculate(hand), -1)

    def test_kokushi_1_shanten(self):
        """国士无双 1向听"""
        hand = make_hand("1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z")
        self.assertEqual(ShantenCalculator.calculate(hand), 1)

    def test_chiitoi_13_tiles(self):
        """七对子 13枚 听牌"""
        hand = make_hand("1m","1m","3p","3p","5s","5s","2z","2z","4z","4z","6z","6z","8p")
        self.assertEqual(ShantenCalculator.calculate(hand), 0)

    def test_chiitoi_14_tiles(self):
        """七对子 14枚 听牌"""
        hand = make_hand("1m","1m","3p","3p","5s","5s","2z","2z","4z","4z","6m","6m","8p","9p")
        self.assertEqual(ShantenCalculator.calculate(hand), 0)

    def test_ryanmen_tenpai(self):
        """两面听牌"""
        hand = make_hand("2m","3m","5p","6p","7p","9s","9s","9s","1z","1z","1z","2z","2z")
        self.assertEqual(ShantenCalculator.calculate(hand), 0)

    def test_complete_hand(self):
        """和了形"""
        hand = make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","1p","1p","2p","2p")
        self.assertEqual(ShantenCalculator.calculate(hand), -1)

    def test_kanchan_1_shanten(self):
        """坎张 1向听"""
        hand = make_hand("1m","3m","5p","6p","7p","9s","9s","9s","2z","2z","4z","4z","6p","7p")
        self.assertEqual(ShantenCalculator.calculate(hand), 1)

    def test_all_honors(self):
        """字牌乱手"""
        hand = make_hand("1z","1z","2z","2z","3z","3z","4z","5z","5z","6z","6z","7z","7z","7z")
        s = ShantenCalculator.calculate(hand)
        self.assertLessEqual(s, 2)

    def test_random_high_shanten(self):
        """散乱高向听"""
        hand = make_hand("1m","3m","5m","7m","9m","2p","4p","6p","8p","1s","3s","5s","7s","9s")
        s = ShantenCalculator.calculate(hand)
        self.assertGreaterEqual(s, 3)


if __name__ == "__main__":
    unittest.main()
