using MahjongSoulMod.DataLayer;

namespace MahjongSoulMod.StateReconstruction;

/// <summary>
/// Layer 2: 状态校验器
/// </summary>
public static class StateValidator
{
    /// <summary>
    /// 校验原始快照的一致性
    /// </summary>
    public static bool ValidateSnapshot(GameStateSnapshot raw)
    {
        if (raw.HandTiles == null) return false;

        // 手牌数量合理 (13或14枚)
        if (raw.HandTiles.Length is < 1 or > 14) return false;

        // 舍牌数组4位玩家
        if (raw.Discards == null || raw.Discards.Length != 4) return false;

        // 副露数组4位玩家
        if (raw.Melds == null || raw.Melds.Length != 4) return false;

        // 点数数组
        if (raw.Scores == null || raw.Scores.Length != 4) return false;

        return true;
    }

    /// <summary>
    /// 检查 GameState 是否可用于 AI 决策
    /// </summary>
    public static bool IsReadyForAI(GameState state)
    {
        return state != null && state.Validate();
    }
}
