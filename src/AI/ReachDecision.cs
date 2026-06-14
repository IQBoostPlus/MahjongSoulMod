using System.Linq;
using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.AI;

/// <summary>
/// Layer 3: 立直决策器
/// </summary>
public class ReachDecision
{
    private readonly StrategyParams _params;

    public ReachDecision(StrategyParams strategyParams)
    {
        _params = strategyParams;
    }

    /// <summary>
    /// 判断是否应当立直
    /// </summary>
    public bool ShouldRiichi(Tile[] hand, Tile[] discards, GameState state)
    {
        // 条件: 门前清、听牌、有1000点棒
        if (state.Scores[state.SelfSeat] < 1000) return false;

        int shanten = ShantenCalculator.Calculate(hand);
        if (shanten != -1) return false;

        // 巡目
        int turn = state.RemainingTiles / 4; // 简化
        if (turn > 12 && _params.Aggression < 0.5) return false;

        // 打点期望
        if (_params.Aggression < 0.3) return false;

        return true;
    }

    /// <summary>
    /// 立直时切哪张
    /// </summary>
    public Tile GetRiichiDiscard(Tile[] hand)
    {
        // 通常切安全度最高的听牌
        // 简化: 取第一张切过的安全牌
        return hand[0];
    }
}
