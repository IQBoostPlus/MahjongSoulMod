using System;
using System.Collections.Generic;
using System.Linq;
using MahjongSoulMod.DataLayer;

namespace MahjongSoulMod.StateReconstruction;

/// <summary>
/// Layer 2: 牌局状态
/// 将原始 GameStateSnapshot 转换为结构化的麻将逻辑状态
/// </summary>
public class GameState
{
    // ── 局况 ──
    public int RoundWind { get; private set; }
    public int SelfSeat { get; private set; }
    public int Honba { get; private set; }
    public int[] Deposits { get; private set; }
    public int[] Scores { get; private set; }

    // ── 手牌与牌局 ──
    public Tile[] Hand { get; private set; }
    public List<Tile>[] Discards { get; private set; }
    public List<Meld>[] Melds { get; private set; }
    public Tile[] DoraIndicators { get; private set; }
    public int SelfTurn { get; private set; }
    public int RemainingTiles { get; private set; }

    // ── 已知牌信息 ──
    private int[] _tileCount = new int[Tile.TileTypeCount];

    public int[] TileCount => _tileCount;

    private GameState() { }

    /// <summary>
    /// 从原始快照构建牌局状态
    /// </summary>
    public static GameState? FromSnapshot(GameStateSnapshot raw)
    {
        var state = new GameState();

        try
        {
            state.RoundWind = raw.RoundWind;
            state.SelfSeat = raw.SelfSeat;
            state.Honba = raw.Honba;
            state.Deposits = raw.Deposits ?? [];
            state.Scores = raw.Scores ?? [25000, 25000, 25000, 25000];
            state.SelfTurn = raw.SelfTurn;
            state.RemainingTiles = raw.RemainingTiles;

            state.Hand = raw.HandTiles?.Select(FromTileData).ToArray() ?? [];
            state.Discards = raw.Discards?.Select(d => d?.Select(FromTileData).ToList() ?? []).ToArray() ?? [];
            state.Melds = raw.Melds?.Select(m => m?.Select(FromMeldData).ToList() ?? []).ToArray() ?? [];
            state.DoraIndicators = raw.DoraIndicators?.Select(FromTileData).ToArray() ?? [];

            state._tileCount = new int[Tile.TileTypeCount];
            state.RecomputeTileCount();

            return state;
        }
        catch (Exception ex)
        {
            Utils.LogWriter.Error($"[GameState] Build failed: {ex.Message}");
            return null;
        }
    }

    /// <summary>
    /// 重新计算已见过的所有牌
    /// </summary>
    public void RecomputeTileCount()
    {
        // 重置
        Array.Clear(_tileCount, 0, _tileCount.Length);

        // 手牌
        foreach (var t in Hand)
            if (t.Id >= 0 && t.Id < Tile.TileTypeCount) _tileCount[t.Id]++;

        // 舍牌
        if (Discards != null)
            foreach (var list in Discards)
                if (list != null)
                    foreach (var t in list)
                        if (t.Id >= 0) _tileCount[t.Id]++;

        // 副露
        if (Melds != null)
            foreach (var list in Melds)
                if (list != null)
                    foreach (var m in list)
                        foreach (var t in m.Tiles)
                            if (t.Id >= 0) _tileCount[t.Id]++;

        // 宝牌指示牌
        if (DoraIndicators != null)
            foreach (var t in DoraIndicators)
                if (t.Id >= 0) _tileCount[t.Id]++;
    }

    /// <summary>
    /// 获取某张牌的剩余枚数
    /// </summary>
    public int GetRemaining(Tile tile) => Tile.MaxCountPerTile - _tileCount[tile.Id];

    /// <summary>
    /// 获取所有剩余牌的列表（用于不确定计算）
    /// </summary>
    public IEnumerable<Tile> GetRemainingTiles()
    {
        for (int id = 0; id < Tile.TileTypeCount; id++)
        {
            int remaining = Tile.MaxCountPerTile - _tileCount[id];
            for (int i = 0; i < remaining; i++)
                yield return new Tile(id);
        }
    }

    /// <summary>
    /// 验证状态是否合法（宽松版 — 空手牌也允许以支持场景发现阶段）
    /// </summary>
    public bool Validate()
    {
        // 手牌数验证 (0 手牌 = 还没读取到数据，不算非法)
        if (Hand.Length > 14) return false;

        // 枚数验证
        for (int i = 0; i < Tile.TileTypeCount; i++)
            if (_tileCount[i] > Tile.MaxCountPerTile)
                return false;

        return true;
    }

    private static Tile FromTileData(TileData d) => new(d.Suit * 9 + d.Value - 1, d.IsRedFive);
    private static Meld FromMeldData(MeldData d) => new(d.Tiles.Select(FromTileData).ToArray(), (StateReconstruction.MeldType)d.Type);
}

/// <summary>
/// 副露
/// </summary>
public class Meld
{
    public Tile[] Tiles { get; }
    public MeldType Type { get; }

    public Meld(Tile[] tiles, MeldType type)
    {
        Tiles = tiles;
        Type = type;
    }
}

public enum MeldType
{
    Chi, Pon, Kan, AnKan
}
