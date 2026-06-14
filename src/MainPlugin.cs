using BepInEx;
using HarmonyLib;
using MahjongSoulMod.Config;
using MahjongSoulMod.Safety;
using MahjongSoulMod.UI;
using MahjongSoulMod.Utils;

namespace MahjongSoulMod;

/// <summary>
/// BepInEx 6 IL2CPP MOD 入口点 — Layer 0: MOD 框架层
///
/// 每帧驱动通过 Harmony hook 实现:
/// - hook LuaLooper.Update() → OnUpdate() 每帧调用
/// - hook LuaLooper.LateUpdate() → OnLateUpdate() 备用
/// </summary>
[BepInPlugin(MyPluginInfo.PLUGIN_GUID, MyPluginInfo.PLUGIN_NAME, MyPluginInfo.PLUGIN_VERSION)]
public class MainPlugin : BepInEx.Unity.IL2CPP.BasePlugin
{
    public override void Load()
    {
        Log.LogInfo($"Loading {MyPluginInfo.PLUGIN_NAME} v{MyPluginInfo.PLUGIN_VERSION}");

        try
        {
            ModConfig.Bind(Config);
            LogWriter.Init(Log);

            var harmony = new Harmony(MyPluginInfo.PLUGIN_GUID);
            Patches.Init(harmony);

            SafetyController = new SafetyController();
            ModUI = new ModUI();
            KillSwitch = new KillSwitch();

            KillSwitch.OnKillSwitchActivated += () =>
            {
                SafetyController?.Disable();
                Log.LogWarning("KillSwitch activated");
            };

            Log.LogInfo($"{MyPluginInfo.PLUGIN_NAME} loaded successfully");
        }
        catch (System.Exception ex)
        {
            Log.LogError($"Init failed: {ex.Message}");
        }
    }

    /// <summary>
    /// 每帧由 Patches.OnUpdate → OnFrameUpdate 调用
    /// </summary>
    public static void OnFrameUpdate()
    {
        var sc = SafetyController;
        if (sc == null) return;

        sc.Update();

        if (!sc.IsEnabled || !sc.ShouldAct()) return;

        MainLoop.Instance.Tick();
    }

    // ── 模块引用（static 以便 Harmony hook 访问）──
    public static SafetyController SafetyController { get; private set; }
    public static KillSwitch KillSwitch { get; private set; }
    public static ModUI ModUI { get; private set; }

    public override bool Unload()
    {
        Log.LogInfo("MOD unloaded");
        return true;
    }
}
