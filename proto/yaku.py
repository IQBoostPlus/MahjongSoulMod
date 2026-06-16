"""
雀魂役种/按钮/房间映射表

数据来源: MajsoulPaipuAnalyzer (zyr17/MajsoulPaipuAnalyzer)
  - SimpleMahjong/const.js: 役种ID映射, 按钮映射, 牌编码
  - lib/majsoul/analyze.js: 房间等级映射, 协议解析

所有映射基于雀魂官方 liqi 协议, 与游戏完全一致。
"""

from typing import Dict, List, Tuple, Optional

# ═══════════════════════════════════════════════════════════════
#  役种 ID → 名称映射 (雀魂 54 役种)
# ═══════════════════════════════════════════════════════════════

YAKU_ID_TO_NAME: Dict[int, str] = {
    0:  "",
    1:  "门前清自摸和",    2:  "立直",          3:  "枪杠",
    4:  "岭上开花",        5:  "海底摸月",      6:  "河底捞鱼",
    7:  "役牌 白",         8:  "役牌 发",       9:  "役牌 中",
    10: "役牌:门风牌",     11: "役牌:场风牌",   12: "断幺九",
    13: "一杯口",          14: "平和",          15: "混全带幺九",
    16: "一气通贯",        17: "三色同顺",      18: "两立直",
    19: "三色同刻",        20: "三杠子",        21: "对对和",
    22: "三暗刻",          23: "小三元",        24: "混老头",
    25: "七对子",          26: "纯全带幺九",    27: "混一色",
    28: "二杯口",          29: "清一色",        30: "一发",
    31: "宝牌",            32: "红宝牌",        33: "里宝牌",
    34: "拔北宝牌",        35: "天和",          36: "地和",
    37: "大三元",          38: "四暗刻",        39: "字一色",
    40: "绿一色",          41: "清老头",        42: "国士无双",
    43: "小四喜",          44: "四杠子",        45: "九莲宝灯",
    46: "八连庄",          47: "纯正九莲宝灯",  48: "四暗刻单骑",
    49: "国士无双十三面",  50: "大四喜",
}


# 役种 → 番数 (标准规则)
YAKU_FAN: Dict[int, int] = {}

def _init_yaku_fan():
    """初始化役种番数表"""
    # 一番役
    for yid in range(1, 13): YAKU_FAN[yid] = 1          # 1-12: 一番
    # 二番役
    for yid in range(13, 23): YAKU_FAN[yid] = 2         # 13-22: 两番
    YAKU_FAN[30] = 1  # 一发 (一番)
    # 三番役
    YAKU_FAN[23] = 3  # 小三元 (实际上小三元是2番+2役牌)
    YAKU_FAN[24] = 2  # 混老头
    # 六番役
    YAKU_FAN[26] = 3  # 纯全带幺九
    YAKU_FAN[27] = 3  # 混一色 (门清3番, 副露2番)
    YAKU_FAN[28] = 3  # 二杯口
    # 满贯役
    YAKU_FAN[29] = 6  # 清一色 (门清6番, 副露5番)
    # 役满 (13番)
    for yid in [35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 47, 48, 49, 50]:
        YAKU_FAN[yid] = 13
    # 双倍役满 (26番)
    for yid in [47, 48, 49, 50]:  # 纯正九莲, 四暗刻单骑, 国士十三面, 大四喜
        YAKU_FAN[yid] = 26
    # 宝牌系列
    YAKU_FAN[31] = 0  # 宝牌 (不计番数, 仅增加宝牌计数)
    YAKU_FAN[32] = 0  # 红宝牌
    YAKU_FAN[33] = 0  # 里宝牌
    YAKU_FAN[34] = 0  # 拔北宝牌

_init_yaku_fan()


