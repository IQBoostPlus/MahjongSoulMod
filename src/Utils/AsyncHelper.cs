using System;
using System.Threading.Tasks;

namespace MahjongSoulMod.Utils;

/// <summary>
/// 异步辅助
/// </summary>
public static class AsyncHelper
{
    private static readonly Random _rng = new();

    /// <summary>
    /// 延迟指定毫秒（可中途取消）
    /// </summary>
    public static async Task Delay(int ms)
    {
        if (ms > 0)
            await Task.Delay(ms);
    }

    /// <summary>
    /// 在范围内随机延迟
    /// </summary>
    public static async Task RandomDelay(int minMs, int maxMs)
    {
        if (maxMs <= 0) return;
        int ms = _rng.Next(Math.Max(minMs, 0), maxMs);
        await Delay(ms);
    }

    /// <summary>
    /// 正态分布的随机延迟（更拟人化）
    /// </summary>
    public static async Task NormalDistributedDelay(int meanMs, int stdDevMs)
    {
        int ms = NextGaussian(meanMs, stdDevMs);
        ms = Math.Clamp(ms, 50, 5000);
        await Delay(ms);
    }

    private static int NextGaussian(int mean, int stdDev)
    {
        double u1 = 1.0 - _rng.NextDouble();
        double u2 = 1.0 - _rng.NextDouble();
        double randStdNormal = Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Sin(2.0 * Math.PI * u2);
        return (int)(mean + stdDev * randStdNormal);
    }
}
