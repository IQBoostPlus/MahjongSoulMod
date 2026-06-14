using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text.RegularExpressions;
using UnityEngine;

namespace MahjongSoulMod.DataLayer;

/// <summary>
/// Layer 1A: Unity 对象查找器
/// 游戏架构: ToLua + CUI 框架
///
/// 注意: IL2CPP 下 Resources.FindObjectsOfTypeAll(System.Type) 签名不匹配，
/// 必须使用反射调用或 GameObject.Find(string) 替代。
/// </summary>
public class UnityObjectFinder
{
    private object _cachedLuaClient;

    /// <summary>
    /// 查找 LuaClient 单例
    /// </summary>
    public bool TryFindGameEngine(out object engineObj)
    {
        engineObj = _cachedLuaClient;
        if (engineObj != null) return true;

        try
        {
            var lcType = FindType("LuaClient");
            if (lcType == null) return false;

            var instProp = lcType.GetProperty("Instance",
                BindingFlags.Public | BindingFlags.Static);
            if (instProp != null)
            {
                engineObj = instProp.GetValue(null);
                _cachedLuaClient = engineObj;
                return engineObj != null;
            }

            return false;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// 从场景中读取手牌
    /// </summary>
    public TileData[] ReadHandTiles(object _)
    {
        var result = new List<TileData>();

        try
        {
            // 通过 GameObject.Find 按名字查找手牌对象
            var handRoot = GameObject.Find("HandRoot") ??
                           GameObject.Find("HandPanel") ??
                           GameObject.Find("Tehai");
            if (handRoot != null)
                CollectTilesFromChildren(handRoot.transform, result);

            // 如果没找到，尝试通过命名约定扫描
            if (result.Count == 0)
            {
                for (int i = 0; i < 14; i++)
                {
                    var pai = GameObject.Find($"Pai_{i}") ??
                              GameObject.Find($"Tile_{i}") ??
                              GameObject.Find($"handPai_{i}");
                    if (pai != null)
                    {
                        var tile = ParseTileFromName(pai.name);
                        if (tile.HasValue)
                            result.Add(tile.Value);
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Utils.LogWriter.Warning($"[UOF] ReadHandTiles: {ex.Message}");
        }

        return result.ToArray();
    }

    public TileData[][] ReadAllDiscards(object _)
    {
        var discards = new[] { new List<TileData>(), new List<TileData>(),
                               new List<TileData>(), new List<TileData>() };

        try
        {
            for (int p = 0; p < 4; p++)
            {
                var area = GameObject.Find($"DiscardArea_{p}")
                    ?? GameObject.Find($"Kawa_{p}")
                    ?? GameObject.Find($"Sutehai_{p}");
                if (area != null)
                    CollectTilesFromChildren(area.transform, discards[p]);
            }
        }
        catch { }

        return new[] {
            discards[0].ToArray(), discards[1].ToArray(),
            discards[2].ToArray(), discards[3].ToArray()
        };
    }

    public MeldData[][] ReadAllMelds(object _)
    {
        var all = new[] { new List<MeldData>(), new List<MeldData>(),
                          new List<MeldData>(), new List<MeldData>() };
        return new[] { all[0].ToArray(), all[1].ToArray(), all[2].ToArray(), all[3].ToArray() };
    }

    public TileData[] ReadDoraIndicators(object _)
    {
        var result = new List<TileData>();
        try
        {
            var doraRoot = GameObject.Find("DoraIndicator")
                ?? GameObject.Find("DoraPanel");
            if (doraRoot != null)
                CollectTilesFromChildren(doraRoot.transform, result);
        }
        catch { }
        return result.ToArray();
    }

    public bool TryAnalyzeScene(out int roundWind, out int selfSeat,
        out int[] scores)
    {
        roundWind = 0;
        selfSeat = 0;
        scores = new[] { 25000, 25000, 25000, 25000 };

        try
        {
            if (TryFindGameEngine(out var engine))
            {
                roundWind = ReadRoundWind(engine);
                selfSeat = ReadSelfSeat(engine);
                scores = ReadScores(engine);
            }

            for (int i = 0; i < 4; i++)
            {
                var scoreText = GameObject.Find($"ScoreText_{i}")
                    ?? GameObject.Find($"Player{i}_Score");
                if (scoreText != null)
                {
                    var textComp = scoreText.GetComponent<UnityEngine.UI.Text>();
                    if (textComp != null)
                    {
                        var text = textComp.text;
                        if (int.TryParse(text, out int val))
                            scores[i] = val * 100;
                    }
                }
            }
            return true;
        }
        catch
        {
            return false;
        }
    }

    public int ReadRoundWind(object _) => 0;
    public int ReadSelfSeat(object _) => 0;
    public int ReadHonba(object _) => 0;
    public int[] ReadDeposits(object _) => [];
    public int[] ReadScores(object _) => [25000, 25000, 25000, 25000];
    public TileData ReadUraDoraIndicator(object _) => default;
    public int ReadCurrentTurn(object _) => 0;
    public int ReadRemainingTiles(object _) => 0;
    public int ReadLastAction(object _) => 0;
    public TileData ReadLastActionTile(object _) => default;

    // ── 辅助方法 ──

    private static Type FindType(string name)
    {
        try
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var t = asm.GetType(name, false);
                if (t != null) return t;
            }
        }
        catch { }
        return null;
    }

    private static GameObject GetGameObject(object component)
    {
        try
        {
            var prop = component.GetType().GetProperty("gameObject");
            return prop?.GetValue(component) as GameObject;
        }
        catch { return null; }
    }

    private static void CollectTilesFromChildren(Transform parent,
        List<TileData> result)
    {
        if (parent == null) return;
        for (int i = 0; i < parent.childCount; i++)
        {
            var child = parent.GetChild(i);
            if (child == null) continue;
            var go = child.gameObject;
            if (go == null) continue;
            var tile = ParseTileFromName(go.name);
            if (tile.HasValue)
                result.Add(tile.Value);
            CollectTilesFromChildren(child, result);
        }
    }

    internal static TileData? ParseTileFromName(string name)
    {
        if (string.IsNullOrEmpty(name)) return null;
        var cleaned = name.ToLowerInvariant();
        var m = Regex.Match(cleaned,
            @"(?:tile_|pai_|img_)?(\d{1,2})([mpsz])(r?)");
        if (!m.Success) return null;

        int num = int.Parse(m.Groups[1].Value);
        string suitChar = m.Groups[2].Value;
        bool isRed = m.Groups[3].Value == "r";
        int suit = suitChar switch { "m" => 0, "p" => 1, "s" => 2, "z" => 3, _ => -1 };
        if (suit < 0 || num < 1 || num > 9) return null;
        if (suit == 3 && num > 7) return null;

        return new TileData { Suit = suit, Value = num, IsRedFive = isRed, IsDora = false };
    }
}

/// <summary>
/// 场景诊断工具 — 运行时使用反射输出场景层次
/// </summary>
internal class SceneDumper
{
    public void DumpHierarchy()
    {
    }
}
