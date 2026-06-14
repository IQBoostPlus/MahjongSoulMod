using MahjongSoulMod.Config;

namespace MahjongSoulMod.Safety;

/// <summary>
/// Layer 5: 安全控制器
/// 控制 MOD 总体启用状态、人机化和反检测机制
/// </summary>
public class SafetyController
{
    private readonly HumanizationEngine _humanizer = new();
    private int _frameSinceLastAction;
    private bool _isEnabled = true;

    public bool IsEnabled => _isEnabled && ModConfig.Enabled.Value;

    /// <summary>
    /// 每帧调用
    /// </summary>
    public void Update()
    {
        _frameSinceLastAction++;

        if (!ModConfig.Enabled.Value && _isEnabled)
            Disable();
    }

    /// <summary>
    /// 是否可以执行 AI 决策和动作
    /// </summary>
    public bool ShouldAct()
    {
        if (!IsEnabled) return false;

        // 频率限制: 至少间隔 N 帧
        if (_frameSinceLastAction < 3) return false;

        return true;
    }

    /// <summary>
    /// 人机化延迟后执行动作
    /// </summary>
    public async System.Threading.Tasks.Task ExecuteWithHumanization(System.Func<bool> action)
    {
        if (ModConfig.SafetyMode.Value)
        {
            await _humanizer.RandomDelay();
        }

        action();
        _frameSinceLastAction = 0;
    }

    public void Disable()
    {
        _isEnabled = false;
        Utils.LogWriter.Warning("[Safety] MOD disabled");
    }

    public void Enable()
    {
        _isEnabled = true;
        Utils.LogWriter.Info("[Safety] MOD enabled");
    }
}
