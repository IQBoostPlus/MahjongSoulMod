"""
应用上下文 — 依赖注入容器

统一管理所有核心组件实例，支持两种数据源模式:
  - Vision (默认): 视觉识别管线 (DXcam + 模板匹配)
  - MITM (兼容): mitmproxy WebSocket 拦截

用法:
    # Vision 模式 (推荐)
    ctx = AppContext.create_vision()
    ctx.start_vision()

    # MITM 模式 (兼容)
    ctx = AppContext.get()

    # 获取单例
    ctx = AppContext.get()
    ctx.event_bus.subscribe(GameEvent.DRAW_TILE, my_handler)
"""

from typing import Optional, List

from core.events import EventBus, GameEvent
from utils.log import Logger


class AppContext:
    """
    全局应用上下文 — 依赖注入容器。

    Vision 模式:  使用 VisionPipeline + StateDiffer 作为数据源
    MITM 模式:    使用 mitmproxy addon + LiqiDecoder 作为数据源

    向后兼容: AppContext.get() 始终可用，返回 MITM 模式默认实例。
    """

    _instance: Optional["AppContext"] = None

    def __init__(self,
                 event_bus: Optional[EventBus] = None,
                 tracker=None,
                 ai=None,
                 executor=None,
                 dashboard=None,
                 vision_pipeline=None,
                 vision_processor=None,
                 button_detector=None):
        """
        依赖注入构造函数。

        所有参数可选 — None 时使用默认值。
        首次调用自动注册为全局单例。

        Args:
            event_bus: 事件总线 (None=自动创建)
            tracker: GameTracker 实例 (None=自动创建)
            ai: AIDecisionMaker 实例 (None=自动创建)
            executor: 动作执行器 (None=根据平台自动选择)
            dashboard: DashboardServer 实例 (None=自动创建)
            vision_pipeline: VisionPipeline 实例 (vision 模式)
            vision_processor: VisionEventProcessor 实例 (vision 模式)
            button_detector: ButtonDetector 实例
        """
        # 检测：空参调用 → 可能是旧代码的 AppContext() 误用
        all_none = all(x is None for x in [
            event_bus, tracker, ai, executor, dashboard,
            vision_pipeline, vision_processor, button_detector
        ])
        # 允许通过 _setup 内部调用（单例未创建时首次构造）
        has_instance = AppContext._instance is not None

        if has_instance and all_none:
            # 已经有过一个 context，空参构造是误用
            # 直接返回已有实例而不是报错，防止旧 MITM addon 崩溃
            Logger.debug("[AppContext] Reusing existing instance (empty constructor ignored)")

        self._event_bus = event_bus
        self._tracker = tracker
        self._ai = ai
        self._executor = executor
        self._dashboard = dashboard
        self._vision_pipeline = vision_pipeline
        self._vision_processor = vision_processor
        self._button_detector = button_detector

        # 状态
        self._auto_mode = True
        self._listen_only = False
        self._running = True

        # 延迟初始化标志
        self._setup_done = False

        # 为单例注册 (仅首次)
        if not has_instance:
            AppContext._instance = self

    # ── 初始化 (延迟到 get/create 时调用) ──

    def _ensure_setup(self):
        """确保组件已初始化 (幂等)"""
        if self._setup_done:
            return
        self._setup_done = True
        self._setup()

    def _setup(self):
        """初始化所有核心组件并连接事件"""
        from game_state.tracker import GameTracker
        from ai.engine import AIDecisionMaker
        from config import cfg

        # 基础设施
        if self._event_bus is None:
            self._event_bus = EventBus()

        # 领域组件 (共享单例)
        if self._tracker is None:
            self._tracker = GameTracker()

        if self._ai is None:
            self._ai = AIDecisionMaker()

        # 执行器: 根据平台 + vision 可用性自动选择
        if self._executor is None:
            self._executor = self._create_executor()

        # Dashboard
        if self._dashboard is None:
            self._dashboard = self._create_dashboard()

        # Button detector (vision 模式需要)
        if self._vision_pipeline is not None and self._button_detector is None:
            try:
                from vision.buttons import ButtonDetector
                self._button_detector = ButtonDetector()
            except ImportError:
                pass

        # Tracker 回调 → EventBus 事件
        self._tracker.add_callback(self._on_tracker_update)

        # 游戏事件 → AI 决策触发
        self._event_bus.subscribe(GameEvent.DRAW_TILE, self._on_draw_tile)
        self._event_bus.subscribe(GameEvent.DISCARD_TILE, self._on_discard_tile)

        # AI 决策 → 动作执行
        self._event_bus.subscribe(GameEvent.AI_DECISION, self._on_ai_decision)

        # 控制事件
        self._event_bus.subscribe(GameEvent.TOGGLE_AUTO, self._on_toggle_auto)
        self._event_bus.subscribe(GameEvent.KILL_SWITCH, self._on_kill_switch)

        # Dashboard 推送
        if self._dashboard:
            self._event_bus.on_any(self._on_dashboard_push)

        # 全局事件日志 (调试)
        self._event_bus.on_any(self._on_any_event)

    # ── 工厂方法 ──

    @classmethod
    def create(cls) -> "AppContext":
        """首次创建 (内部使用), 返回单例"""
        if cls._instance is not None:
            return cls._instance

        instance = object.__new__(cls)
        instance._event_bus = instance._tracker = instance._ai = None
        instance._executor = instance._dashboard = None
        instance._vision_pipeline = instance._vision_processor = None
        instance._button_detector = None
        instance._auto_mode = True
        instance._listen_only = False
        instance._running = True
        instance._setup_done = False
        cls._instance = instance
        return instance

    @classmethod
    def get(cls) -> "AppContext":
        """获取单例 — 未创建时自动创建 (MITM 模式)"""
        if cls._instance is None:
            return cls.create()
        # 确保 setup
        cls._instance._ensure_setup()
        return cls._instance

    @classmethod
    def create_vision(cls,
                       capture_backend: str = "auto",
                       fps: int = 10,
                       verify_actions: bool = True) -> "AppContext":
        """
        创建 Vision 模式的 AppContext。

        构建完整的视觉管线:
          Capture → Regions → TileRecognizer → Pipeline → Differ → Processor → Tracker

        Args:
            capture_backend: "auto" | "dxcam" | "pil" | "adb"
            fps: 目标帧率
            verify_actions: 是否启用闭环验证

        Returns:
            AppContext 实例 (已注册为单例)
        """
        from config import cfg

        # 1. 采集后端
        from vision.capture import CaptureConfig, CaptureBackend, CaptureFactory, DXCAMCapture, PILCapture

        backend_map = {"auto": "auto", "dxcam": "dxcam", "pil": "pil", "adb": "adb"}
        backend_str = backend_map.get(capture_backend, "auto")

        config = CaptureConfig(
            backend=CaptureBackend(backend_str),
            target_fps=fps,
            output_color="BGR",
        )
        capture = CaptureFactory.create(config)
        capture.start()

        # 2. ROI 布局 (从窗口分辨率选择)
        from vision.regions import RegionConfig
        regions = RegionConfig.get_for_window(1920, 1080)  # 默认, 运行时动态更新

        # 3. 牌面识别器
        from vision.tiles import TileRecognizer
        tiles = TileRecognizer(threshold=cfg.get("vision_tile_threshold", 0.80))

        # 4. 按钮检测器
        from vision.buttons import ButtonDetector
        buttons = ButtonDetector()

        # 5. 管线
        from vision.pipeline import VisionPipeline
        pipeline = VisionPipeline(capture, regions, tiles, buttons)

        # 6. 差分器
        from vision.differ import StatefulDiffer
        differ = StatefulDiffer(confirmation_frames=2)

        # 7. 处理器 (延迟绑定 tracker — 在 _ensure_setup 之后)
        from vision.processor import VisionEventProcessor
        processor = VisionEventProcessor()  # tracker/event_bus 后续绑定

        # 8. 动作执行器
        from vision.executor import VisionActionExecutor
        from vision.verifier import ActionVerifier

        verifier = ActionVerifier(
            pipeline=pipeline,
            button_detector=buttons,
            max_retries=cfg.get("vision_max_retries", 3),
        ) if verify_actions else None

        executor = VisionActionExecutor(
            pipeline=pipeline,
            button_detector=buttons,
            verifier=verifier,
            differ=differ,
        )

        # 9. 构建上下文
        if cls._instance is not None:
            cls._instance.stop()

        instance = object.__new__(cls)
        instance._event_bus = EventBus()
        instance._tracker = None  # _setup 中创建
        instance._ai = None
        instance._executor = executor
        instance._dashboard = None
        instance._vision_pipeline = pipeline
        instance._vision_processor = processor
        instance._button_detector = buttons
        instance._auto_mode = True
        instance._listen_only = False
        instance._running = True
        instance._setup_done = False

        # 注册单例
        cls._instance = instance

        # 确保基础组件初始化
        instance._ensure_setup()

        # 绑定 processor 到 tracker
        processor._tracker = instance._tracker
        processor._event_bus = instance._event_bus

        Logger.info("[AppContext] Vision mode initialized")
        return instance

    @classmethod
    def reset(cls) -> None:
        """重置上下文 (测试用)"""
        if cls._instance:
            try:
                cls._instance.stop()
            except Exception:
                pass
        cls._instance = None

    # ── 组件初始化 ──

    def _create_executor(self):
        """根据配置创建对应平台的执行器"""
        from config import cfg
        platform = cfg.get("platform", "desktop")

        # Vision 模式优先
        if self._vision_pipeline is not None:
            from vision.executor import VisionActionExecutor
            from vision.verifier import ActionVerifier

            verifier = ActionVerifier(
                pipeline=self._vision_pipeline,
                button_detector=self._button_detector,
                max_retries=cfg.get("vision_max_retries", 3),
            ) if cfg.get("vision_verify_actions", True) else None

            return VisionActionExecutor(
                pipeline=self._vision_pipeline,
                button_detector=self._button_detector,
                verifier=verifier,
            )

        if platform == "mobile":
            from action.mobile_executor import MobileActionExecutor
            executor = MobileActionExecutor(
                device_id=cfg.get("adb_device_id", None)
            )
            if executor.connect():
                Logger.info("[AppContext] Mobile executor connected")
            else:
                Logger.warning("[AppContext] Mobile executor: no device found, running in debug mode")
            return executor
        else:
            # 桌面端: 优先 Airtest, 回退 OpenCV
            try:
                from action.airtest_executor import AirtestActionExecutor
                Logger.info("[AppContext] Using Airtest image recognition engine")
                return AirtestActionExecutor()
            except ImportError:
                from action.executor import ActionExecutor
                Logger.info("[AppContext] Using OpenCV template matching")
                return ActionExecutor()

    def _create_dashboard(self):
        """创建仪表盘服务器"""
        from config import cfg
        try:
            from dashboard.server import DashboardServer
            port = cfg.get("dashboard_port", 8082)
            server = DashboardServer(port)
            server.start()
            Logger.info(f"[AppContext] Dashboard started on port {port}")
            return server
        except Exception as e:
            Logger.warning(f"[AppContext] Dashboard not available: {e}")
            return None

    # ── Vision 模式控制 ──

    def start_vision(self, fps: int = 10) -> bool:
        """
        启动视觉处理后台循环。

        Args:
            fps: 目标帧率

        Returns:
            True 成功, False (无 vision pipeline)
        """
        if self._vision_pipeline is None:
            Logger.warning("[AppContext] No vision pipeline — call create_vision() first")
            return False

        from vision.differ import StatefulDiffer
        differ = StatefulDiffer(confirmation_frames=2)

        self._vision_processor.start_loop(self._vision_pipeline, differ, fps)
        Logger.info(f"[AppContext] Vision loop started ({fps} FPS)")
        return True

    def stop_vision(self):
        """停止视觉处理循环"""
        if self._vision_processor:
            self._vision_processor.stop_loop()
        if self._vision_pipeline:
            self._vision_pipeline.stop()

    # ── 属性 ──

    @property
    def event_bus(self) -> EventBus:
        self._ensure_setup()
        return self._event_bus

    @property
    def tracker(self):
        self._ensure_setup()
        return self._tracker

    @property
    def ai(self):
        self._ensure_setup()
        return self._ai

    @property
    def executor(self):
        self._ensure_setup()
        return self._executor

    @property
    def dashboard(self):
        self._ensure_setup()
        return self._dashboard

    @property
    def vision_pipeline(self):
        return self._vision_pipeline

    @property
    def vision_processor(self):
        return self._vision_processor

    @property
    def auto_mode(self) -> bool:
        return self._auto_mode

    @property
    def running(self) -> bool:
        return self._running

    def stop(self):
        """停止所有子系统"""
        self._running = False
        if self._vision_processor:
            try:
                self._vision_processor.stop_loop()
            except Exception:
                pass
        if self._vision_pipeline:
            try:
                self._vision_pipeline.stop()
            except Exception:
                pass
        if self._dashboard:
            try:
                self._dashboard.stop()
            except Exception:
                pass

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

        # 跳过自家舍牌 (不需要鸣牌判断)
        if state.last_discard_seat == state.self_seat:
            return

        # 更新 AI 策略
        self._ai.on_state_update(state)

        # 鸣牌决策
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
        status = "ON" if self._auto_mode else "OFF"
        msg = f"[Control] Auto mode: {status}"
        Logger.info(msg)
        # 终端 + 屏幕提示
        print(f"\n{'='*40}\n  {msg}\n{'='*40}\n")
        self._show_toast(f"Auto {status}")

    def _on_kill_switch(self, event: GameEvent, data: dict):
        self._running = False
        self._auto_mode = False
        msg = "[Control] KILL SWITCH — all automation stopped"
        Logger.info(msg)
        print(f"\n{'='*40}\n  {msg}\n{'='*40}\n")
        self._show_toast("KILL SWITCH")

    @staticmethod
    def _show_toast(msg: str):
        """显示简短屏幕提示 (非阻塞)"""
        try:
            import threading
            def _toast():
                try:
                    import tkinter as tk
                    root = tk.Tk()
                    root.overrideredirect(True)
                    root.attributes('-topmost', True)
                    root.geometry(f'+{root.winfo_screenwidth()//2-120}+{root.winfo_screenheight()//2-30}')
                    lbl = tk.Label(root, text=msg, font=('Microsoft YaHei', 16, 'bold'),
                                   fg='white', bg='#333333', padx=30, pady=10)
                    lbl.pack()
                    root.after(1500, root.destroy)
                    root.mainloop()
                except Exception:
                    pass
            threading.Thread(target=_toast, daemon=True).start()
        except Exception:
            pass

    def _on_any_event(self, event: GameEvent, data: dict):
        """所有事件的调试日志"""
        Logger.debug(f"[EventBus] {event.value}")

    def _on_dashboard_push(self, event: GameEvent, data: dict):
        """推送事件到仪表盘 SSE"""
        if not self._dashboard:
            return
        try:
            payload = {"msg_name": event.value}
            action = data.get("action")
            if action:
                payload["action"] = action.action.value
                payload["tile"] = action.tile
                payload["reason"] = f"shanten={getattr(action, 'shanten', '?')}"

            if event == GameEvent.AI_DECISION:
                self._dashboard.push_event("ai_decision", payload)
            elif event == GameEvent.ACTION_DONE:
                self._dashboard.push_event("action_done", payload)
            elif event == GameEvent.ACTION_FAILED:
                self._dashboard.push_event("action_failed", payload)
            elif event == GameEvent.TOGGLE_AUTO:
                self._dashboard.push_event("control", {"auto_mode": self._auto_mode})
            elif event == GameEvent.KILL_SWITCH:
                self._dashboard.push_event("control", {"auto_mode": False, "kill": True})
            else:
                self._dashboard.push_event("game_event", payload)
        except Exception:
            pass
