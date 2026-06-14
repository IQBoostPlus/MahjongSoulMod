"""
应用上下文 — 单例容器

统一管理所有核心组件实例，确保 main.py 和 mitm/addons.py 使用的是同一套
GameTracker / AIDecisionMaker / ActionExecutor / EventBus。
"""

from typing import Optional


class AppContext:
    """
    全局应用上下文

    用法:
        ctx = AppContext.get()
        ctx.event_bus.subscribe(...)
        ctx.tracker.on_game_event(...)

    所有子系统通过 ctx 获取共享组件，避免独立实例化导致的通信断裂。
    """

    _instance: Optional["AppContext"] = None
    _initialized: bool = False

    def __init__(self):
        if not AppContext._initialized:
            raise RuntimeError(
                "Use AppContext.create() or AppContext.get() instead of direct constructor"
            )

    @classmethod
    def create(cls) -> "AppContext":
        """首次创建 (内部使用)"""
        if cls._instance is not None:
            return cls._instance

        # bypass __init__ check
        instance = object.__new__(cls)
        instance._setup()
        cls._instance = instance
        cls._initialized = True
        return instance

    @classmethod
    def get(cls) -> "AppContext":
        """获取单例 — 如果未创建则自动创建"""
        if cls._instance is None:
            return cls.create()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置上下文 (测试用)"""
        cls._instance = None
        cls._initialized = False

    # ── 组件初始化 ──

    def _setup(self):
        from core.events import EventBus
        from game_state.tracker import GameTracker
        from ai.engine import AIDecisionMaker
        from action.executor import ActionExecutor

        # 基础设施
        self._event_bus = EventBus()

        # 领域组件
        self._tracker = GameTracker()
        self._ai = AIDecisionMaker()
        self._executor = ActionExecutor()

        # 连接 Tracker → EventBus
        self._tracker.add_callback(self._on_tracker_update)

        # 连接 AI → Executor (通过事件)
        self._event_bus.subscribe(
            self._event_bus.GameEvent if False else __import__("core.events", fromlist=["GameEvent"]).GameEvent.AI_DECISION,
            self._on_ai_decision
        ) if False else None

        # 注册 AI 决策处理器
        from core.events import GameEvent
        self._event_bus.subscribe(GameEvent.DRAW_TILE, self._on_draw_tile)
        self._event_bus.subscribe(GameEvent.DISCARD_TILE, self._on_discard_tile)

        # 控制事件
        self._event_bus.subscribe(GameEvent.TOGGLE_AUTO, self._on_toggle_auto)
        self._event_bus.subscribe(GameEvent.KILL_SWITCH, self._on_kill_switch)

        self._auto_mode = True
        self._listen_only = False
        self._running = True

    # ── 属性 ──

    @property
    def event_bus(self):
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

    def set_listen_only(self, val: bool):
        self._listen_only = val

    # ── 内部回调 ──

    def _on_tracker_update(self, msg_name: str, state):
        """GameTracker 状态更新 → 转换为事件"""
        from core.events import GameEvent

        event_map = {
            "new_round":    GameEvent.NEW_ROUND,
            "draw_tile":    GameEvent.DRAW_TILE,
            "discard_tile": GameEvent.DISCARD_TILE,
            "chi":          GameEvent.CHI,
            "pon":          GameEvent.PON,
            "kan":          GameEvent.KAN,
            "an_kan":       GameEvent.AN_KAN,
            "add_kan":      GameEvent.ADD_KAN,
            "liqi":         GameEvent.RIICHI,
            "hu":           GameEvent.TSUMO,   # 需根据 data 区分 tsumo/ron
            "liuju":        GameEvent.LIUJU,
            "game_start":   GameEvent.GAME_START,
            "game_end":     GameEvent.GAME_END,
            "update_left_count": GameEvent.TILE_COUNT,
        }

        event = event_map.get(msg_name)
        if event:
            self._event_bus.publish(event, state=state, msg_name=msg_name)

    def _on_draw_tile(self, event, data: dict):
        """摸牌 → AI 决策"""
        if not self._auto_mode or self._listen_only:
            return

        state = data.get("state")
        if not state or not state.in_game:
            return

        hand = state.players[state.self_seat].hand
        if state.last_action == "draw" and len(hand) > 13:
            self.ai.on_state_update(state)
            decision = self.ai.decide_discard(state)
            self._event_bus.publish(
                __import__("core.events", fromlist=["GameEvent"]).GameEvent.AI_DECISION,
                action=decision
            )

    def _on_discard_tile(self, event, data: dict):
        """对手出牌 → 鸣牌检测"""
        if not self._auto_mode or self._listen_only:
            return

        state = data.get("state")
        if not state or not state.in_game:
            return

        # 通知 AI 更新状态
        self.ai.on_state_update(state)

        # TODO: 检测鸣牌按钮可见性后触发鸣牌决策

    def _on_ai_decision(self, event, data: dict):
        """AI 决策 → 执行"""
        if self._listen_only:
            return

        action = data.get("action")
        if action:
            self.executor.execute(action)

    def _on_toggle_auto(self, event, data: dict):
        self._auto_mode = not self._auto_mode
        from utils.log import Logger
        Logger.info(f"Auto mode: {'ON' if self._auto_mode else 'OFF'}")

    def _on_kill_switch(self, event, data: dict):
        self._running = False
        from utils.log import Logger
        Logger.info("KILL SWITCH activated")
