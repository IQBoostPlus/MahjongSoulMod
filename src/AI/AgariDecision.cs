using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.AI;

/// <summary>
/// Layer 3: 和牌决策器
/// </summary>
public class AgariDecision
{
    private readonly StrategyParams _params;

    public AgariDecision(StrategyParams strategyParams)
    {
        _params = strategyParams;
    }

    /// <summary>
    /// 判断是否应当和牌（荣和/自摸）
    /// </summary>
    public bool ShouldAgari(GameState state, bool isTsumo)
    {
        // 默认: 总是和牌
        // 特殊场景可跳过:
        // 1. 亲家连庄利益 > 和牌收益
        // 2. 故意做更高级手役（几乎不会出现）
        return true;
    }
}