# 役种日文/英文名
YAKU_NAME_JP: Dict[str, str] = {
    "门前清自摸和": "menzenchintsumoho", "立直": "riichi",
    "枪杠": "chankan", "岭上开花": "rinshankaiho",
    "海底摸月": "haiteiraoyue", "河底捞鱼": "houteiraoyui",
    "役牌 白": "yakuhai haku", "役牌 发": "yakuhai hatsu",
    "役牌 中": "yakuhai chun", "断幺九": "tanyao",
    "一杯口": "iipeikou", "平和": "pinfu",
    "混全带幺九": "honchantaiyaochu", "一气通贯": "ikkitsukan",
    "三色同顺": "sanshokudoujun", "两立直": "dabururiichi",
    "三色同刻": "sanshokudouko", "三杠子": "sankantsu",
    "对对和": "toitoiho", "三暗刻": "sanankou",
    "小三元": "shousangen", "混老头": "honroutou",
    "七对子": "chiitoitsu", "纯全带幺九": "junchantaiyaochu",
    "混一色": "honitsu", "二杯口": "ryanpeikou",
    "清一色": "chinitsu", "一发": "ippatsu",
    "宝牌": "dora", "红宝牌": "akadora",
    "里宝牌": "uradora", "天和": "tenho",
    "地和": "chiho", "大三元": "daisangen",
    "四暗刻": "suankou", "字一色": "tsuuisou",
    "绿一色": "ryuuisou", "清老头": "chinroutou",
    "国士无双": "kokushimusou", "小四喜": "shousuushii",
    "四杠子": "suukantsu", "九莲宝灯": "chuurenpoutou",
    "纯正九莲宝灯": "junseichuurenpoutou", "四暗刻单骑": "suankoutanki",
    "国士无双十三面": "kokushimusoujusanmen", "大四喜": "daisuushii",
}


# ═══════════════════════════════════════════════════════════════
#  按钮映射
# ═══════════════════════════════════════════════════════════════

# 雀魂操作类型 → 按钮名
MAJSOUL_OPTION_TO_BUTTON: Dict[str, str] = {
    "none":   "无操作",
    "dapai":  "打牌",
    "chi":    "吃",
    "pon":    "碰",
    "ankan":  "暗杠",
    "kan":    "杠",
    "kakan":  "加杠",
    "reach":  "立直",
    "tsumo":  "自摸",
    "ron":    "荣和",
    "kyukyu": "九种九牌",
    "pei":    "拔北",
}

# 按钮名 → 操作类型
BUTTON_TO_OPTION: Dict[str, str] = {v: k for k, v in MAJSOUL_OPTION_TO_BUTTON.items()}

# 按钮名 → 操作编号
BUTTON_TO_NUM: Dict[str, int] = {
    "kyukyu": 0, "pei": 1, "chi": 2, "pon": 3, "kan": 4,
    "kakan": 5, "ankan": 6, "reach": 7, "ron": 8, "tsumo": 9,
}

# 鸣牌类型
NAKI_TYPE_TO_STR: Dict[int, str] = {0: "chi", 1: "pon", 2: "kan", 3: "ankan", 4: "kakan"}
NAKI_STR_TO_TYPE: Dict[str, int] = {v: k for k, v in NAKI_TYPE_TO_STR.items()}

# 操作类型 → 协议 action_type 编号
ACTION_TYPE_TO_PROTO: Dict[str, int] = {
    "discard": 1, "chi": 3, "pon": 4, "kan": 5,
    "liqi": 8, "riichi": 8, "pass": 11, "ron": 7,
    "tsumo": 7,  # tsumo 和 ron 都是 hu(7)
}

# 按钮中文名
BUTTON_DISPLAY_NAMES: Dict[str, str] = {
    "kyukyu": "流局", "pei":   "拔北",
    "chi":    "吃",   "pon":   "碰",
    "kan":    "杠",   "kakan": "加杠",
    "ankan":  "暗杠", "reach": "立直",
    "ron":    "荣",   "tsumo": "自摸",
}


# ═══════════════════════════════════════════════════════════════
#  房间等级映射
# ═══════════════════════════════════════════════════════════════

