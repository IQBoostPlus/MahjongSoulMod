"""
应用上下文 — 单例容器

统一管理所有核心组件实例，确保 main.py 和 mitm/addons.py 使用的是同一套
GameTracker / AIDecisionMaker / ActionExecutor / EventBus。
"""

from typing import Optional

from core.events import EventBus, GameEvent
from utils.log import Logger


class AppContext:
    """
    全局应用上下文

    用法:
        ctx = AppContext.get()
        ctx.event_bus.subscribe(GameEvent.DRAW_TILE, my_handler)
        ctx.tracker.on_game_event(...)
    """

    _instance: Optional["AppContext"] = None

    def __init__(self):
        if not self.__class__._instance:
            raise RuntimeError(
                "Use AppContext.create() or AppContext.get() instead of direct constructor"
            )

    @classmethod
    def create(cls) -> "AppContext":
        """首次创建 (内部使用)，返回单例"""
        if cls._instance is not None:
            return cls._instance

        instance = object.__new__(cls)
        instance._setup()
        cls._instance = instance
        return instance

    @classmethod
    def get(cls) -> "AppContext":
        """获取单例 — 未创建时自动创建"""
        if cls._instance is None:
            return cls.create()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置上下文 (测试用)"""
        cls._instance = None

    # ── 组件初始化 ──

    def _setup(self):
        from game_state.tracker import GameTracker
        from ai.engine import AIDecisionMaker
        from action.executor import ActionExecutor

        # 基础设施
        self._event_bus = EventBus()

        # 领域组件 (共享单例)
        self._tracker = GameTracker()
        self._ai = AIDecisionMaker()
        self._executor = ActionExecutor()

        # Tracker 状态更新 → EventBus 事件
        self._tracker.add_callback(self._on_tracker_update)

        # 游戏事件 → AI 决策触发
        self._event_bus.subscribe(GameEvent.DRAW_TILE, self._on_draw_tile)
        self._event_bus.subscribe(GameEvent.DISCARD_TILE, self._on_discard_tile)

        # AI 决策 → 动作执行
        self._event_bus.subscribe(GameEvent.AI_DECISION, self._on_ai_decision)

        # 控制事件
        self._event_bus.subscribe(GameEvent.TOGGLE_AUTO, self._on_toggle_auto)
        self._event_bus.subscribe(GameEvent.KILL_SWITCH, self._on_kill_switch)

        # 全局事件日志 (调试)
        self._event_bus.on_any(self._on_any_event)

        # 状态
        self._auto_mode = True
        self._listen_only = False
        self._running = True

    # ── 属性 ──

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    @property
    def tracker(self):
        return self._tracker

    @property
    def ai(self):
        return self._ai

    @property
    def executor(self):
        return self._executor

    @property
    def auto_mode(self) -> bool:
        return self._auto_mode

    @property
    def running(self) -> bool:
        return self._running

    def stop(self):
        self._running = False

    def set_listen_only(self, val: bool):
        self._listen_only = val

    # ── Tracker 回调 → EventBus 事件 ──

    def _on_tracker_update(self, msg_name: str, state):
        """GameTracker 状态更新 → 转换为 EventBus 事件"""
        event_map = {
            "new_round":          GameEvent.NEW_ROUND,
            "draw_tile":          GameEvent.DRAW_TILE,
            "discard_tile":       GameEvent.DISCARD_TILE,
            "chi":                GameEvent.CHI,
            "pon":                GameEvent.PON,
            "kan":                GameEvent.KAN,
            "an_kan":             GameEvent.AN_KAN,
            "add_kan":            GameEvent.ADD_KAN,
            "liqi":               GameEvent.RIICHI,
            "hu":                 GameEvent.TSUMO,
            "liuju":              GameEvent.LIUJU,
            "game_start":         GameEvent.GAME_START,
            "game_end":           GameEvent.GAME_END,
            "update_left_count":  GameEvent.TILE_COUNT,
        }

        event = event_map.get(msg_name)
        if event:
            self._event_bus.publish(event, state=state, msg_name=msg_name)

    # ── 游戏事件 → AI 决策 ──

    def _on_draw_tile(self, event: GameEvent, data: dict):
        """摸牌 → AI 出牌决策"""
        if not self._auto_mode or self._listen_only:
            return

        state = data.get("state")
        if not state or not state.in_game:
            return

        hand = state.players[state.self_seat].hand
        if state.last_action == "draw" and len(hand) > 13:
            self._ai.on_state_update(state)
            decision = self._ai.decide_discard(state)
            self._event_bus.publish(GameEvent.AI_DECISION, action=decision)

    def _on_discard_tile(self, event: GameEvent, data: dict):
        """对手出牌 → 可能触发鸣牌决策"""
        if not self._auto_mode or self._listen_only:
            return

        state = data.get("state")
        if not state or not state.in_game:
            return

        # 更新 AI 策略
        self._ai.on_state_update(state)

        # 鸣牌决策：检查是否有吃/碰/杠机会
        # (实际触发取决于游戏 UI 是否显示鸣牌按钮)
        incoming = state.last_discard
        if incoming >= 0:
            for call_type in ("pon", "chi", "kan"):
                result = self._ai.decide_call(state, incoming, call_type)
                if result.action.value != "pass":
                    self._event_bus.publish(GameEvent.AI_DECISION, action=result)
                    return

    # ── AI 决策 → 动作执行 ──

    def _on_ai_decision(self, event: GameEvent, data: dict):
        """AI 决策结果 → ActionExecutor 执行"""
        if self._listen_only:
            action = data.get("action")
            if action:
                Logger.info(f"[ListenOnly] Would execute: {action.action.value} tile={action.tile}")
            return

        action = data.get("action")
        if action:
            ok = self._executor.execute(action)
            if ok:
                self._event_bus.publish(GameEvent.ACTION_DONE, action=action)
            else:
                self._event_bus.publish(GameEvent.ACTION_FAILED, action=action)

    # ── 控制事件 ──

    def _on_toggle_auto(self, event: GameEvent, data: dict):
        self._auto_mode = not self._auto_mode
        Logger.info(f"[Control] Auto mode: {'ON' if self._auto_mode else 'OFF'}")

    def _on_kill_switch(self, event: GameEvent, data: dict):
        self._running = False
        self._auto_mode = False
        Logger.info("[Control] KILL SWITCH — all automation stopped")

    def _on_any_event(self, event: GameEvent, data: dict):
        """所有事件的调试日志"""
        Logger.debug(f"[EventBus] {event.value}")
