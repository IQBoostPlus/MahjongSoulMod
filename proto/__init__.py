"""
雀魂 liqi 协议编解码器

麻将牌编码 (Majsoul 格式):
  0-8:   一万~九万
  9-17:  一筒~九筒
  18-26: 一索~九索
  27-33: 东南西北白发中
  34-...: 赤5 (34=5m赤, 35=5p赤, 36=5s赤)

协议基于 Protobuf + WebSocket, 所有消息以 Wrapper(name, data) 形式传输
"""

import struct
import json
from typing import Any, Dict, List, Optional, Tuple


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
    return tile >= 34

def tile_to_str(tile: int) -> str:
    if tile < 0 or tile > 36:
        return f"?"
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


# ── 原始协议消息解析 ──

class LiqiDecoder:
    """
    liqi 协议解码器
    将 WebSocket 收到的二进制消息解码为结构化字典。

    消息格式:
      - 消息头 (2 bytes): 消息长度
      - 消息体: Wrapper(name=消息名, data=ProtobufBytes)
    """

    @staticmethod
    def decode_message(data: bytes) -> Optional[Dict[str, Any]]:
        """
        解码单条 WebSocket 消息

        返回: { "name": str, "data": dict } 或 None
        """
        try:
            # 消息格式: 2字节长度 + Wrapper protobuf
            # 某些情况可能没有长度头
            pos = 0
            if len(data) >= 2:
                # 尝试解析长度头
                msg_len = struct.unpack('<H', data[:2])[0]
                if msg_len > 0 and msg_len + 2 <= len(data):
                    pos = 2

            if pos >= len(data):
                return None

            # 简易 Wrapper 解析 (protobuf 格式)
            # field 1 (name, string): tag=0x0a
            # field 2 (data, bytes): tag=0x12
            return LiqiDecoder._parse_wrapper(data, pos)

        except Exception as e:
            Logger.warning(f"Decode error: {e}")
            return None

    @staticmethod
    def _parse_wrapper(data: bytes, offset: int) -> Optional[Dict]:
        """解析 Wrapper protobuf"""
        try:
            pos = offset
            result = {"name": "", "data": b""}

            while pos < len(data):
                if pos >= len(data):
                    break
                tag = data[pos]
                pos += 1

                if tag == 0x0a:  # field 1: name (string)
                    strlen, n = LiqiDecoder._decode_varint(data, pos)
                    pos = n
                    result["name"] = data[pos:pos + strlen].decode('utf-8', errors='replace')
                    pos += strlen

                elif tag == 0x12:  # field 2: data (bytes)
                    strlen, n = LiqiDecoder._decode_varint(data, pos)
                    pos = n
                    result["data"] = data[pos:pos + strlen]
                    pos += strlen

                elif tag == 0x00:  # padding
                    continue

                else:
                    # 跳过未知字段
                    wire_type = tag & 0x07
                    field_num = tag >> 3
                    if wire_type == 0:  # varint
                        _, pos = LiqiDecoder._decode_varint(data, pos)
                    elif wire_type == 2:  # length-delimited
                        strlen, pos = LiqiDecoder._decode_varint(data, pos)
                        pos += strlen
                    elif wire_type == 5:  # 32-bit
                        pos += 4
                    else:
                        break

            return result
        except:
            return None

    @staticmethod
    def _decode_varint(data: bytes, pos: int) -> Tuple[int, int]:
        """解码 protobuf varint"""
        value = 0
        shift = 0
        start = pos
        while pos < len(data):
            byte = data[pos]
            value |= (byte & 0x7f) << shift
            shift += 7
            pos += 1
            if (byte & 0x80) == 0:
                break
        return value, pos

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

        # type
        payload.append(0x08)
        payload.extend(LiqiDecoder._encode_varint(action_type))

        if tile > 0:
            payload.append(0x10)
            payload.extend(LiqiDecoder._encode_varint(tile))

        # 构建 Wrapper
        wrapper = bytearray()

        # name = ""
        wrapper.append(0x0a)
        name_bytes = b""
        strlen, _ = LiqiDecoder._encode_varint(len(name_bytes))
        wrapper.extend(strlen)

        # data = payload
        wrapper.append(0x12)
        dlen, _ = LiqiDecoder._encode_varint(len(payload))
        wrapper.extend(dlen)
        wrapper.extend(payload)

        # 长度头
        header = struct.pack('<H', len(wrapper))
        return bytes(header) + bytes(wrapper)

    @staticmethod
    def _encode_varint(value: int) -> bytes:
        """编码 protobuf varint"""
        result = bytearray()
        while value > 0x7f:
            result.append((value & 0x7f) | 0x80)
            value >>= 7
        result.append(value & 0x7f)
        return bytes(result)


# 延迟导入避免循环
from utils.log import Logger
