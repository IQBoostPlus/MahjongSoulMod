using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text.RegularExpressions;
using UnityEngine;

namespace MahjongSoulMod.DataLayer;

/// <summary>
/// Layer 1A: Unity 对象查找器
///
/// 通过 GameObject.Find() 按名称定位场景对象。
/// 名称来自 Patches.cs 的首次运行场景 dump。
///
/// IL2CPP 兼容性说明:
/// - Resources.FindObjectsOfTypeAll(System.Type) → ❌ 签名不匹配
/// - GameObject.FindObjectsOfType<T>() → ⚠️ 可能不匹配
/// - GameObject.Find(string) → ✅ 正常工作
/// - Transform 父子遍历 → ✅ 正常工作
/// - GetComponent<T>() → ⚠️ 使用反射调用
/// </summary>
public class UnityObjectFinder
{
    private static object? _cachedEngine;
    private static bool _engineTried;

    public bool TryFindGameEngine(out object? engineObj)
    {
        engineObj = _cachedEngine;
        if (_engineTried) return engineObj != null;

        _engineTried = true;

        try
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (!asm.GetName().Name.Contains("Assembly-CSharp"))
                    continue;

                var type = asm.GetType("GameEngine", false);
                if (type == null) continue;

                var field = type.GetField("Inst",
                    BindingFlags.Public | BindingFlags.Static);
                if (field != null)
                {
                    engineObj = field.GetValue(null);
                    _cachedEngine = engineObj;
                    if (engineObj != null)
                        Utils.LogWriter.Info("[UOF] Found GameEngine.Inst");
                    return engineObj != null;
                }
            }
        }
        catch (Exception ex)
        {
            Utils.LogWriter.Warning($"[UOF] FindGameEngine: {ex.Message}");
        }

        return false;
    }

    public TileData[] ReadHandTiles(object? _)
    {
        var result = new List<TileData>();

        try
        {
            // 尝试已知的手牌面板名称
            var handPanel = GameObject.Find("HandPanel")
                ?? GameObject.Find("hand_panel")
                ?? GameObject.Find("SelfHand")
                ?? GameObject.Find("Tehai")
                ?? GameObject.Find("HandRoot");

            if (handPanel != null)
            {
                CollectTilesFromChildren(handPanel.transform, result);
                if (result.Count > 0)
                    Utils.LogWriter.Info($"[UOF] Read {result.Count} hand tiles from {handPanel.name}");
            }
        }
        catch (Exception ex)
        {
            Utils.LogWriter.Warning($"[UOF] ReadHandTiles: {ex.Message}");
        }

        return result.ToArray();
    }

    public TileData[][] ReadAllDiscards(object? _)
    {
        var d = new[] {
            new List<TileData>(), new List<TileData>(),
            new List<TileData>(), new List<TileData>()
        };

        try
        {
            for (int p = 0; p < 4; p++)
            {
                var area = GameObject.Find($"Kawa_{p}")
                    ?? GameObject.Find($"kawa_{p}")
                    ?? GameObject.Find($"Discard_{p}")
                    ?? GameObject.Find($"discard_{p}");
                if (area != null)
                    CollectTilesFromChildren(area.transform, d[p]);
            }
        }
        catch { }

        return new[] { d[0].ToArray(), d[1].ToArray(), d[2].ToArray(), d[3].ToArray() };
    }

    public MeldData[][] ReadAllMelds(object? _) =>
        new[] { Array.Empty<MeldData>(), Array.Empty<MeldData>(), Array.Empty<MeldData>(), Array.Empty<MeldData>() };

    public TileData[] ReadDoraIndicators(object? _)
    {
        var r = new List<TileData>();
        try
        {
            var root = GameObject.Find("Dora") ?? GameObject.Find("DoraPanel");
            if (root != null) CollectTilesFromChildren(root.transform, r);
        }
        catch { }
        return r.ToArray();
    }

    // 这些值后续通过 Lua 状态读取
    public int ReadRoundWind(object? _) => 0;
    public int ReadSelfSeat(object? _) => 0;
    public int ReadHonba(object? _) => 0;
    public int[] ReadDeposits(object? _) => [];
    public int[] ReadScores(object? _) => [25000, 25000, 25000, 25000];
    public TileData ReadUraDoraIndicator(object? _) => default;
    public int ReadCurrentTurn(object? _) => 0;
    public int ReadRemainingTiles(object? _) => 0;
    public int ReadLastAction(object? _) => 0;
    public TileData ReadLastActionTile(object? _) => default;
    public bool TryAnalyzeScene(out int rw, out int ss, out int[] sc)
    { rw = 0; ss = 0; sc = [25000, 25000, 25000, 25000]; return false; }

    // ── 辅助 ──

    private static void CollectTilesFromChildren(Transform parent, List<TileData> result)
    {
        if (parent == null) return;
        for (int i = 0; i < parent.childCount; i++)
        {
            var child = parent.GetChild(i);
            if (child == null) continue;
            var tile = ParseTileFromName(child.name);
            if (tile.HasValue) result.Add(tile.Value);
            CollectTilesFromChildren(child, result);
        }
    }

    internal static TileData? ParseTileFromName(string name)
    {
        if (string.IsNullOrEmpty(name)) return null;
        var m = Regex.Match(name.ToLowerInvariant(),
            @"(?:tile_|pai_|img_)?(\d{1,2})([mpsz])(r?)");
        if (!m.Success) return null;

        int num = int.Parse(m.Groups[1].Value);
        string s = m.Groups[2].Value;
        bool red = m.Groups[3].Value == "r";
        int suit = s switch { "m" => 0, "p" => 1, "s" => 2, "z" => 3, _ => -1 };
        if (suit < 0 || num < 1 || num > 9 || (suit == 3 && num > 7)) return null;

        return new TileData { Suit = suit, Value = num, IsRedFive = red, IsDora = false };
    }
}
