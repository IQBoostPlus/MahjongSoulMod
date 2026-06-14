using System;
using System.Collections.Generic;
using System.Linq;
using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.AI;

/// <summary>
/// Layer 3: 鸣牌决策器
/// </summary>
public class CallDecision
{
    private readonly StrategyParams _params;

    public CallDecision(StrategyParams strategyParams) => _params = strategyParams;

    /// <summary>
    /// 判断是否碰
    /// </summary>
    public bool ShouldPon(Tile incoming, Tile[] hand, GameState state)
    {
        if (hand.Count(t => t.Id == incoming.Id) < 2) return false;
        if (_params.Aggression < 0.3) return false;

        // 碰后手牌: 原手牌 - 2张(碰出) = 12张(14枚时) 或 11张(13枚时)
        int beforeShanten = ShantenCalculator.Calculate(hand);
        var afterHand = RemoveTiles(hand, incoming, 2);
        int afterShanten = ShantenCalculator.Calculate(afterHand);

        return afterShanten < beforeShanten;
    }

    /// <summary>
    /// 判断是否吃
    /// </summary>
    public bool ShouldChi(Tile incoming, Tile[] hand, GameState state)
    {
        if (incoming.IsHonor) return false;
        if (_params.Aggression < 0.3) return false;

        int beforeShanten = ShantenCalculator.Calculate(hand);
        var combos = GetChiCombinations(incoming, hand);

        foreach (var combo in combos)
        {
            // 吃后: 移除组合中的两张手牌，加进来牌
            var afterHand = hand.Where(t => t.Id != combo[0].Id && t.Id != combo[1].Id).ToList();
            int afterShanten = ShantenCalculator.Calculate(afterHand.ToArray());

            if (afterShanten < beforeShanten)
                return true;
        }

        return false;
    }

    private static Tile[] RemoveTiles(Tile[] hand, Tile target, int count)
    {
        var list = new List<Tile>(hand);
        int removed = 0;
        list.RemoveAll(t => {
            if (removed < count && t.Id == target.Id) { removed++; return true; }
            return false;
        });
        return list.ToArray();
    }

    private static List<Tile[]> GetChiCombinations(Tile incoming, Tile[] hand)
    {
        var result = new List<Tile[]>();
        int id = incoming.Id;
        if (id >= 27) return result; // 字牌不能吃

        int suitStart = (id / 9) * 9;
        int offset = id % 9;

        // 三种吃牌组合: (n-2,n-1), (n-1,n+1), (n+1,n+2)
        int[][] patterns = [[-2, -1], [-1, +1], [+1, +2]];

        foreach (var p in patterns)
        {
            int a = id + p[0];
            int b = id + p[1];
            if (a < suitStart || b > suitStart + 8) continue;
            if (a < 0 || b > 26) continue;
            if (hand.Count(t => t.Id == a) > 0 && hand.Count(t => t.Id == b) > 0)
                result.Add([new Tile(a), new Tile(b)]);
        }

        return result;
    }
}
