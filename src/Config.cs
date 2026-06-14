using BepInEx.Configuration;

namespace MahjongSoulMod.Config;

/// <summary>
/// Layer 6: MOD 全局配置
/// </summary>
public static class ModConfig
{
    // ── 功能开关 ──
    public static ConfigEntry<bool> Enabled { get; private set; }
    public static ConfigEntry<bool> AutoDiscard { get; private set; }
    public static ConfigEntry<bool> AutoCall { get; private set; }
    public static ConfigEntry<bool> AutoRiichi { get; private set; }
    public static ConfigEntry<bool> AutoAgari { get; private set; }

    // ── 策略参数 ──
    public static ConfigEntry<int> AggressionLevel { get; private set; }
    public static ConfigEntry<int> SpeedPreference { get; private set; }
    public static ConfigEntry<int> RiskTolerance { get; private set; }

    // ── 安全与拟人化 ──
    public static ConfigEntry<bool> SafetyMode { get; private set; }
    public static ConfigEntry<int> MinDelayMs { get; private set; }
    public static ConfigEntry<int> MaxDelayMs { get; private set; }

    // ── 快捷键 ──
    public static ConfigEntry<string> ToggleKey { get; private set; }
    public static ConfigEntry<string> KillSwitchKey { get; private set; }

    public static void Bind(ConfigFile config)
    {
        const string sectionGeneral = "General";
        const string sectionStrategy = "Strategy";
        const string sectionSafety = "Safety";
        const string sectionHotkey = "Hotkeys";

        Enabled = config.Bind(sectionGeneral, "Enabled", true, "总开关");
        AutoDiscard = config.Bind(sectionGeneral, "AutoDiscard", true, "自动切牌");
        AutoCall = config.Bind(sectionGeneral, "AutoCall", true, "自动鸣牌（吃/碰/杠）");
        AutoRiichi = config.Bind(sectionGeneral, "AutoRiichi", true, "自动立直");
        AutoAgari = config.Bind(sectionGeneral, "AutoAgari", true, "自动和牌");

        AggressionLevel = config.Bind(sectionStrategy, "Aggression", 3,
            new ConfigDescription("攻击性 (1=保守, 5=激进)", new AcceptableValueRange<int>(1, 5)));
        SpeedPreference = config.Bind(sectionStrategy, "Speed", 3,
            new ConfigDescription("速度偏好 (1=打点优先, 5=速度优先)", new AcceptableValueRange<int>(1, 5)));
        RiskTolerance = config.Bind(sectionStrategy, "RiskTolerance", 3,
            new ConfigDescription("风险容忍度 (1=安全至上, 5=高风险高回报)", new AcceptableValueRange<int>(1, 5)));

        SafetyMode = config.Bind(sectionSafety, "SafetyMode", true, "安全模式（更拟人化）");
        MinDelayMs = config.Bind(sectionSafety, "MinDelay", 300,
            new ConfigDescription("最小动作延迟 (ms)", new AcceptableValueRange<int>(50, 5000)));
        MaxDelayMs = config.Bind(sectionSafety, "MaxDelay", 1500,
            new ConfigDescription("最大动作延迟 (ms)", new AcceptableValueRange<int>(100, 10000)));

        ToggleKey = config.Bind(sectionHotkey, "ToggleKey", "F6", "切换自动模式快捷键");
        KillSwitchKey = config.Bind(sectionHotkey, "KillSwitchKey", "F7", "紧急停止快捷键");
    }
}
