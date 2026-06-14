using System;
using System.Threading.Tasks;
using MahjongSoulMod.Config;

namespace MahjongSoulMod.Safety;

/// <summary>
/// Layer 5: 人机化引擎
/// 对 AI 动作施加随机延迟、误差和拟人化处理
/// </summary>
public class HumanizationEngine
{
    private readonly Random _rng = new();

    /// <summary>
    /// 随机延迟（正态分布）
    /// </summary>
    public async Task RandomDelay()
    {
        int mean = (ModConfig.MinDelayMs.Value + ModConfig.MaxDelayMs.Value) / 2;
        int stdDev = (ModConfig.MaxDelayMs.Value - ModConfig.MinDelayMs.Value) / 3;

        int ms = NextGaussian(mean, stdDev);
        ms = Math.Clamp(ms, ModConfig.MinDelayMs.Value, ModConfig.MaxDelayMs.Value);

        if (ms > 0)
            await Task.Delay(ms);
    }

    /// <summary>
    /// 等优选项时随机选择（模拟人类不总是选最优）
    /// </summary>
    public T PickWithRandomness<T>(T[] candidates, double errorRate = 0.02)
    {
        if (candidates.Length == 0) return default;
        if (_rng.NextDouble() < errorRate)
            return candidates[_rng.Next(candidates.Length)];
        return candidates[0];
    }

    private int NextGaussian(int mean, int stdDev)
    {
        double u1 = 1.0 - _rng.NextDouble();
        double u2 = 1.0 - _rng.NextDouble();
        double randStdNormal = Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Sin(2.0 * Math.PI * u2);
        return (int)(mean + stdDev * randStdNormal);
    }
}
