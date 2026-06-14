using System;

namespace MahjongSoulMod.StateReconstruction;

/// <summary>
/// Layer 2: 牌定义
/// 34种牌的一维编码 + 结构化表示
/// </summary>
public readonly struct Tile : IEquatable<Tile>
{
    // ── 34种牌编码 ──
    // 0-8:   一万~九万
    // 9-17:  一筒~九筒
    // 18-26: 一索~九索
    // 27-33: 东南西北白发中

    public readonly int Id;      // 0-33, 34种牌的唯一ID
    public readonly bool IsRed;  // 是否赤5

    public Tile(int id, bool isRed = false)
    {
        if (id < 0 || id > 33)
            throw new ArgumentOutOfRangeException(nameof(id), "Tile ID must be 0-33");
        Id = id;
        IsRed = isRed;
    }

    // ── 花色/数值拆解 ──
    public int Suit => Id / 9;          // 0=万, 1=筒, 2=索, 3=字
    public int Value => Id % 9 + 1;     // 万/筒/索: 1-9; 字牌: 1-7
    public bool IsHonor => Suit == 3;
    public bool IsTerminal => !IsHonor && Value is 1 or 9;
    public bool IsYaochu => IsHonor || IsTerminal;  // 幺九牌
    public bool IsMiddle => !IsYaochu;              // 中张牌

    // ── 字牌子类别 ──
    public bool IsWind => IsHonor && Value <= 4;    // 东南西北
    public bool IsDragon => IsHonor && Value >= 5;  // 白发中

    // ── 内置常量 ──
    public static readonly int TileTypeCount = 34;
    public static readonly int MaxCountPerTile = 4;

    // ── 工厂方法 ──
    public static Tile Of(int suit, int value, bool isRed = false)
    {
        return new Tile(suit * 9 + (value - 1), isRed);
    }

    public static Tile Man(int v, bool red = false) => Of(0, v, red);
    public static Tile Pin(int v, bool red = false) => Of(1, v, red);
    public static Tile Sou(int v, bool red = false) => Of(2, v, red);
    public static Tile Ton() => new(27);
    public static Tile Nan() => new(28);
    public static Tile Sha() => new(29);
    public static Tile Pei() => new(30);
    public static Tile Haku() => new(31);
    public static Tile Hatsu() => new(32);
    public static Tile Chun() => new(33);

    // ── 工具 ──
    public bool Equals(Tile other) => Id == other.Id && IsRed == other.IsRed;
    public override bool Equals(object obj) => obj is Tile other && Equals(other);
    public override int GetHashCode() => HashCode.Combine(Id, IsRed);
    public override string ToString() => $"{(Suit switch { 0 => "M", 1 => "P", 2 => "S", _ => "Z" })}{Value}{(IsRed ? "*" : "")}";

    public static bool operator ==(Tile a, Tile b) => a.Equals(b);
    public static bool operator !=(Tile a, Tile b) => !a.Equals(b);
}
