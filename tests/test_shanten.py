"""
向听数计算器测试 — 移植自 C# xUnit 测试 (12 tests)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai.shanten import ShantenCalculator, TILE_COUNT


def make_hand(*tiles: str) -> list:
    """字符串表示 → 手牌列表
    格式: "1m", "5p", "9s", "1z" (东南西北白发中)
    """
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


# ── 测试用例 ──

def test_nine_gate_13_tiles():
    """九莲宝灯 13枚 听牌"""
    hand = make_hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","9m","9m","9m")
    assert ShantenCalculator.calculate(hand) == 0, "九莲宝灯 13枚应为 0向听(听牌)"


def test_nine_gate_14_tiles():
    """九莲宝灯 14枚 和了"""
    hand = make_hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","8m","9m","9m","9m")
    assert ShantenCalculator.calculate(hand) == -1, "九莲宝灯 14枚应为 -1(和了)"


def test_kokushi_13_tiles():
    """国士无双 13面听"""
    hand = make_hand("1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z","7z")
    assert ShantenCalculator.calculate(hand) == 0, "国士无双 13枚应为 0向听"


def test_kokushi_completed():
    """国士无双 完成"""
    hand = make_hand("1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z","7z","1m")
    assert ShantenCalculator.calculate(hand) == -1, "国士无双 14枚应为 -1"


def test_kokushi_1_shanten():
    """国士无双 1向听"""
    hand = make_hand("1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z")
    assert ShantenCalculator.calculate(hand) == 1


def test_chiitoi_13_tiles():
    """七对子 13枚 听牌"""
    hand = make_hand("1m","1m","3p","3p","5s","5s","2z","2z","4z","4z","6z","6z","8p")
    assert ShantenCalculator.calculate(hand) == 0


def test_chiitoi_14_tiles():
    """七对子 14枚 听牌"""
    hand = make_hand("1m","1m","3p","3p","5s","5s","2z","2z","4z","4z","6m","6m","8p","9p")
    assert ShantenCalculator.calculate(hand) == 0


def test_ryanmen_tenpai():
    """两面听牌"""
    hand = make_hand("2m","3m","5p","6p","7p","9s","9s","9s","1z","1z","1z","2z","2z")
    assert ShantenCalculator.calculate(hand) == 0


def test_complete_hand():
    """和了形"""
    hand = make_hand("1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","1p","1p","2p","2p")
    assert ShantenCalculator.calculate(hand) == -1


def test_kanchan_1_shanten():
    """坎张 1向听"""
    hand = make_hand("1m","3m","5p","6p","7p","9s","9s","9s","2z","2z","4z","4z","6p","7p")
    assert ShantenCalculator.calculate(hand) == 1


def test_all_honors():
    """字牌乱手"""
    hand = make_hand("1z","1z","2z","2z","3z","3z","4z","5z","5z","6z","6z","7z","7z","7z")
    s = ShantenCalculator.calculate(hand)
    assert s <= 2


def test_random_high_shanten():
    """散乱高向听"""
    hand = make_hand("1m","3m","5m","7m","9m","2p","4p","6p","8p","1s","3s","5s","7s","9s")
    s = ShantenCalculator.calculate(hand)
    assert s >= 3


if __name__ == "__main__":
    tests = [
        ("九莲宝灯 13枚听牌", test_nine_gate_13_tiles),
        ("九莲宝灯 14枚和了", test_nine_gate_14_tiles),
        ("国士无双 13面听", test_kokushi_13_tiles),
        ("国士无双 完成形", test_kokushi_completed),
        ("国士无双 1向听", test_kokushi_1_shanten),
        ("七对子 13枚听牌", test_chiitoi_13_tiles),
        ("七对子 14枚听牌", test_chiitoi_14_tiles),
        ("两面听牌", test_ryanmen_tenpai),
        ("和了形", test_complete_hand),
        ("坎张 1向听", test_kanchan_1_shanten),
        ("字牌乱手", test_all_honors),
        ("散乱高向听", test_random_high_shanten),
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

    print(f"\n结果: {passed}/{passed + failed} 通过")
    sys.exit(0 if failed == 0 else 1)
