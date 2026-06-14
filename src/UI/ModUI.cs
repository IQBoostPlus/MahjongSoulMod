namespace MahjongSoulMod.UI;

/// <summary>
/// Layer 6: MOD 配置界面
/// 基于 BepInEx ConfigurationManager 或游戏内 Overlay
/// </summary>
public class ModUI
{
    private bool _visible;

    public void Update()
    {
        // TODO: Unity IMGUI / 游戏内 Overlay 渲染
    }

    public void ShowDisabled()
    {
        Utils.LogWriter.Warning("[UI] MOD disabled overlay shown");
    }

    public void Toggle()
    {
        _visible = !_visible;
    }
}
