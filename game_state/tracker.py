"""
牌局/对局 状态追踪器

接收来自 mitmproxy addon 的 liqi 协议消息，构建完整的结构化牌局状态。
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import IntEnum

from proto import (
    tile_id, tile_suit, tile_value, tile_is_red, tile_to_str,
    YAOCHU_TILES, MSG_NAMES_S2C
)
from utils.log import Logger


class MeldType(IntEnum):
    CHI = 1
    PON = 2
    KAN_MING = 3  # 明杠
    KAN_AN = 4    # 暗杠
    KAN_JIA = 5   # 加杠


@dataclass
class Meld:
    type: MeldType
    tiles: List[int]     # 组成牌
    called_from: int     # 被鸣牌来源座位


@dataclass
class Player:
    """玩家状态"""
    seat: int = 0
    hand: List[int] = field(default_factory=list)          # 手牌 (编码ID)
    discards: List[int] = field(default_factory=list)      # 舍牌序列
    melds: List[Meld] = field(default_factory=list)        # 副露
    discards_count: int = 0                                # 舍牌数(含摸切)
    is_liqi: bool = False
    is_menzen: bool = True                                 # 门前清
    score: int = 25000


@dataclass
class GameState:
    """
    完整牌局状态
    由 GameTracker 消息驱动更新
    """
    # ── 局况 ──
    round_wind: int = 0          # 场风 (0=东, 1=南)
    round_number: int = 0        # 局数 (0-3)
    honba: int = 0               # 本场
    dealer: int = 0              # 庄家座位
    self_seat: int = 0           # 自家座位

    # ── 牌局数据 ──
    players: List[Player] = field(default_factory=lambda: [Player(), Player(), Player(), Player()])
    dora_indicator: int = -1     # 宝牌指示牌
    left_tiles: int = 0          # 牌山剩余
    deposits: List[int] = field(default_factory=lambda: [0, 0, 0, 0])  # 立直棒

    # ── 已见牌追踪 ──
    seen_tiles: List[int] = field(default_factory=lambda: [0] * 37)  # 0-36每种牌的已见张数

    # ── 最后动作 ──
    last_action: str = ""
    last_discard: int = -1       # 上家打出的最后一张牌

    # ── 对局生命周期 ──
    in_game: bool = False

    def get_seen_count(self, tile_id: int) -> int:
        """获取某张牌已见张数"""
        if 0 <= tile_id < len(self.seen_tiles):
            return self.seen_tiles[tile_id]
        return 0

    def get_remaining(self, tile_id: int) -> int:
        """获取某张牌剩余张数 (最多4张)"""
        return 4 - self.get_seen_count(tile_id)

    def __str__(self) -> str:
        hand = ", ".join(tile_to_str(t) for t in self.players[self.self_seat].hand)
        return (
            f"[局] {'东南'[self.round_wind]}{self.round_number + 1}局 "
            f"本场{self.honba} 剩余{self.left_tiles}枚 "
            f"手牌({len(self.players[self.self_seat].hand)}枚): {hand}"
        )


class GameTracker:
    """
    对局状态追踪器

    接收 liqi 协议消息 → 增量更新 GameState
    """

    def __init__(self):
        self.state = GameState()
        self._callbacks = []

    def on_game_event(self, msg_name: str, data: dict):
        """处理一条游戏消息"""
        handler = getattr(self, f"_on_{msg_name}", None)
        if handler:
            handler(data)
            # 回调通知
            for cb in self._callbacks:
                cb(msg_name, self.state)
        else:
            Logger.debug(f"Unknown event: {msg_name}")

    def add_callback(self, callback):
        """添加状态更新回调"""
        self._callbacks.append(callback)

    # ── 消息处理器 ──

    def _on_notify_room_view(self, data: dict):
        """进入房间"""
        Logger.info("Room joined")

    def _on_game_start(self, data: dict):
        """游戏开始"""
        Logger.info("=== GAME START ===")
        self.state = GameState()
        self.state.in_game = True

    def _on_new_round(self, data: dict):
        """新一局开始"""
        self.state.round_wind = data.get("chang", 0)
        self.state.round_number = data.get("ju", 0)
        self.state.honba = data.get("ben", 0)
        self.state.dealer = data.get("oya", 0)
        self.state.self_seat = data.get("self_seat", 0)
        self.state.dora_indicator = data.get("dora_indicator", -1)
        self.state.left_tiles = data.get("tile_count", 0)
        self.state.last_action = "new_round"
        self.state.last_discard = -1

        # 点数
        scores = data.get("scores", [25000, 25000, 25000, 25000])
        for i in range(4):
            self.state.players[i].score = scores[i]
            self.state.players[i].hand = []
            self.state.players[i].discards = []
            self.state.players[i].melds = []
            self.state.players[i].is_liqi = False
            self.state.players[i].is_menzen = True

        self.state.deposits = data.get("deposits", [0, 0, 0, 0])

        # 手牌
        tiles = data.get("tiles", [])
        self.state.players[self.state.self_seat].hand = list(tiles)

        # 重置已见牌统计
        self.state.seen_tiles = [0] * 37
        for t in tiles:
            if 0 <= t < 37:
                self.state.seen_tiles[t] += 1

        Logger.info(f"New round: {self.state}")

    def _on_deal_tile(self, data: dict):
        """发牌/配牌"""
        pass  # new_round 已包含手牌

    def _on_draw_tile(self, data: dict):
        """摸牌"""
        seat = data.get("seat", 0)
        tile = data.get("tile", -1)

        if seat == self.state.self_seat:
            if tile >= 0:
                self.state.players[seat].hand.append(tile)
                if 0 <= tile < 37:
                    self.state.seen_tiles[tile] += 1
                Logger.info(f"Draw: {tile_to_str(tile)} → {', '.join(tile_to_str(t) for t in self.state.players[seat].hand)}")

        self.state.left_tiles = data.get("left_count", self.state.left_tiles - 1)

    def _on_discard_tile(self, data: dict):
        """出牌"""
        seat = data.get("seat", 0)
        tile = data.get("tile", -1)
        is_liqi = data.get("is_liqi", False)
        moqie = data.get("moqie", 0)

        if tile >= 0:
            self.state.players[seat].discards.append(tile)
            self.state.players[seat].discards_count += 1
            if 0 <= tile < 37:
                self.state.seen_tiles[tile] += 1

        # 从手牌移除 (仅自家)
        if seat == self.state.self_seat and tile >= 0:
            if tile in self.state.players[seat].hand:
                self.state.players[seat].hand.remove(tile)

        if is_liqi:
            self.state.players[seat].is_liqi = True

        self.state.last_discard = tile
        self.state.last_action = "discard"

        Logger.info(f"Discard[{seat}]: {tile_to_str(tile)} " +
                    f"{'(liqi)' if is_liqi else ''}{'(moqie)' if moqie else ''}")

    def _on_chi(self, data: dict):
        """吃"""
        seat = data.get("seat", 0)
        tile = data.get("tile", -1)
        tiles = data.get("tiles", [])

        meld = Meld(MeldType.CHI, tiles, data.get("from", -1))
        self.state.players[seat].melds.append(meld)
        self.state.players[seat].is_menzen = False

        # 从手牌移除
        if seat == self.state.self_seat:
            for t in tiles:
                if t in self.state.players[seat].hand:
                    self.state.players[seat].hand.remove(t)

        Logger.info(f"Chi[{seat}]: {tile_to_str(tile)}")

    def _on_pon(self, data: dict):
        """碰"""
        seat = data.get("seat", 0)
        tile = data.get("tile", -1)

        # 碰牌由3张相同牌组成
        meld = Meld(MeldType.PON, [tile, tile, tile], data.get("from", -1))
        self.state.players[seat].melds.append(meld)
        self.state.players[seat].is_menzen = False

        # 从手牌移除2张
        if seat == self.state.self_seat:
            for _ in range(2):
                if tile in self.state.players[seat].hand:
                    self.state.players[seat].hand.remove(tile)

        Logger.info(f"Pon[{seat}]: {tile_to_str(tile)}")

    def _on_kan(self, data: dict):
        """明杠"""
        self._add_kan(data, MeldType.KAN_MING, "Kan")

    def _on_an_kan(self, data: dict):
        """暗杠"""
        self._add_kan(data, MeldType.KAN_AN, "AnKan")

    def _on_add_kan(self, data: dict):
        """加杠"""
        self._add_kan(data, MeldType.KAN_JIA, "AddKan")

    def _add_kan(self, data: dict, meld_type: MeldType, label: str):
        seat = data.get("seat", 0)
        tile = data.get("tile", -1)
        meld = Meld(meld_type, [tile] * 4, data.get("from", -1))
        self.state.players[seat].melds.append(meld)
        self.state.players[seat].is_menzen = False

        if seat == self.state.self_seat:
            for _ in range(4 if meld_type != MeldType.KAN_JIA else 1):
                if tile in self.state.players[seat].hand:
                    self.state.players[seat].hand.remove(tile)

        Logger.info(f"{label}[{seat}]: {tile_to_str(tile)}")

    def _on_liqi(self, data: dict):
        """立直宣告"""
        seat = data.get("seat", 0)
        self.state.players[seat].is_liqi = True
        Logger.info(f"Liqi[{seat}]")

    def _on_hu(self, data: dict):
        """和牌"""
        seat = data.get("seat", 0)
        from_seat = data.get("from", seat)
        score = data.get("score", 0)
        zimo = data.get("zimo", False)

        Logger.info(f"{'Tsumo' if zimo else 'Ron'}[{seat}] ← [{from_seat}] +{score}pt")

    def _on_liuju(self, data: dict):
        """流局"""
        Logger.info(f"Liuju: type={data.get('type', 0)}")

    def _on_game_end(self, data: dict):
        """游戏结束"""
        self.state.in_game = False
        Logger.info("=== GAME END ===")
