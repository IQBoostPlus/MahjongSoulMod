"""
雀魂 liqi 协议编解码器

麻将牌编码 (Majsoul 格式):
  0-8:   一万~九万
  9-17:  一筒~九筒
  18-26: 一索~九索
  27-33: 东南西北白发中
  34-36: 赤5 (34=5m赤, 35=5p赤, 36=5s赤)

协议基于 Protobuf + WebSocket，所有消息以 Wrapper(name, data) 形式传输。
本模块完成两层解析: Wrapper 外层 → 内层消息 bytes → 结构化 dict。
"""

import struct
from typing import Any, Dict, List, Optional, Tuple

# ── 役种/按钮/房间映射 (来自 MajsoulPaipuAnalyzer) ──
from .yaku import (  # noqa: F401 — re-export for convenience
    YAKU_ID_TO_NAME, YAKU_FAN, YAKU_NAME_JP,
    MAJSOUL_OPTION_TO_BUTTON, BUTTON_TO_OPTION, BUTTON_TO_NUM,
    NAKI_TYPE_TO_STR, NAKI_STR_TO_TYPE,
    ACTION_TYPE_TO_PROTO, BUTTON_DISPLAY_NAMES,
    MODE_ID_TO_ROOM, ROOM_NAME_TO_LEVEL, ROOM_INIT_POINTS,
    majsoul_to_tenhou, tenhou_to_majsoul,
    get_yaku_name, get_yaku_fan, is_yakuman, calc_total_fan,
    get_room_name, get_button_name,
)

# ── 牌编码工具 ──

def tile_id(suit: int, value: int) -> int:
    """花色+数值 → ID (0-33)"""
    return suit * 9 + (value - 1)

def tile_suit(tile: int) -> int:
    """牌ID → 花色 (0=万, 1=筒, 2=索, 3=字)"""
    if tile >= 34:  # 赤5
        return (tile - 34) // 9
    return tile // 9

def tile_value(tile: int) -> int:
    """牌ID → 数值 (1-9, 字牌1-7)"""
    if tile >= 34:  # 赤5
        v = (tile - 34) % 9 + 1
        return v
    v = tile % 9 + 1
    return v

def tile_is_red(tile: int) -> bool:
    """是否赤5"""
    return tile >= 34

def tile_to_str(tile: int) -> str:
    """牌ID → 人类可读字符串 (如 '5m', '1z', 'r5p')"""
    if tile < 0 or tile > 36:
        return "?"
    s = tile_suit(tile)
    v = tile_value(tile)
    r = "r" if tile_is_red(tile) else ""
    suit_ch = {0: "m", 1: "p", 2: "s", 3: "z"}
    return f"{v}{suit_ch.get(s, '?')}{r}"

# 幺九牌集合
YAOCHU_TILES = {0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33}


# ── 协议消息名 ──

# 服务端→客户端
MSG_NAMES_S2C = {
    ".lq.NotifyRoomViewDataNotify": "notify_room_view",
    ".lq.NotifyGameStart": "game_start",
    ".lq.NotifyGameEnd": "game_end",
    ".lq.NotifyNewRound": "new_round",
    ".lq.NotifyDealTile": "deal_tile",
    ".lq.NotifyDrawTile": "draw_tile",
    ".lq.NotifyDiscardTile": "discard_tile",
    ".lq.NotifyChi": "chi",
    ".lq.NotifyPon": "pon",
    ".lq.NotifyKan": "kan",
    ".lq.NotifyAddKan": "add_kan",
    ".lq.NotifyAnKan": "an_kan",
    ".lq.NotifyLiqi": "liqi",
    ".lq.NotifyHu": "hu",
    ".lq.NotifyLiuJu": "liuju",
    ".lq.NotifyUpdateLeftTileCount": "update_left_count",
}

# 客户端→服务端
MSG_NAMES_C2S = {
    ".lq.ReqDiscardTile": "req_discard",
    ".lq.ReqChi": "req_chi",
    ".lq.ReqPon": "req_pon",
    ".lq.ReqKan": "req_kan",
    ".lq.ReqAddKan": "req_add_kan",
    ".lq.ReqAnKan": "req_an_kan",
    ".lq.ReqLiqi": "req_liqi",
    ".lq.ReqHu": "req_hu",
    ".lq.ReqPass": "req_pass",
    ".lq.ReqNoTile": "req_no_tile",
}


# ═══════════════════════════════════════════════════════════════
#  Protobuf 底层工具函数
# ═══════════════════════════════════════════════════════════════

