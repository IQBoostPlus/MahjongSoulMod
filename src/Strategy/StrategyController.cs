using MahjongSoulMod.Config;
using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.Strategy;

/// <summary>
/// Layer 4: 策略控制器
/// 根据局况动态调整攻击性/速度偏好/风险容忍度
/// </summary>
public class StrategyController
{
    public AI.StrategyParams CurrentParams { get; private set; }

    public StrategyController()
    {
        CurrentParams = new AI.StrategyParams
        {
            Aggression = 0.5,
            Speed = 0.5,
            RiskTolerance = 0.5
        };
    }

    /// <summary>
    /// 每回合更新策略参数
    /// </summary>
    public void Update(GameState state)
    {
        var p = new AI.StrategyParams();

        // 基础值: 从配置加载
        p.Aggression = Normalize(ModConfig.AggressionLevel.Value);
        p.Speed = Normalize(ModConfig.SpeedPreference.Value);
        p.RiskTolerance = Normalize(ModConfig.RiskTolerance.Value);

        // 局况调整: 点棒状况
        int selfIndex = state.SelfSeat;
        int selfScore = state.Scores[selfIndex];
        int maxScore = 0, minScore = int.MaxValue;
        foreach (var s in state.Scores) { if (s > maxScore) maxScore = s; if (s < minScore) minScore = s; }
        bool isLeading = selfScore == maxScore;
        bool isLast = selfScore == minScore;

        // 领先时趋于保守
        if (isLeading) { p.Aggression -= 0.15; p.RiskTolerance -= 0.15; }
        // 落后时趋于激进
        if (isLast) { p.Aggression += 0.15; p.RiskTolerance += 0.15; }

        // AL (最后一局) 判断
        if (IsAllLast(state))
        {
            int diffFromFirst = maxScore - selfScore;
            if (diffFromFirst > 10000 && !isLeading)
            {
                p.Aggression = 1.0;
                p.RiskTolerance = 1.0;
                p.Speed = 1.0;
            }
        }

        // 裁剪
        p.Aggression = Clamp(p.Aggression);
        p.Speed = Clamp(p.Speed);
        p.RiskTolerance = Clamp(p.RiskTolerance);

        CurrentParams = p;
    }

    private static bool IsAllLast(GameState state)
    {
        // 南4局 (South round, 4th honba) 或东4局东场最后一局无连庄时
        return state.RoundWind == 1; // 南场 = RoundWind == 1
    }

    private static double Normalize(int configValue) => (configValue - 1) / 4.0;
    private static double Clamp(double v) => v < 0 ? 0 : v > 1 ? 1 : v;
}
