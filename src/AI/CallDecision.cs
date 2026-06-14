using System;
using System.Collections.Generic;
using System.Linq;
using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.AI;

/// <summary>
/// Layer 3: 鸣牌决策器
/// 判断是否应当吃/碰/杠
/// </summary>
public class CallDecision
{
    private readonly StrategyParams _params;

    public CallDecision(StrategyParams strategyParams)
    {
        _params = strategyParams;
    }

    /// <summary>
    /// 判断是否碰
    /// </summary>
    public bool ShouldPon(Tile tile, Tile[] hand, GameState state)
    {
        if (!CanPon(tile, hand)) return false;

        var after = RemoveTiles(hand, tile, 2);
        int beforeShanten = ShantenCalculator.Calculate(hand);
        int afterShanten = ShantenCalculator.Calculate([.. after, tile, tile, tile]);

        // 碰后向听数必须前进
        if (afterShanten >= beforeShanten && beforeShanten != 0) return false;

        // 攻击性
        if (_params.Aggression < 0.3) return false;

        return true;
    }

    /// <summary>
    /// 判断是否吃
    /// </summary>
    public bool ShouldChi(Tile tile, Tile[] hand, GameState state)
    {
        if (!CanChi(tile, hand, out _)) return false;

        int beforeShanten = ShantenCalculator.Calculate(hand);

        var combos = GetChiCombinations(tile, hand);
        foreach (var combo in combos)
        {
            var afterHand = hand.Where(t => t.Id != combo[0].Id || t.Id != combo[1].Id).ToArray();
            // 简化判断
            int afterShanten = beforeShanten - 1; // 假设吃后进1向听

            if (afterShanten < beforeShanten)
                return true;
        }

        return false;
    }

    /// <summary>
    /// 判断是否杠
    /// </summary>
    public (bool shouldKan, bool isAnKan) ShouldKan(int[] counts, GameState state)
    {
        // 暗杠条件: 有4枚相同牌
        for (int i = 0; i < Tile.TileTypeCount; i++)
        {
            if (counts[i] == 4)
            {
                // 暗杠会减少手牌，可能破坏听牌
                return (true, true);
            }
        }

        return (false, false);
    }

    private static bool CanPon(Tile tile, Tile[] hand)
    {
        return hand.Count(t => t.Id == tile.Id) >= 2;
    }

    private static bool CanChi(Tile tile, Tile[] hand, out List<Tile[]> combinations)
    {
        combinations = [];
        if (tile.IsHonor) return false;

        combinations = GetChiCombinations(tile, hand);
        return combinations.Count > 0;
    }

    private static List<Tile[]> GetChiCombinations(Tile tile, Tile[] hand)
    {
        var result = new List<Tile[]>();

        int id = tile.Id;
        int suit = id / 9;
        int baseInSuit = id % 9;

        // 可能的顺子组合: (n-2,n-1), (n-1,n+1), (n+1,n+2)
        int[][] offsets = [
            [-2, -1],
            [-1, +1],
            [+1, +2],
        ];

        foreach (var off in offsets)
        {
            int a = suit * 9 + baseInSuit + off[0];
            int b = suit * 9 + baseInSuit + off[1];

            if (a < suit * 9 || b > suit * 9 + 8) continue;
            if (hand.Count(t => t.Id == a) > 0 && hand.Count(t => t.Id == b) > 0)
                result.Add([new Tile(a), new Tile(b)]);
        }

        return result;
    }

    private static Tile[] RemoveTiles(Tile[] hand, Tile exclude, int count)
    {
        var list = new List<Tile>(hand);
        int removed = 0;
        list.RemoveAll(t => {
            if (removed < count && t.Id == exclude.Id) { removed++; return true; }
            return false;
        });
        return list.ToArray();
    }
}
