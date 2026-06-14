using HarmonyLib;
using System;
using System.IO;
using System.Reflection;

namespace MahjongSoulMod;

/// <summary>
/// Harmony 补丁集 — 手动加载 IL2CPP interop 程序集并应用补丁
/// </summary>
public static class Patches
{
    private static Harmony _harmony;
    private static bool _patched;

    public static void Init(Harmony harmony)
    {
        _harmony = harmony;
        Utils.LogWriter.Info("Starting patch retry timer...");

        var timer = new System.Threading.Timer(_ =>
        {
            if (_patched) return;
            TryLoadInteropAssembly();
        }, null, 1000, 2000);
    }

    private static void TryLoadInteropAssembly()
    {
        try
        {
            var interopDir = Path.Combine(
                Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)
                    ?.Replace("plugins", "interop")
                    ?? @"D:\Steam\steamapps\common\MahjongSoul\BepInEx\interop",
                "Assembly-CSharp.dll");

            if (!File.Exists(interopDir))
            {
                Utils.LogWriter.Warning($"Interop DLL not found: {interopDir}");
                return;
            }

            var asm = Assembly.LoadFrom(interopDir);
            var luaLooperType = asm.GetType("LuaLooper");
            if (luaLooperType == null) return;

            Utils.LogWriter.Info($"Found LuaLooper in {asm.GetName().Name}");

            var updateMethod = luaLooperType.GetMethod("Update",
                BindingFlags.Public | BindingFlags.NonPublic |
                BindingFlags.Instance | BindingFlags.Static);

            if (updateMethod == null) return;

            var postfix = typeof(Patches).GetMethod(nameof(OnUpdate),
                BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);

            _harmony.Patch(updateMethod, postfix: new HarmonyMethod(postfix));
            Utils.LogWriter.Info("Patched LuaLooper.Update()");
            _patched = true;
        }
        catch (Exception ex)
        {
            Utils.LogWriter.Warning($"Attempt failed: {ex.GetType().Name}");
        }
    }

    private static int _frameCount;

    /// <summary>
    /// LuaLooper.Update postfix — 每帧调用
    /// </summary>
    public static void OnUpdate()
    {
        _frameCount++;
        if (_frameCount == 1)
            Utils.LogWriter.Info("OnUpdate called! Frame loop is working.");

        // MainPlugin.OnFrameUpdate(); // Temporarily disabled to isolate the error
    }
}
