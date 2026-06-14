using System;
using System.Collections.Generic;
using System.Linq;
using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.AI;

/// <summary>
/// Layer 3: 防守分析器
/// 基于对手舍牌信息评估每张牌的危险度
/// </summary>
public class DefenseAnalysis
{
    private readonly StrategyParams _params;

    // 安全等级
    public enum SafetyLevel
    {
        Safe,       // 现物 / 自家切过的牌
        SemiSafe,   // 筋 / 壁 / 早巡外侧
        Risky,      // 无筋 / 生牌 / 中张
        Dangerous,  // 立直后自摸切附近的生牌
    }

    public DefenseAnalysis(StrategyParams strategyParams)
    {
        _params = strategyParams;
    }

    /// <summary>
    /// 分析所有34种牌的危险度，0.0(绝对安全) ~ 1.0(极度危险)
    /// </summary>
    public double[] EvaluateRisks(GameState state, int targetPlayer)
    {
        var risks = new double[Tile.TileTypeCount];

        var discards = state.Discards[targetPlayer] ?? new List<Tile>();
        var discardsSet = new HashSet<int>(discards.Select(t => t.Id));
        var myDiscards = state.Discards[state.SelfSeat] ?? new List<Tile>();
        var myDiscardsSet = new HashSet<int>(myDiscards.Select(t => t.Id));

        for (int id = 0; id < Tile.TileTypeCount; id++)
        {
            Tile tile = new(id);

            // 1) 现物 — 绝对安全
            if (discardsSet.Contains(id))
            {
                risks[id] = 0.0;
                continue;
            }

            // 2) 自家切过的牌 — 安全（对方立直后）
            if (myDiscardsSet.Contains(id))
            {
                risks[id] = 0.05;
                continue;
            }

            // 3) 筋牌计算 (对手舍牌的±3)
            bool isSuji = discards.Any(d => IsSujiOf(d.Id, id));
            if (isSuji)
            {
                risks[id] = 0.15;
                continue;
            }

            // 4) 壁牌计算 (某数值出现4枚)
            bool isWall = IsWall(discards, id);
            if (isWall)
            {
                risks[id] = 0.2;
                continue;
            }

            // 5) 早巡外侧
            bool isEarlyOutside = IsEarlyOutside(discards, id);
            if (isEarlyOutside)
            {
                risks[id] = 0.25;
                continue;
            }

            // 6) 默认: 按花色和数值给基础危险度
            risks[id] = CalculateBaseRisk(tile);
        }

        return risks;
    }

    /// <summary>
    /// 获取安全度最高的可切牌（弃和用）
    /// </summary>
    public Tile[] GetSafeDiscards(GameState state, int targetPlayer)
    {
        var risks = EvaluateRisks(state, targetPlayer);
        var handRisks = new List<(Tile tile, double risk)>();

        foreach (var tile in state.Hand)
        {
            handRisks.Add((tile, risks[tile.Id]));
        }

        return handRisks.OrderBy(r => r.risk).Select(r => r.tile).ToArray();
    }

    /// <summary>
    /// 是否筋牌关系: 数字3的差值
    /// </summary>
    private static bool IsSujiOf(int discardId, int targetId)
    {
        if (discardId >= 27 || targetId >= 27) return false;
        int dValue = discardId % 9 + 1;
        int tValue = targetId % 9 + 1;
        return Math.Abs(dValue - tValue) == 3;
    }

    /// <summary>
    /// 是否壁牌: 某数值出现4枚
    /// </summary>
    private static bool IsWall(List<Tile> discards, int targetId)
    {
        if (targetId >= 27) return false;
        int suit = targetId / 9;
        int value = targetId % 9 + 1;

        bool wallL = value >= 3 && discards.Count(d =>
            d.Suit == suit && d.Value == value - 1) >= 3;
        bool wallR = value <= 7 && discards.Count(d =>
            d.Suit == suit && d.Value == value + 1) >= 3;

        return wallL || wallR;
    }

    /// <summary>
    /// 早巡外侧: 该花色在早巡有1-2巡切过两端之外
    /// </summary>
    private static bool IsEarlyOutside(List<Tile> discards, int targetId)
    {
        if (targetId >= 27) return false;
        // 简化: 非字牌在1-3巡切过相邻花色 -> 近似
        return false;
    }

    private static double CalculateBaseRisk(Tile tile)
    {
        // 字牌 warning （字牌通常更危险）
        if (tile.IsHonor) return 0.5;

        // 中张危险
        if (tile.Value is >= 4 and <= 6) return 0.6;

        // 边张较安全
        if (tile.Value is 1 or 9) return 0.35;

        return 0.5;
    }
}