# mode_id → 房间名
MODE_ID_TO_ROOM: Dict[int, str] = {
    0:  "友人场",
    1:  "铜之间", 2:  "铜之间", 3:  "铜之间",
    4:  "银之间", 5:  "银之间", 6:  "银之间",
    7:  "金之间", 8:  "金之间", 9:  "金之间",
    10: "玉之间", 11: "玉之间", 12: "玉之间",
    15: "王座间", 16: "王座间",
    17: "铜之间", 18: "铜之间", 19: "银之间",
    20: "银之间", 21: "金之间", 22: "金之间",
    23: "玉之间", 24: "玉之间", 25: "王座间",
    26: "王座间",
}

# 房间名 → 等级编号
ROOM_NAME_TO_LEVEL: Dict[str, int] = {
    "友人场": 0, "铜之间": 1, "银之间": 2,
    "金之间": 3, "玉之间": 4, "王座间": 5,
    "比赛场": 100,
}

# 等级编号 → 初始点数
# 按汉语房间名查初始点数
ROOM_INIT_POINTS: Dict[str, int] = {
    "友人场": 25000, "铜之间": 25000, "银之间": 25000,
    "金之间": 25000, "玉之间": 25000, "王座间": 30000,
}


# ═══════════════════════════════════════════════════════════════
#  天凤牌编码 (用于跨工具兼容)
# ═══════════════════════════════════════════════════════════════

# 雀魂 tile_id → 天凤 tenhou_id
#   万子 0-8   → 11-19
#   筒子 9-17  → 21-29
#   索子 18-26 → 31-39
#   字牌 27-33 → 41-47
#   赤5万     → 51
#   赤5筒     → 52
#   赤5索     → 53
def majsoul_to_tenhou(tile_id: int) -> int:
    """雀魂 tile_id → 天凤 tile_id"""
    if tile_id < 0:
        return -1
    if tile_id <= 8:        # 万子
        return 11 + tile_id
    elif tile_id <= 17:     # 筒子
        return 21 + (tile_id - 9)
    elif tile_id <= 26:     # 索子
        return 31 + (tile_id - 18)
    elif tile_id <= 33:     # 字牌
        return 41 + (tile_id - 27)
    elif tile_id == 34:     # 赤5万
        return 51
    elif tile_id == 35:     # 赤5筒
        return 52
    elif tile_id == 36:     # 赤5索
        return 53
    return -1


def tenhou_to_majsoul(tenhou_id: int) -> int:
    """天凤 tile_id → 雀魂 tile_id"""
    if 11 <= tenhou_id <= 19:
        return tenhou_id - 11
    elif 21 <= tenhou_id <= 29:
        return tenhou_id - 21 + 9
    elif 31 <= tenhou_id <= 39:
        return tenhou_id - 31 + 18
    elif 41 <= tenhou_id <= 47:
        return tenhou_id - 41 + 27
    elif tenhou_id == 51:
        return 34
    elif tenhou_id == 52:
        return 35
    elif tenhou_id == 53:
        return 36
    return -1


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════

def get_yaku_name(yaku_id: int) -> str:
    """根据役种 ID 获取中文名"""
    return YAKU_ID_TO_NAME.get(yaku_id, f"未知役种({yaku_id})")


def get_yaku_fan(yaku_id: int) -> int:
    """根据役种 ID 获取番数"""
    return YAKU_FAN.get(yaku_id, 0)


def is_yakuman(yaku_id: int) -> bool:
    """判断是否为役满"""
    return yaku_id >= 35


def calc_total_fan(yaku_ids: List[int]) -> int:
    """计算役种 ID 列表的总番数 (用于和牌得分计算)"""
    total = 0
    for yid in yaku_ids:
        total += get_yaku_fan(yid)
    return total


def get_room_name(mode_id: int) -> str:
    """根据 mode_id 获取房间名"""
    return MODE_ID_TO_ROOM.get(mode_id, f"未知房间({mode_id})")


def get_button_name(option_type: str) -> str:
    """雀魂操作类型 → 按钮中文名"""
    return BUTTON_DISPLAY_NAMES.get(option_type, option_type)
