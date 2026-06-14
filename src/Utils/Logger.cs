namespace MahjongSoulMod.Utils;

/// <summary>
/// 日志工具
/// </summary>
public static class LogWriter
{
    private static BepInEx.Logging.ManualLogSource _logger;

    public static void Init(BepInEx.Logging.ManualLogSource logger)
    {
        _logger = logger;
    }

    public static void Info(string msg) => _logger?.LogInfo(msg);
    public static void Warning(string msg) => _logger?.LogWarning(msg);
    public static void Error(string msg) => _logger?.LogError(msg);
    public static void Debug(string msg) => _logger?.LogDebug(msg);
}