def _decode_varint(data: bytes, pos: int) -> Tuple[int, int]:
    """解码 protobuf varint → (value, new_pos)"""
    value = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        value |= (byte & 0x7f) << shift
        shift += 7
        pos += 1
        if (byte & 0x80) == 0:
            break
    return value, pos


def _encode_varint(value: int) -> bytes:
    """编码 protobuf varint"""
    result = bytearray()
    while value > 0x7f:
        result.append((value & 0x7f) | 0x80)
        value >>= 7
    result.append(value & 0x7f)
    return bytes(result)


def _decode_length_delimited(data: bytes, pos: int) -> Tuple[bytes, int]:
    """解码 length-delimited 字段 → (bytes_content, new_pos)"""
    length, pos = _decode_varint(data, pos)
    content = data[pos:pos + length]
    return content, pos + length


def _decode_packed_varints(data: bytes) -> List[int]:
    """解码 packed repeated varint 字段"""
    values = []
    pos = 0
    while pos < len(data):
        v, pos = _decode_varint(data, pos)
        values.append(v)
    return values


# ═══════════════════════════════════════════════════════════════
#  内层消息解析器 — 将 protobuf bytes → 结构化 dict
# ═══════════════════════════════════════════════════════════════

def parse_new_round(data: bytes) -> dict:
    """
    解析 NewRound 消息
    fields: chang(1), ju(2), ben(3), tile_count(4),
            tiles(5,packed), dora_indicator(6), scores(7,packed),
            deposits(8,packed), oya(9)
    """
    result = {
        "chang": 0, "ju": 0, "ben": 0, "tile_count": 0,
        "tiles": [], "dora_indicator": -1,
        "scores": [25000, 25000, 25000, 25000],
        "deposits": [0, 0, 0, 0], "oya": 0, "self_seat": 0,
    }
    _walk_fields(data, {
        1: lambda v: result.update(chang=v),
        2: lambda v: result.update(ju=v),
        3: lambda v: result.update(ben=v),
        4: lambda v: result.update(tile_count=v),
        5: lambda b: result.update(tiles=_decode_packed_varints(b)),
        6: lambda v: result.update(dora_indicator=v),
        7: lambda b: result.update(scores=_decode_packed_varints(b)),
        8: lambda b: result.update(deposits=_decode_packed_varints(b)),
        9: lambda v: result.update(oya=v),
    })
    return result


def parse_draw_tile(data: bytes) -> dict:
    """fields: seat(1), tile(2), left_count(3)"""
    result = {"seat": 0, "tile": -1, "left_count": 0}
    _walk_fields(data, {
        1: lambda v: result.update(seat=v),
        2: lambda v: result.update(tile=v),
        3: lambda v: result.update(left_count=v),
    })
    return result


def parse_discard_tile(data: bytes) -> dict:
    """fields: seat(1), tile(2), is_liqi(3), moqie(4)"""
    result = {"seat": 0, "tile": -1, "is_liqi": False, "moqie": 0}
    _walk_fields(data, {
        1: lambda v: result.update(seat=v),
        2: lambda v: result.update(tile=v),
        3: lambda v: result.update(is_liqi=bool(v)),
        4: lambda v: result.update(moqie=v),
    })
    return result


def parse_chi(data: bytes) -> dict:
    """fields: seat(1), tile(2), tile1(3), tile2(4)"""
    result = {"seat": 0, "tile": -1, "tiles": [], "from": -1}
    chi_tiles = []
    _walk_fields(data, {
        1: lambda v: result.update(seat=v),
        2: lambda v: result.update(tile=v),
        3: lambda v: chi_tiles.append(v),
        4: lambda v: chi_tiles.append(v),
    })
    # 被吃的牌 + 手牌2张 = 3张组成顺子
    if result["tile"] >= 0:
        result["tiles"] = [result["tile"]] + chi_tiles
    return result


def parse_pon(data: bytes) -> dict:
    """fields: seat(1), tile(2), from(3)"""
    result = {"seat": 0, "tile": -1, "from": -1}
    _walk_fields(data, {
        1: lambda v: result.update(seat=v),
        2: lambda v: result.update(tile=v),
        3: lambda v: result.update(**{"from": v}),  # 'from' is reserved
    })
    return result


def parse_kan(data: bytes) -> dict:
    """fields: seat(1), tile(2), type(3), from(4)"""
    result = {"seat": 0, "tile": -1, "type": 1, "from": -1}
    _walk_fields(data, {
        1: lambda v: result.update(seat=v),
        2: lambda v: result.update(tile=v),
        3: lambda v: result.update(type=v),
        4: lambda v: result.update(**{"from": v}),
    })
    return result


