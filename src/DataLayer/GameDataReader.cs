using System;
using System.Collections.Generic;

namespace MahjongSoulMod.DataLayer;

/// <summary>
/// Layer 1A: 游戏数据读取器
/// 从 Unity 场景中提取牌局原始数据，构建 GameStateSnapshot
/// </summary>
public class GameDataReader
{
    private UnityObjectFinder _objectFinder;

    public GameDataReader()
    {
        _objectFinder = new UnityObjectFinder();
    }

    /// <summary>
    /// 尝试读取完整牌局状态
    /// </summary>
    public bool TryReadSnapshot(out GameStateSnapshot snapshot)
    {
        snapshot = default;

        try
        {
            if (!_objectFinder.TryFindGameEngine(out var engine))
            {
                _objectFinder.TryAnalyzeScene(
                    out int roundWind, out int selfSeat, out int[] scores);
                snapshot.RoundWind = roundWind;
                snapshot.SelfSeat = selfSeat;
                snapshot.Scores = scores;
            }

            snapshot.HandTiles = _objectFinder.ReadHandTiles(engine);
            snapshot.Discards = _objectFinder.ReadAllDiscards(engine);
            snapshot.Melds = _objectFinder.ReadAllMelds(engine);
            snapshot.DoraIndicators = _objectFinder.ReadDoraIndicators(engine);

            if (engine != null)
            {
                snapshot.RoundWind = _objectFinder.ReadRoundWind(engine);
                snapshot.SelfSeat = _objectFinder.ReadSelfSeat(engine);
                snapshot.Honba = _objectFinder.ReadHonba(engine);
                snapshot.Scores = _objectFinder.ReadScores(engine);
            }

            return true;
        }
        catch (Exception ex)
        {
            Utils.LogWriter.Error($"[GameDataReader] Read failed: {ex.Message}");
            return false;
        }
    }
}

/// <summary>
/// 牌局状态快照 — 数据读取层输出的核心数据结构
/// </summary>
public struct GameStateSnapshot
{
    public int RoundWind;               // 场风 (0=东, 1=南, 2=西, 3=北)
    public int SelfSeat;                // 自风 (0=东, 1=南, 2=西, 3=北)
    public int Honba;                   // 本场数
    public int[] Deposits;              // 供托数 (立直棒)
    public int[] Scores;                // 四位玩家点数

    public TileData[] HandTiles;        // 自家手牌
    public TileData[][] Discards;       // 四位玩家的舍牌
    public MeldData[][] Melds;          // 四位玩家的副露
    public TileData[] DoraIndicators;   // 宝牌指示牌
    public TileData UraDoraIndicator;   // 里宝牌指示牌
    public int SelfTurn;                // 当前轮到谁 (0-3)
    public int RemainingTiles;          // 牌山剩余枚数
    public int LastAction;              // 上次动作类型
    public TileData LastActionTile;     // 上次动作关联牌
}

/// <summary>
/// 原始牌数据
/// </summary>
public struct TileData
{
    public int Suit;        // 花色: 0=万, 1=筒, 2=索, 3=字
    public int Value;       // 数值: 1-9 (字牌: 1-7对应东南西北白发中)
    public bool IsRedFive;  // 是否赤5
    public bool IsDora;     // 是否宝牌
}

/// <summary>
/// 副露数据
/// </summary>
public struct MeldData
{
    public MeldType Type;
    public TileData[] Tiles;
    public int CalledFrom;
}

public enum MeldType
{
    Chi, Pon, Kan, AnKan
}
