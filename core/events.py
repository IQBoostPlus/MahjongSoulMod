"""
轻量级事件总线

解耦各子系统 — MITM addon, GameTracker, AI Engine, ActionExecutor
之间通过事件进行通信，而非直接持有引用。
"""

from enum import Enum
from typing import Any, Callable, Dict, List, Set
from utils.log import Logger


class GameEvent(str, Enum):
    """游戏事件类型 — 使用 str 基类方便 JSON 序列化和调试"""
    # 生命周期
    GAME_START    = "game:start"
    GAME_END      = "game:end"
    NEW_ROUND     = "game:new_round"

    # 牌桌动作
    DRAW_TILE     = "game:draw_tile"
    DISCARD_TILE  = "game:discard_tile"

    # 鸣牌
    CHI           = "game:chi"
    PON           = "game:pon"
    KAN           = "game:kan"
    AN_KAN        = "game:an_kan"
    ADD_KAN       = "game:add_kan"

    # 立直/和牌
    RIICHI        = "game:riichi"
    TSUMO         = "game:tsumo"
    RON           = "game:ron"

    # 流局
    LIUJU         = "game:liuju"

    # 牌山
    TILE_COUNT    = "game:tile_count"

    # AI 决策 → 执行
    AI_DECISION   = "ai:decision"

    # 执行反馈
    ACTION_DONE   = "action:done"
    ACTION_FAILED = "action:failed"

    # 控制
    TOGGLE_AUTO   = "control:toggle"
    KILL_SWITCH   = "control:kill"

    # WebSocket 连接状态
    WS_CONNECTED    = "ws:connected"
    WS_DISCONNECTED = "ws:disconnected"
    WS_RECONNECTED  = "ws:reconnected"


Handler = Callable[[GameEvent, Dict[str, Any]], None]


class EventBus:
    """
    同步事件总线 — 发布/订阅模式

    所有订阅者按注册顺序同步调用。
    对于低延迟要求的场景（如响应用户操作），使用 queue=False 直接分发。
    """

    def __init__(self):
        self._subscribers: Dict[GameEvent, List[Handler]] = {}
        self._wildcards: List[Handler] = []          # 匹配所有事件的处理器
        self._event_log: List[str] = []              # 事件日志 (最近 256 条)
        self._max_log = 256
        self._paused = False

    # ── 订阅 API ──

    def subscribe(self, event: GameEvent, handler: Handler) -> None:
        """订阅特定事件"""
        self._subscribers.setdefault(event, []).append(handler)

    def unsubscribe(self, event: GameEvent, handler: Handler) -> None:
        """取消订阅"""
        if event in self._subscribers:
            try:
                self._subscribers[event].remove(handler)
            except ValueError:
                pass

    def on_any(self, handler: Handler) -> None:
        """订阅所有事件 (调试/日志用)"""
        self._wildcards.append(handler)

    # ── 发布 API ──

    def publish(self, event: GameEvent, **data: Any) -> None:
        """发布事件 — 同步分发到所有订阅者"""
        if self._paused:
            self._log_event(event, data, skipped=True)
            return

        self._log_event(event, data)

        # 精准订阅者
        handlers = self._subscribers.get(event, [])
        for h in handlers:
            try:
                h(event, data)
            except Exception as e:
                Logger.error(f"[EventBus] Handler error for {event.value}: {e}")

        # 通配订阅者
        for h in self._wildcards:
            try:
                h(event, data)
            except Exception as e:
                Logger.error(f"[EventBus] Wildcard error: {e}")

    def emit(self, event: GameEvent, **data: Any) -> None:
        """publish 的别名 (更短的调用名)"""
        self.publish(event, **data)

    # ── 控制 ──

    def pause(self) -> None:
        """暂停事件分发"""
        self._paused = True

    def resume(self) -> None:
        """恢复事件分发"""
        self._paused = False

    def clear(self) -> None:
        """清除所有订阅"""
        self._subscribers.clear()
        self._wildcards.clear()
        self._event_log.clear()

    # ── 调试 ──

    def recent_events(self, n: int = 20) -> List[str]:
        """获取最近 N 条事件"""
        return self._event_log[-n:]

    def subscriber_count(self) -> int:
        total = sum(len(v) for v in self._subscribers.values())
        return total + len(self._wildcards)

    # ── 内部 ──

    def _log_event(self, event: GameEvent, data: Dict[str, Any], skipped: bool = False):
        prefix = "[SKIP]" if skipped else ""
        entry = f"{prefix}{event.value} data_keys={list(data.keys())[:5]}"
        self._event_log.append(entry)
        if len(self._event_log) > self._max_log:
            self._event_log = self._event_log[-self._max_log:]
