using MahjongSoulMod.AI;
using MahjongSoulMod.DataLayer;
using MahjongSoulMod.Safety;
using MahjongSoulMod.StateReconstruction;
using MahjongSoulMod.Strategy;

namespace MahjongSoulMod;

/// <summary>
/// 主循环（单例）
/// 协调各层数据流：读取 → 重建 → 决策 → 执行
/// </summary>
public class MainLoop
{
    public static readonly MainLoop Instance = new();

    private readonly GameDataReader _reader = new();
    private readonly StrategyController _strategy = new();
    private readonly DecisionCoordinator _coordinator;
    private readonly ActionExecutor _executor = new();
    private readonly SafetyController _safety = new();

    private GameState _lastState;
    private bool _hasPendingAction;

    private MainLoop()
    {
        _coordinator = new DecisionCoordinator(_strategy);
    }

    /// <summary>
    /// 每帧 Tick
    /// </summary>
    public void Tick()
    {
        // 1. 读取数据
        if (!_reader.TryReadSnapshot(out var snapshot))
            return;

        // 2. 状态重建
        var state = GameState.FromSnapshot(snapshot);
        if (state == null || !state.Validate())
            return;

        _lastState = state;

        // 3. 安全检查
        if (!_safety.IsEnabled)
            return;

        // 4. 判断是否需要行动
        if (!NeedsAction(state))
            return;

        // 5. AI 决策
        var decision = Decide(state);

        // 6. 人机化 + 执行
        _ = _safety.ExecuteWithHumanization(() =>
        {
            return _executor.Execute(decision);
        });
    }

    private GameActionDecision Decide(GameState state)
    {
        // 根据不同的触发场景分发到不同的决策模块
        // TODO: 区分摸牌后、鸣牌时、和牌时

        return _coordinator.DecideDiscard(state);
    }

    private static bool NeedsAction(GameState state)
    {
        // 只有轮到自家时才行动
        // TODO: 鸣牌/和牌选择不需要是自家回合
        return true;
    }
}
