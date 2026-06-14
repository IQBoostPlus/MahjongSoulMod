using System;

namespace MahjongSoulMod.Safety;

/// <summary>
/// Layer 5: 紧急停止开关
/// </summary>
public class KillSwitch
{
    public event Action OnKillSwitchActivated;
    private bool _activated;

    /// <summary>
    /// 每帧检查
    /// </summary>
    public void Check()
    {
        // TODO: 检测快捷键 (Unity Input / Windows 全局钩子)
        // if (Input.GetKeyDown(ModConfig.KillSwitchKey.Value))
        // {
        //     Activate();
        // }

        // 异常检测: 游戏状态异常时自动禁用
        if (DetectAnomaly())
        {
            Activate();
        }
    }

    public void Activate()
    {
        if (_activated) return;
        _activated = true;
        OnKillSwitchActivated?.Invoke();
    }

    public void Reset()
    {
        _activated = false;
    }

    private static bool DetectAnomaly()
    {
        // 检测: 游戏版本不匹配、读取数据异常等
        return false;
    }
}
