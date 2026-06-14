using System;
using System.Reflection;
using MahjongSoulMod.StateReconstruction;
using UnityEngine;

namespace MahjongSoulMod.DataLayer;

/// <summary>
/// Layer 1B: 动作执行器
/// </summary>
public class ActionExecutor
{
    public bool Execute(GameActionDecision decision)
    {
        try
        {
            // 优先: 尝试反射调用游戏内部方法
            if (TryReflectInvoke(decision))
                return true;

            // 降级: 模拟点击
            if (SimulateClick(decision))
                return true;

            // 兜底: 只记录
            Utils.LogWriter.Info($"[Action] Cannot execute {decision.Action} " +
                $"(tile={decision.Tile}, target={decision.CallTarget})");
            return false;
        }
        catch (Exception ex)
        {
            Utils.LogWriter.Warning($"[Action] Failed: {ex.Message}");
            return false;
        }
    }

    /// <summary>
    /// 通过反射查找并调用游戏内部动作方法
    /// </summary>
    private bool TryReflectInvoke(GameActionDecision decision)
    {
        try
        {
            // 查找 GameEngine.Inst 上的方法
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (!asm.GetName().Name.Contains("Assembly-CSharp"))
                    continue;

                var engineType = asm.GetType("GameEngine", false);
                if (engineType == null) continue;

                var instField = engineType.GetField("Inst",
                    BindingFlags.Public | BindingFlags.Static);
                var inst = instField?.GetValue(null);
                if (inst == null) continue;

                // 尝试调用带 action 名称的方法
                string methodName = decision.Action switch
                {
                    GameActionType.Discard => "OnDiscard",
                    GameActionType.Pon => "OnPon",
                    GameActionType.Chi => "OnChi",
                    GameActionType.Kan => "OnKan",
                    GameActionType.Riichi => "OnRiichi",
                    GameActionType.Pass => "OnPass",
                    _ => null
                };

                if (methodName == null) return false;

                var method = engineType.GetMethod(methodName,
                    BindingFlags.Public | BindingFlags.NonPublic |
                    BindingFlags.Instance | BindingFlags.Static);
                if (method != null)
                {
                    method.Invoke(inst, null);
                    Utils.LogWriter.Info($"[Action] Invoked {methodName}()");
                    return true;
                }

                break;
            }
        }
        catch { }
        return false;
    }

    /// <summary>
    /// 通过 Unity UI 事件系统模拟点击
    /// </summary>
    private bool SimulateClick(GameActionDecision decision)
    {
        try
        {
            string buttonName = decision.Action switch
            {
                GameActionType.Discard => "BtnDiscard",
                GameActionType.Pon => "BtnPon",
                GameActionType.Chi => "BtnChi",
                GameActionType.Kan => "BtnKan",
                GameActionType.Riichi => "BtnRiichi",
                GameActionType.Pass => "BtnPass",
                _ => null
            };

            if (buttonName == null) return false;

            var btn = GameObject.Find(buttonName);
            if (btn == null)
            {
                // 尝试备选命名
                foreach (var suffix in new[] { "Button", "", "_btn" })
                {
                    btn = GameObject.Find(buttonName + suffix)
                        ?? GameObject.Find(decision.Action.ToString() + suffix);
                    if (btn != null) break;
                }
            }

            if (btn != null)
            {
                var btnComponent = btn.GetComponent<UnityEngine.UI.Button>();
                if (btnComponent != null)
                {
                    btnComponent.onClick.Invoke();
                    Utils.LogWriter.Info($"[Action] Clicked {btn.name}");
                    return true;
                }
            }

            return false;
        }
        catch
        {
            return false;
        }
    }
}

public struct GameActionDecision
{
    public GameActionType Action;
    public Tile Tile;
    public int CallTarget;
}

public enum GameActionType
{
    Discard, Riichi, Pon, Chi, Kan, Ron, Tsumo, Pass
}
