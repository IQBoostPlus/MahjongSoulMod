using MahjongSoulMod.AI;
using MahjongSoulMod.StateReconstruction;

namespace MahjongSoulMod.Tests;

/// <summary>
/// 向听数计算器单元测试
/// </summary>
public class ShantenCalculatorTests
{
    private static Tile[] Hand(params string[] tileStrs)
    {
        return tileStrs.Select(ParseTile).ToArray();
    }

    private static Tile ParseTile(string s)
    {
        s = s.Trim().ToLower();
        int num = int.Parse(s[..^1]);
        char suit = s[^1];
        int id = suit switch
        {
            'm' => num - 1,
            'p' => 9 + num - 1,
            's' => 18 + num - 1,
            'z' => 27 + num - 1,
            _ => throw new ArgumentException($"Invalid suit: {suit}")
        };
        return new Tile(id, false);
    }

    /// <summary>
    /// 九莲宝灯: 1112345678999 = 13枚, 听牌
    /// </summary>
    [Fact]
    public void NineGate_13Tiles_IsTenpai()
    {
        var hand = Hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","9m","9m","9m");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(0, shanten);
    }

    /// <summary>
    /// 九莲宝灯 + 任意万子 = 14枚 = 完成
    /// </summary>
    [Fact]
    public void NineGate_14Tiles_IsCompleted()
    {
        var hand = Hand("1m","1m","1m","2m","3m","4m","5m","6m","7m","8m","8m","9m","9m","9m");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(-1, shanten);
    }

    /// <summary>
    /// 国士无双: 13面听 (13枚)
    /// </summary>
    [Fact]
    public void KokushiMusou_13Tiles_IsTenpai()
    {
        var hand = Hand(
            "1m","9m","1p","9p","1s","9s",
            "1z","2z","3z","4z","5z","6z","7z");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(0, shanten);
    }

    /// <summary>
    /// 国士无双: 14枚完成 (13种幺九 + 1种重复)
    /// </summary>
    [Fact]
    public void KokushiMusou_Completed()
    {
        var hand = Hand(
            "1m","9m","1p","9p","1s","9s",
            "1z","2z","3z","4z","5z","6z","7z",
            "1m");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(-1, shanten);
    }

    /// <summary>
    /// 国士无双: 1向听 (缺2种幺九牌, 13枚)
    /// </summary>
    [Fact]
    public void KokushiMusou_1Shanten()
    {
        var hand = Hand(
            "1m","9m","1p","9p","1s","9s",
            "1z","2z","3z","4z","5z","6z");
        // 缺 7z 和任意一对 = 缺2种幺九, 1向听
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(1, shanten);
    }

    /// <summary>
    /// 七对子: 听牌 (6对 + 1单张 = 13枚)
    /// </summary>
    [Fact]
    public void Chiitoi_13Tiles_Tenpai()
    {
        var hand = Hand(
            "1m","1m","3p","3p","5s","5s",
            "2z","2z","4z","4z","6z","6z",
            "8p");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(0, shanten);
    }

    /// <summary>
    /// 七对子: 听牌 (6对 + 2单张 = 14枚)
    /// </summary>
    [Fact]
    public void Chiitoi_14Tiles_Tenpai()
    {
        var hand = Hand(
            "1m","1m","3p","3p","5s","5s",
            "2z","2z","4z","4z","6m","6m",
            "8p","9p");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(0, shanten);
    }

    /// <summary>
    /// 标准手: 两面听牌
    /// 23m + 567p + 999s + 111z + 22z = 13枚，听 1m/4m
    /// </summary>
    [Fact]
    public void RyanmenTenpai_13Tiles()
    {
        var hand = Hand(
            "2m","3m",
            "5p","6p","7p",
            "9s","9s","9s",
            "1z","1z","1z",
            "2z","2z");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(0, shanten);
    }

    /// <summary>
    /// 完成的手: 123m 456m 789m 111p 22p
    /// </summary>
    [Fact]
    public void CompleteHand_IsAgari()
    {
        var hand = Hand(
            "1m","2m","3m",
            "4m","5m","6m",
            "7m","8m","9m",
            "1p","1p","1p",
            "2p","2p");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(-1, shanten);
    }

    /// <summary>
    /// 1向听: 13m(坎张) + 567p(顺子) + 999s(刻子) + 22z(对) + 44z(对) + 6p7p(搭)
    /// </summary>
    [Fact]
    public void Kanchan_1Shanten()
    {
        var hand = Hand(
            "1m","3m",
            "5p","6p","7p",
            "9s","9s","9s",
            "2z","2z",
            "4z","4z",
            "6p","7p");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.Equal(1, shanten);
    }

    /// <summary>
    /// 字牌乱手
    /// </summary>
    [Fact]
    public void AllHonors_1Or2Shanten()
    {
        var hand = Hand(
            "1z","1z","2z","2z","3z","3z",
            "4z","5z","5z","6z","6z","7z","7z","7z");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.True(shanten <= 2);
    }

    /// <summary>
    /// 散乱手牌: 高向听
    /// </summary>
    [Fact]
    public void RandomHand_HighShanten()
    {
        var hand = Hand(
            "1m","3m","5m","7m","9m",
            "2p","4p","6p","8p",
            "1s","3s","5s","7s","9s");
        int shanten = ShantenCalculator.Calculate(hand);
        Assert.True(shanten >= 3);
    }
}
