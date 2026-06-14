using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.UI;

/// <summary>
/// Layer 6: 状态叠加显示
/// 在游戏画面上显示 MOD 状态和 AI 决策信息
/// </summary>
public class StatusOverlay
{
    public bool Visible { get; set; } = true;

    /// <summary>
    /// 渲染状态信息
    /// </summary>
    public void Render(GameState state)
    {
        if (!Visible) return;

        // TODO: Unity IMGUI OnGUI 渲染
        // 显示:
        // - MOD 启用状态
        // - 当前向听数
        // - AI 推荐打牌
    }
}
