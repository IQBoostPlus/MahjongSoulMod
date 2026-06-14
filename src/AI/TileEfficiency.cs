using System;
using System.Collections.Generic;
using System.Linq;
using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.AI;

/// <summary>
/// Layer 3: 打牌效率分析器
/// 枚举所有候选打牌，计算牌效评分
/// </summary>
public class TileEfficiency
{
    private readonly StrategyParams _params;

    public TileEfficiency(StrategyParams strategyParams)
    {
        _params = strategyParams;
    }

    /// <summary>
    /// 计算每张候选牌的评分，按降序排列
    /// </summary>
    public List<CandidateDiscard> Evaluate(Tile[] hand, int[] tileCount)
    {
        var results = new List<CandidateDiscard>();
        var seen = new HashSet<int>();

        foreach (var tile in hand)
        {
            if (!seen.Add(tile.Id)) continue;

            // 模拟切掉这张牌
            var remaining = RemoveTile(hand, tile);
            int[] counts = ShantenCalculator.ToCountArray(remaining);

            int shanten = ShantenCalculator.Calculate(remaining);
            int[] waits = shanten == -1 ? GetWaits(counts, tileCount) : [];
            int waitCount = waits.Sum(id => Tile.MaxCountPerTile - tileCount[id]);

            // 良形率: 两面听的比例
            double goodShapeRate = shanten == -1
                ? CalcGoodShapeRate(waits, tileCount)
                : CalcGoodShapeRatePossible(counts, tileCount);

            // 评分 = 综合牌效
            double score = ScoreDiscard(shanten, waitCount, goodShapeRate);

            results.Add(new CandidateDiscard
            {
                Tile = tile,
                Shanten = shanten,
                Waits = waits,
                WaitCount = waitCount,
                GoodShapeRate = goodShapeRate,
                Score = score
            });
        }

        return results.OrderByDescending(r => r.Score).ToList();
    }

    private double ScoreDiscard(int shanten, int waitCount, double goodShapeRate)
    {
        // 向听数惩罚: 越远的向听负数越大
        double shantenPenalty = shanten switch
        {
            -1 => 100,      // 听牌
            0 => 80,        // 1向听
            1 => 40,        // 2向听
            2 => -10,       // 3向听
            _ => -50        // 4向听+
        };

        // 进张奖励
        double waitBonus = Math.Min(waitCount, 40) * 1.0;

        // 良形奖励
        double shapeBonus = goodShapeRate * 20;

        return shantenPenalty + waitBonus + shapeBonus;
    }

    private static Tile[] RemoveTile(Tile[] hand, Tile tile)
    {
        bool removed = false;
        return hand.Where(t => {
            if (!removed && t.Id == tile.Id && t.IsRed == tile.IsRed)
            {
                removed = true;
                return false;
            }
            return true;
        }).ToArray();
    }

    private static int[] GetWaits(int[] counts, int[] tileCount)
    {
        var waits = new List<int>();
        for (int i = 0; i < Tile.TileTypeCount; i++)
        {
            if (tileCount[i] >= Tile.MaxCountPerTile) continue;
            counts[i]++;
            if (ShantenCalculator.Calculate(FromCounts(counts)) == -1)
                waits.Add(i);
            counts[i]--;
        }
        return waits.ToArray();
    }

    private static double CalcGoodShapeRate(int[] waits, int[] tileCount)
    {
        // 良形 = 两面听 (ryanmen)、双碰 (shanpon) =~50%, 概率权重
        // 简易: 边张/坎张听不算良形
        if (waits.Length == 0) return 0;

        int good = 0;
        foreach (int w in waits)
        {
            if (IsRyanmenWait(w)) good++;
            if (IsShanponWait(w)) good += 1; // 双碰算半良形
        }

        return (double)good / waits.Length;
    }

    private static double CalcGoodShapeRatePossible(int[] counts, int[] tileCount)
    {
        // 在非听牌状态下，估算未来良形听牌的概率
        // 简化: 检查搭子的质量
        return 0.3; // 默认值
    }

    private static bool IsRyanmenWait(int tileId)
    {
        if (tileId >= 27) return false; // 字牌无两面
        int v = tileId % 9;
        return v is >= 1 and <= 7; // 不是1和9就可以有两面
    }

    private static bool IsShanponWait(int tileId) => true; // 任何牌都可能双碰

    private static Tile[] FromCounts(int[] counts)
    {
        var list = new List<Tile>();
        for (int i = 0; i < counts.Length; i++)
            for (int j = 0; j < counts[i]; j++)
                list.Add(new Tile(i));
        return list.ToArray();
    }
}

public struct CandidateDiscard
{
    public Tile Tile;
    public int Shanten;
    public int[] Waits;
    public int WaitCount;
    public double GoodShapeRate;
    public double Score;
}

public struct StrategyParams
{
    public double Aggression;       // 0.0-1.0
    public double Speed;            // 0.0-1.0
    public double RiskTolerance;    // 0.0-1.0
}
