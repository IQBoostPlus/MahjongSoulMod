using System;
using System.Collections.Generic;
using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.DataLayer;

/// <summary>
/// Layer 1B: 动作执行器
/// 将 AI 决策转换为游戏内的实际动作
/// </summary>
public class ActionExecutor
{
    private InputSimulator _inputSim = new();
    private HarmonyInvoker _harmonyInvoker = new();

    /// <summary>
    /// 执行动作，优先使用 Harmony hook 内部调用，降级到输入模拟
    /// </summary>
    public bool Execute(GameActionDecision decision)
    {
        if (!TryInvokeInternal(decision))
        {
            return SimulateClick(decision);
        }
        return true;
    }

    private bool TryInvokeInternal(GameActionDecision decision)
    {
        try
        {
            switch (decision.Action)
            {
                case GameActionType.Discard:
                    // TODO: Harmony hook 调用内部 Discard(Tile) 方法
                    return _harmonyInvoker.Discard(decision.Tile);
                case GameActionType.Pon:
                    return _harmonyInvoker.CallPon();
                case GameActionType.Chi:
                    return _harmonyInvoker.CallChi();
                case GameActionType.Kan:
                    return _harmonyInvoker.CallKan();
                case GameActionType.Riichi:
                    return _harmonyInvoker.DeclareRiichi(decision.Tile);
                case GameActionType.Ron:
                    return _harmonyInvoker.CallRon();
                case GameActionType.Tsumo:
                    return _harmonyInvoker.CallTsumo();
                case GameActionType.Pass:
                    return _harmonyInvoker.CallPass();
                default:
                    return false;
            }
        }
        catch
        {
            return false; // 降级到输入模拟
        }
    }

    private bool SimulateClick(GameActionDecision decision)
    {
        return _inputSim.ClickAction(decision);
    }
}

/// <summary>
/// AI 决策的输出 —— 要执行的动作
/// </summary>
public struct GameActionDecision
{
    public GameActionType Action;
    public Tile Tile;       // 关联的牌（如切哪张、立直切哪张）
    public int CallTarget;  // 鸣牌目标 (0-3)
}

public enum GameActionType
{
    Discard,        // 打牌
    Riichi,         // 立直
    Pon,            // 碰
    Chi,            // 吃
    Kan,            // 杠
    Ron,            // 荣和
    Tsumo,          // 自摸
    Pass,           // 跳过
}

/// <summary>
/// Harmony 方式调用游戏内部方法
/// </summary>
internal class HarmonyInvoker
{
    public bool Discard(Tile tile) => false;    // TODO
    public bool CallPon() => false;
    public bool CallChi() => false;
    public bool CallKan() => false;
    public bool DeclareRiichi(Tile tile) => false;
    public bool CallRon() => false;
    public bool CallTsumo() => false;
    public bool CallPass() => false;
}

/// <summary>
/// Windows 输入模拟（降级方案）
/// </summary>
internal class InputSimulator
{
    public bool ClickAction(GameActionDecision decision) => false; // TODO
}
