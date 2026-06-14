using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.Strategy;

/// <summary>
/// Layer 4: 局况判断
/// 提供游戏状态的高层语义判断
/// </summary>
public static class SituationalJudgment
{
    /// <summary>
    /// 是否处于东场 (East round)
    /// </summary>
    public static bool IsEastRound(GameState state) => state.RoundWind == 0;

    /// <summary>
    /// 是否处于南场 (South round)
    /// </summary>
    public static bool IsSouthRound(GameState state) => state.RoundWind == 1;

    /// <summary>
    /// 是否最终局
    /// </summary>
    public static bool IsAllLast(GameState state)
    {
        // 简化: 南4局为AL
        return state.RoundWind == 1 && state.Honba == 0;
    }

    /// <summary>
    /// 是否坐庄 (Dealer)
    /// </summary>
    public static bool IsDealer(GameState state) => state.SelfSeat == 0;

    /// <summary>
    /// 是否有对手立直
    /// </summary>
    public static bool AnyOpponentReached(GameState state)
    {
        // TODO: 通过游戏状态检查对手立直旗
        return false;
    }

    /// <summary>
    /// 判断当前巡目阶段
    /// </summary>
    public static RoundPhase GetRoundPhase(GameState state)
    {
        int discards = state.Discards?[state.SelfSeat]?.Count ?? 0;
        if (discards <= 5) return RoundPhase.Early;
        if (discards <= 12) return RoundPhase.Mid;
        return RoundPhase.Late;
    }
}

public enum RoundPhase
{
    Early,  // 序盘 (1-5巡)
    Mid,    // 中盘 (6-12巡)
    Late,   // 终盘 (13+巡)
}