def parse_an_kan(data: bytes) -> dict:
    """暗杠: 简化处理，字段与 kan 类似"""
    return parse_kan(data)


def parse_add_kan(data: bytes) -> dict:
    """加杠"""
    return parse_kan(data)


def parse_liqi(data: bytes) -> dict:
    """fields: seat(1), tile(2)"""
    result = {"seat": 0, "tile": -1}
    _walk_fields(data, {
        1: lambda v: result.update(seat=v),
        2: lambda v: result.update(tile=v),
    })
    return result


def parse_hu(data: bytes) -> dict:
    """
    解析和牌消息
    fields: seat(1), from(2), tile(3), zimo(4), tiles(5,packed),
            melds(6), fu(7), fan(8), score(9), scores(10,packed),
            yaku(11,packed), baoman(12), fan_id(13)
    """
    result = {
        "seat": 0, "from": 0, "tile": -1, "zimo": False,
        "tiles": [], "melds": [], "fu": 0, "fan": 0, "score": 0,
        "scores": [], "yaku": [], "baoman": False, "fan_id": 0,
    }
    _walk_fields(data, {
        1:  lambda v: result.update(seat=v),
        2:  lambda v: result.update(**{"from": v}),
        3:  lambda v: result.update(tile=v),
        4:  lambda v: result.update(zimo=bool(v)),
        5:  lambda b: result.update(tiles=_decode_packed_varints(b)),
        7:  lambda v: result.update(fu=v),
        8:  lambda v: result.update(fan=v),
        9:  lambda v: result.update(score=v),
        10: lambda b: result.update(scores=_decode_packed_varints(b)),
        11: lambda b: result.update(yaku=_decode_packed_varints(b)),
        12: lambda v: result.update(baoman=bool(v)),
        13: lambda v: result.update(fan_id=v),
    })
    return result


def parse_liuju(data: bytes) -> dict:
    """fields: type(1), tenpai(2,packed), scores(3,packed)"""
    result = {"type": 0, "tenpai": [], "scores": []}
    _walk_fields(data, {
        1: lambda v: result.update(type=v),
        2: lambda b: result.update(tenpai=_decode_packed_varints(b)),
        3: lambda b: result.update(scores=_decode_packed_varints(b)),
    })
    return result


def parse_update_left_count(data: bytes) -> dict:
    """field: left_count(1)"""
    result = {"left_count": 0}
    _walk_fields(data, {
        1: lambda v: result.update(left_count=v),
    })
    return result


def parse_game_start(data: bytes) -> dict:
    """游戏开始 (通常无重要字段，返回空即可)"""
    return {}


def parse_game_end(data: bytes) -> dict:
    """游戏结束"""
    return {}


def parse_deal_tile(data: bytes) -> dict:
    """配牌 (new_round 已包含手牌，此消息可忽略)"""
    return {}


# ── 内层解析器注册表 ──

_INNER_PARSERS = {
    "new_round":          parse_new_round,
    "draw_tile":          parse_draw_tile,
    "discard_tile":       parse_discard_tile,
    "chi":                parse_chi,
    "pon":                parse_pon,
    "kan":                parse_kan,
    "an_kan":             parse_an_kan,
    "add_kan":            parse_add_kan,
    "liqi":               parse_liqi,
    "hu":                 parse_hu,
    "liuju":              parse_liuju,
    "update_left_count":  parse_update_left_count,
    "game_start":         parse_game_start,
    "game_end":           parse_game_end,
    "deal_tile":          parse_deal_tile,
    "notify_room_view":   lambda _: {},
}


# ═══════════════════════════════════════════════════════════════
#  Protobuf 字段遍历器 (手动解析，无依赖)
# ═══════════════════════════════════════════════════════════════

def _walk_fields(data: bytes, handlers: Dict[int, callable]) -> None:
    """
    遍历 protobuf 消息的各个字段，对每个字段调用对应的 handler。

    Args:
        data: 原始 protobuf 二进制
        handlers: { field_number → handler(varint_value | bytes_value) }

    wire_type:
      0 = varint (int32/int64/bool/enum)
      2 = length-delimited (string/bytes/packed/repeated)
    """
    pos = 0
    while pos < len(data):
        if pos >= len(data):
            break
        tag = data[pos]
        pos += 1

        field_number = tag >> 3
        wire_type = tag & 0x07

        handler = handlers.get(field_number)
        if handler is None:
            # 跳过未知字段
            pos = _skip_field(data, pos, wire_type)
            continue

        if wire_type == 0:  # varint
            value, pos = _decode_varint(data, pos)
            handler(value)
        elif wire_type == 2:  # length-delimited
            content, pos = _decode_length_delimited(data, pos)
            handler(content)
        elif wire_type == 5:  # 32-bit (fixed32, float)
            pos += 4
        elif wire_type == 1:  # 64-bit (fixed64, double)
            pos += 8
        else:
            break


