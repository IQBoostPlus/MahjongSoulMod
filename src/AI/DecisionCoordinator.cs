using System;
using System.Collections.Generic;
using System.Linq;
using MahjongSoulMod.DataLayer;
using MahjongSoulMod.StateReconstruction;
using MahjongSoulMod.Strategy;

namespace MahjongSoulMod.AI;

/// <summary>
/// Layer 3: 决策协调器
/// 整合各决策模块，基于策略参数产生最终动作
/// </summary>
public class DecisionCoordinator
{
    private readonly StrategyController _strategy;
    private TileEfficiency _tileEfficiency;
    private DefenseAnalysis _defense;
    private CallDecision _call;
    private ReachDecision _reach;
    private AgariDecision _agari;

    public DecisionCoordinator(StrategyController strategy)
    {
        _strategy = strategy;
        _tileEfficiency = new TileEfficiency(strategy.CurrentParams);
        _defense = new DefenseAnalysis(strategy.CurrentParams);
        _call = new CallDecision(strategy.CurrentParams);
        _reach = new ReachDecision(strategy.CurrentParams);
        _agari = new AgariDecision(strategy.CurrentParams);
    }

    /// <summary>
    /// 刷新策略参数（每回合调用）
    /// </summary>
    public void Refresh(GameState state)
    {
        _strategy.Update(state);
        var p = _strategy.CurrentParams;
        _tileEfficiency = new TileEfficiency(p);
        _defense = new DefenseAnalysis(p);
        _call = new CallDecision(p);
        _reach = new ReachDecision(p);
        _agari = new AgariDecision(p);
    }

    /// <summary>
    /// AI 主决策入口：自家摸牌后决定切哪张
    /// </summary>
    public GameActionDecision DecideDiscard(GameState state)
    {
        Refresh(state);

        // 0) 听牌时检查立直
        int shanten = ShantenCalculator.Calculate(state.Hand);
        if (shanten == -1 && _reach.ShouldRiichi(state.Hand, null, state))
        {
            return new GameActionDecision
            {
                Action = GameActionType.Riichi,
                Tile = _reach.GetRiichiDiscard(state.Hand)
            };
        }

        // 1) 评估防守态势
        bool shouldDefend = ShouldDefend(state);

        if (shouldDefend)
        {
            return GetDefensiveDiscard(state);
        }

        // 2) 进攻: 牌效率分析
        var candidates = _tileEfficiency.Evaluate(state.Hand, state.TileCount);

        if (candidates.Count > 0)
        {
            var best = candidates[0];
            return new GameActionDecision
            {
                Action = GameActionType.Discard,
                Tile = best.Tile
            };
        }

        return new GameActionDecision
        {
            Action = GameActionType.Discard,
            Tile = state.Hand[0]
        };
    }

    /// <summary>
    /// 对手打牌后决定是否鸣牌
    /// </summary>
    public GameActionDecision DecideCall(Tile incomingTile, GameState state)
    {
        Refresh(state);

        if (_call.ShouldPon(incomingTile, state.Hand, state))
        {
            return new GameActionDecision { Action = GameActionType.Pon, Tile = incomingTile };
        }

        if (_call.ShouldChi(incomingTile, state.Hand, state))
        {
            return new GameActionDecision { Action = GameActionType.Chi, Tile = incomingTile };
        }

        return new GameActionDecision { Action = GameActionType.Pass };
    }

    /// <summary>
    /// 和牌判定
    /// </summary>
    public GameActionDecision DecideAgari(GameState state, bool isTsumo)
    {
        return new GameActionDecision
        {
            Action = _agari.ShouldAgari(state, isTsumo) ? GameActionType.Ron : GameActionType.Pass
        };
    }

    private static bool ShouldDefend(GameState state)
    {
        // 检查是否有对手立直、副露多等危险信号
        for (int i = 0; i < 4; i++)
        {
            if (i == state.SelfSeat) continue;
            // 立直检查 (需通过游戏数据)
        }
        return false;
    }

    private GameActionDecision GetDefensiveDiscard(GameState state)
    {
        // 找出最安全的弃牌
        foreach (var p in Enumerable.Range(0, 4).Where(p => p != state.SelfSeat))
        {
            var safe = _defense.GetSafeDiscards(state, p);
            if (safe.Length > 0)
            {
                return new GameActionDecision
                {
                    Action = GameActionType.Discard,
                    Tile = safe[0]
                };
            }
        }

        return new GameActionDecision
        {
            Action = GameActionType.Discard,
            Tile = state.Hand[0]
        };
    }
}
