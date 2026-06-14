using HarmonyLib;
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;

namespace MahjongSoulMod;

public static class Patches
{
    private static Harmony _harmony;
    private static bool _patched;
    private static bool _sceneDumped;
    private static int _frameCount;
    private static System.Threading.Timer? _timer;

    public static void Init(Harmony harmony)
    {
        _harmony = harmony;
        Utils.LogWriter.Info("Starting patch retry timer...");

        _timer = new System.Threading.Timer(_ =>
        {
            if (_patched) return;
            TryLoadInteropAssembly();
        }, null, 1000, 2000);
    }

    private static void TryLoadInteropAssembly()
    {
        try
        {
            var modLocation = Assembly.GetExecutingAssembly().Location;
            if (string.IsNullOrEmpty(modLocation)) return;

            var interopDir = Path.Combine(
                modLocation.Replace("plugins", "interop")
                    .Replace("MahjongSoulMod.dll", ""),
                "Assembly-CSharp.dll");

            if (!File.Exists(interopDir)) return;

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
            Utils.LogWriter.Info("Patched LuaLooper.Update() — main loop active");
            _patched = true;

            _timer?.Dispose();
            _timer = null;
        }
        catch (Exception ex)
        {
            Utils.LogWriter.Warning($"Patch attempt failed: {ex.GetType().Name}");
        }
    }

    public static void OnUpdate()
    {
        _frameCount++;

        if (!_sceneDumped)
        {
            _sceneDumped = true;
            DumpViaGameObjectFind();
        }

        if (_frameCount % 6 == 0)
            MainPlugin.OnFrameUpdate();
    }

    private static void DumpViaGameObjectFind()
    {
        Utils.LogWriter.Info("=== Scene dump via GameObject.Find ===");

        string[] candidates = [
            "Root_UI", "GameRoot", "UIRoot", "uiroot", "Canvas",
            "HandRoot", "HandPanel", "Tehai", "hand_panel",
            "Game", "table", "Table", "MahjongTable",
            "Kawa_0", "Kawa_1", "Kawa_2", "Kawa_3",
            "DiscardArea_0", "DiscardArea_1",
            "Dora", "DoraPanel", "DoraIndicator",
            "Score", "ScorePanel",
            "Player0", "Player1", "Player2", "Player3",
            "BtnPon", "BtnChi", "BtnKan", "BtnRiichi", "BtnPass", "BtnRon",
            "GameEngine", "LuaClient", "LuaLooper",
        ];

        foreach (var name in candidates)
        {
            var go = GameObject.Find(name);
            if (go != null)
            {
                string parent = "(root)";
                try { parent = go.transform.parent?.gameObject.name ?? "(root)"; } catch { }
                Utils.LogWriter.Info($"  FOUND: [{parent}] {name} (active={go.activeInHierarchy})");
            }
        }

        Utils.LogWriter.Info("=== End ===");
    }
}