def _skip_field(data: bytes, pos: int, wire_type: int) -> int:
    """跳过未知字段，返回新位置"""
    if wire_type == 0:
        _, pos = _decode_varint(data, pos)
    elif wire_type == 2:
        length, pos = _decode_varint(data, pos)
        pos += length
    elif wire_type == 5:
        pos += 4
    elif wire_type == 1:
        pos += 8
    return pos


# ═══════════════════════════════════════════════════════════════
#  LiqiDecoder — 主解码器
# ═══════════════════════════════════════════════════════════════

class LiqiDecoder:
    """
    liqi 协议解码器

    将 WebSocket 二进制消息解析为 { name, data } 结构化字典。
    两层解析:
      1. Wrapper: name(string) + data(bytes)
      2. Inner:   根据 name 选择对应的内层消息解析器
    """

    @staticmethod
    def decode_message(data: bytes) -> Optional[Dict[str, Any]]:
        """
        解码单条 WebSocket 消息

        返回: { "name": str, "data": dict } 或 None
        """
        try:
            pos = 0

            # 尝试跳过长度头 (2 bytes, little-endian)
            if len(data) >= 2:
                msg_len = struct.unpack('<H', data[:2])[0]
                if 0 < msg_len <= len(data) - 2:
                    pos = 2

            if pos >= len(data):
                return None

            # ── 第一层: 解析 Wrapper ──
            wrapper = LiqiDecoder._parse_wrapper(data, pos)
            if wrapper is None:
                return None

            raw_name = wrapper.get("name", "")
            raw_data = wrapper.get("data", b"")

            if not raw_name:
                return None

            # 简化消息名
            short_name = MSG_NAMES_S2C.get(raw_name, raw_name)

            # ── 第二层: 解析内层消息 ──
            parser = _INNER_PARSERS.get(short_name)
            if parser and raw_data:
                structured = parser(raw_data)
            else:
                structured = {}

            return {"name": short_name, "data": structured}

        except Exception:
            return None

    @staticmethod
    def _parse_wrapper(data: bytes, offset: int) -> Optional[Dict]:
        """解析 Wrapper protobuf: field 1=name(string), field 2=data(bytes)"""
        try:
            pos = offset
            result = {"name": "", "data": b""}

            while pos < len(data):
                if pos >= len(data):
                    break
                tag = data[pos]
                pos += 1

                field_num = tag >> 3
                wire_type = tag & 0x07

                if field_num == 1 and wire_type == 2:  # name (string)
                    content, pos = _decode_length_delimited(data, pos)
                    result["name"] = content.decode('utf-8', errors='replace')

                elif field_num == 2 and wire_type == 2:  # data (bytes)
                    content, pos = _decode_length_delimited(data, pos)
                    result["data"] = content

                elif tag == 0x00:  # padding
                    continue

                else:
                    pos = _skip_field(data, pos, wire_type)

            return result
        except Exception:
            return None

    @staticmethod
    def encode_action(action_type: int, tile: int = 0) -> bytes:
        """
        编码出牌/鸣牌请求

        Args:
            action_type: 动作类型 (1=出牌 3=吃 4=碰 5=杠 8=立直 11=过)
            tile: 关联牌编码

        Returns: WebSocket 消息 bytes
        """
        # 构建 ReqAction protobuf:
        # field 1 (type, int32): tag=0x08
        # field 2 (tile, int32): tag=0x10
        payload = bytearray()
        payload.append(0x08)
        payload.extend(_encode_varint(action_type))

        if tile > 0:
            payload.append(0x10)
            payload.extend(_encode_varint(tile))

        # 构建 Wrapper
        wrapper = bytearray()
        # name = ""
        wrapper.append(0x0a)
        name_bytes = b""
        wrapper.extend(_encode_varint(len(name_bytes)))

        # data = payload
        wrapper.append(0x12)
        wrapper.extend(_encode_varint(len(payload)))
        wrapper.extend(payload)

        # 长度头
        header = struct.pack('<H', len(wrapper))
        return bytes(header) + bytes(wrapper)
