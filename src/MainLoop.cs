using MahjongSoulMod.AI;
using MahjongSoulMod.DataLayer;
using MahjongSoulMod.StateReconstruction;
using MahjongSoulMod.Strategy;

namespace MahjongSoulMod;

/// <summary>
/// 主循环：读取 → 重建 → 决策 → 执行
/// </summary>
public class MainLoop
{
    public static readonly MainLoop Instance = new();

    private readonly GameDataReader _reader = new();
    private readonly StrategyController _strategy = new();
    private readonly DecisionCoordinator _coordinator;
    private readonly ActionExecutor _executor = new();

    private int _tickCount;
    private int _emptyHandCount;
    private GameState? _lastState;

    private MainLoop()
    {
        _coordinator = new DecisionCoordinator(_strategy);
    }

    public void Tick()
    {
        _tickCount++;

        // 1. 读取数据
        if (!_reader.TryReadSnapshot(out var snapshot))
        {
            if (_tickCount % 60 == 0)
                Utils.LogWriter.Info("[MainLoop] No game data yet (waiting for match)...");
            return;
        }

        // 2. 状态重建
        var state = GameState.FromSnapshot(snapshot);
        if (state == null)
        {
            Utils.LogWriter.Warning("[MainLoop] Failed to build game state");
            return;
        }

        _lastState = state;

        // 3. 验证状态
        if (!state.Validate())
        {
            Utils.LogWriter.Warning("[MainLoop] Invalid state");
            return;
        }

        // 4. 手牌为空 → 不在对局中
        if (state.Hand.Length == 0)
        {
            _emptyHandCount++;
            if (_emptyHandCount == 1 || _emptyHandCount % 300 == 0)
                Utils.LogWriter.Info("[MainLoop] Not in game (empty hand)");
            return;
        }
        _emptyHandCount = 0;

        // 5. 安全检查
        // (SafetyController already checked in MainPlugin)

        // 6. 判断是否需要行动
        if (!NeedsAction(state))
            return;

        // 7. AI 决策
        var decision = Decide(state);

        // 8. 执行
        _executor.Execute(decision);
    }

    private GameActionDecision Decide(GameState state)
    {
        try
        {
            return _coordinator.DecideDiscard(state);
        }
        catch (System.Exception ex)
        {
            Utils.LogWriter.Error($"[MainLoop] AI decision failed: {ex.Message}");
            return new GameActionDecision { Action = GameActionType.Pass };
        }
    }

    private static bool NeedsAction(GameState state)
    {
        // TODO: 区分摸牌后、鸣牌时、和牌时
        return true;
    }
}
