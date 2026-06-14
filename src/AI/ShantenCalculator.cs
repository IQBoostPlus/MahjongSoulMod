using System;
using System.Collections.Generic;
using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.AI;

/// <summary>
/// Layer 3: 向听数计算器
/// 支持标准手、七对子、国士无双三种向听数计算
/// </summary>
public class ShantenCalculator
{
    /// <summary>
    /// 计算最少向听数（取标准手/七对子/国士无双的最小值）
    /// </summary>
    public static int Calculate(Tile[] hand)
    {
        if (hand.Length == 0) return -1; // 不可能

        int[] counts = ToCountArray(hand);
        int totalTiles = hand.Length;

        int normal = NormalShanten(counts, totalTiles);
        int chiitoi = ChiitoiShanten(counts);
        int kokushi = KokushiShanten(counts);

        return Math.Min(normal, Math.Min(chiitoi, kokushi));
    }

    /// <summary>
    /// 标准手向听数
    /// 基于递归拆解: (4 - 面子数) * 2 - 搭子数
    /// </summary>
    public static int NormalShanten(int[] counts, int totalTiles)
    {
        int neededMelds = totalTiles / 3;   // 通常为4
        int minShanten = int.MaxValue;

        // 枚举雀头位置
        for (int i = 0; i < Tile.TileTypeCount; i++)
        {
            if (counts[i] < 2) continue;

            counts[i] -= 2;
            int shanten = CalculateMentsuShanten(counts, neededMelds, 0, 0);
            counts[i] += 2;

            if (shanten < minShanten) minShanten = shanten;
        }

        // 无雀头的情况（雀头不足，当 minShanten==int.MaxValue 时说明手牌全是搭子无对子）
        if (minShanten == int.MaxValue)
        {
            minShanten = CalculateMentsuShanten(counts, neededMelds, 0, 0) + 1;
        }

        return minShanten;
    }

    private static int CalculateMentsuShanten(int[] counts, int targetMelds, int melds, int partials)
    {
        if (melds > targetMelds) return int.MaxValue;
        if (partials > targetMelds - melds) partials = targetMelds - melds;

        if (IsAllZero(counts))
        {
            // 核心公式: shanten = 2*(targetMelds - melds) - partials
            // 减 1 是因为已在外层循环移除了雀头
            int shanten = 2 * (targetMelds - melds) - partials - 1;
            return shanten < -1 ? -1 : shanten;
        }

        // 找到第一个非零位置
        int pos = 0;
        while (pos < Tile.TileTypeCount && counts[pos] == 0) pos++;

        int minShanten = int.MaxValue;

        // 1) 取顺子（仅限于非字牌）
        if (pos < 27 && pos % 9 < 7 && counts[pos] > 0 && counts[pos + 1] > 0 && counts[pos + 2] > 0)
        {
            counts[pos]--; counts[pos + 1]--; counts[pos + 2]--;
            int s = CalculateMentsuShanten(counts, targetMelds, melds + 1, partials);
            counts[pos]++; counts[pos + 1]++; counts[pos + 2]++;
            if (s < minShanten) minShanten = s;
        }

        // 2) 取刻子
        if (counts[pos] >= 3)
        {
            counts[pos] -= 3;
            int s = CalculateMentsuShanten(counts, targetMelds, melds + 1, partials);
            counts[pos] += 3;
            if (s < minShanten) minShanten = s;
        }

        // 3) 取搭子
        if (counts[pos] >= 2)
        {
            // 对子
            counts[pos] -= 2;
            int s = CalculateMentsuShanten(counts, targetMelds, melds, partials + 1);
            counts[pos] += 2;
            if (s < minShanten) minShanten = s;
        }

        // 两面/坎张/边张
        if (pos < 27 && pos % 9 < 8 && counts[pos] > 0 && counts[pos + 1] > 0)
        {
            counts[pos]--; counts[pos + 1]--;
            int s = CalculateMentsuShanten(counts, targetMelds, melds, partials + 1);
            counts[pos]++; counts[pos + 1]++;
            if (s < minShanten) minShanten = s;
        }

        if (pos < 27 && pos % 9 < 7 && counts[pos] > 0 && counts[pos + 2] > 0)
        {
            counts[pos]--; counts[pos + 2]--;
            int s = CalculateMentsuShanten(counts, targetMelds, melds, partials + 1);
            counts[pos]++; counts[pos + 2]++;
            if (s < minShanten) minShanten = s;
        }

        // 4) 孤张 — 跳过这张牌
        {
            int cnt = counts[pos];
            counts[pos] = 0;
            int s = CalculateMentsuShanten(counts, targetMelds, melds, partials);
            counts[pos] = cnt;
            if (s < minShanten) minShanten = s;
        }

        return minShanten;
    }

    /// <summary>
    /// 七对子向听数
    /// pairs = 满对子数 (count/2), 例如 3枚相同牌 = 1对 + 1单张
    /// </summary>
    public static int ChiitoiShanten(int[] counts)
    {
        int pairs = 0;
        int singles = 0;

        for (int i = 0; i < Tile.TileTypeCount; i++)
        {
            pairs += counts[i] / 2;
            singles += counts[i] % 2;
        }

        if (pairs >= 7) return -1;  // 完成
        if (pairs == 6) return 0;   // 听牌

        return 6 - pairs;
    }

    /// <summary>
    /// 国士无双向听数
    /// </summary>
    public static int KokushiShanten(int[] counts)
    {
        // 13种幺九牌索引
        int[] yaochuIds = [
            0, 8,      // 一万、九万
            9, 17,     // 一筒、九筒
            18, 26,    // 一索、九索
            27, 28, 29, 30, 31, 32, 33 // 东南西北白发中
        ];

        int unique = 0;
        bool hasPair = false;

        foreach (int id in yaochuIds)
        {
            if (counts[id] >= 1) unique++;
            if (counts[id] >= 2) hasPair = true;
        }

        int shanten = 13 - unique;
        if (hasPair) shanten--;

        return shanten;
    }

    /// <summary>
    /// 将手牌 Tile 数组转换为 34 维计数数组
    /// </summary>
    public static int[] ToCountArray(Tile[] hand)
    {
        var arr = new int[Tile.TileTypeCount];
        foreach (var tile in hand)
            if (tile.Id >= 0 && tile.Id < Tile.TileTypeCount)
                arr[tile.Id]++;
        return arr;
    }

    /// <summary>
    /// 计算听牌后能和的牌列表
    /// </summary>
    public static Tile[] GetWaitingTiles(int[] counts)
    {
        var waits = new List<Tile>();

        for (int i = 0; i < Tile.TileTypeCount; i++)
        {
            if (counts[i] >= Tile.MaxCountPerTile) continue;

            counts[i]++;
            if (Calculate(new[] { new Tile(0) }) == -1) // 简化: 需完整判断
            {
                // 实际上需要完整构建14枚手牌判断，此处为伪代码
            }
            counts[i]--;
        }

        return waits.ToArray();
    }

    private static bool IsAllZero(int[] arr)
    {
        foreach (int v in arr)
            if (v != 0) return false;
        return true;
    }
}
