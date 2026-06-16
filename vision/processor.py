"""
Vision Event Processor — 视觉事件 → GameTracker 桥接器

将 StateDiffer 输出的 VisionEvent 转换为 GameTracker.on_game_event() 调用。
这与 MITM addon 使用完全相同的接口, 确保 AI 引擎零改动。

后台循环:
  Pipeline.process_frame() → Differ.diff() → Processor.process_events()
                                                    ↓
                                          GameTracker.on_game_event(msg_name, data)
                                                    ↓
                                          (现有 EventBus → AI → Action 链路不变)

用法:
    processor = VisionEventProcessor(tracker, event_bus)
    processor.process_events(events)
    # 或启动后台循环:
    processor.run_loop(pipeline, differ, fps=10)
"""

import time
import threading
from typing import List, Optional

from utils.log import Logger


class VisionEventProcessor:
    """
    将 VisionEvent 列表桥接到 GameTracker。

    注意:
      - 某些视觉事件需要数据适配 (vision → GameTracker 格式)
      - 并非所有 MITM 事件都能从视觉推断, 缺失的填默认值
      - GameTracker 在收到事件后会自动触发 EventBus → AI 决策链路
    """

    def __init__(self, tracker=None, event_bus=None):
        """
        Args:
            tracker: GameTracker 实例 (None = 延迟从 AppContext 获取)
            event_bus: EventBus 实例 (None = 延迟获取)
        """
        self._tracker = tracker
        self._event_bus = event_bus
        self._last_discard_seat = -1

        # 统计
        self._event_count = 0
        self._error_count = 0
        self._running = False

    # ── 属性 ──

    @property
    def tracker(self):
        """延迟获取 GameTracker (处理初始化顺序问题)"""
        if self._tracker is None:
            from core.context import AppContext
            self._tracker = AppContext.get().tracker
        return self._tracker

    @property
    def event_bus(self):
        """延迟获取 EventBus"""
        if self._event_bus is None:
            from core.context import AppContext
            self._event_bus = AppContext.get().event_bus
        return self._event_bus

    # ── 主接口 ──

    def process_events(self, events: List["VisionEvent"]):
        """
        处理一批 VisionEvent。

        每个事件映射到 GameTracker.on_game_event() 调用。
        事件数据格式与 MITM LiqiDecoder 输出兼容。
        """
        for event in events:
            try:
                self._process_one(event)
                self._event_count += 1
            except Exception as e:
                self._error_count += 1
                Logger.debug(f"[VisionProc] Error processing {event.event_type}: {e}")

    def _process_one(self, event: "VisionEvent"):
        """处理单个事件 — 调用 GameTracker"""
        tracker = self.tracker

        # 直接调用 — tracker.on_game_event 内部通过反射路由到 _on_{msg_name}
        # 事件类型命名与 GameTracker 内部方法名一致
        internal_msg = self._map_event_type(event.event_type)

        try:
            tracker.on_game_event(internal_msg, event.data)
        except Exception as e:
            Logger.debug(f"[VisionProc] Tracker rejected {internal_msg}: {e}")

        # 追踪最后舍牌人 (用于 AI 鸣牌判断)
        if internal_msg == "discard_tile":
            self._last_discard_seat = event.data.get("seat", -1)
            # 同步到 tracker.state
            state = tracker.state
            if state:
                state.last_discard = event.data.get("tile", -1)
                state.last_discard_seat = self._last_discard_seat

    @staticmethod
    def _map_event_type(vision_type: str) -> str:
        """
        视觉事件类型 → GameTracker 内部消息名。

        大部分 1:1 对应, 少数需映射。
        """
        # 事件名映射表 (视觉 → tracker)
        mapping = {
            "game_start":        "game_start",
            "game_end":          "game_end",
            "new_round":         "new_round",
            "draw_tile":         "draw_tile",
            "discard_tile":      "discard_tile",
            "chi":               "chi",
            "pon":               "pon",
            "kan":               "kan",
            "an_kan":            "an_kan",
            "add_kan":           "add_kan",
            "liqi":              "liqi",
            "hu":                "hu",
            "liuju":             "liuju",
            "update_left_count": "update_left_count",
            # 视觉特有 — tracker 会忽略
            "game_start":        "game_start",
            "liqi_candidate":   None,  # 不送 tracker (仅提示)
        }

        mapped = mapping.get(vision_type, vision_type)
        if mapped is None:
            Logger.debug(f"[VisionProc] Skipping unmapped event: {vision_type}")
        return mapped or vision_type

    # ── 后台循环 ──

    def run_loop(self, pipeline, differ, fps: int = 10,
                 stop_event: threading.Event = None):
        """
        启动后台视觉处理循环。

        Args:
            pipeline: VisionPipeline 实例
            differ: StateDiffer 实例
            fps: 目标帧率
            stop_event: 外部停止信号 (None=使用 self._running)
        """
        self._running = True
        interval = 1.0 / max(1, fps)

        Logger.info(f"[VisionProc] Loop started ({fps} FPS)")

        while self._running and (stop_event is None or not stop_event.is_set()):
            t0 = time.perf_counter()

            try:
                # 采集 + 识别
                frame = pipeline.process_frame()
                if frame is None:
                    time.sleep(interval)
                    continue

                # 差分 → 事件
                events = differ.diff(frame) if differ else []

                # 桥接 → GameTracker
                if events:
                    self.process_events(events)

            except Exception as e:
                Logger.error(f"[VisionProc] Loop error: {e}")

            # 帧率控制
            elapsed = time.perf_counter() - t0
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        Logger.info("[VisionProc] Loop stopped")

    def start_loop(self, pipeline, differ, fps: int = 10):
        """在后台线程启动处理循环"""
        self._stop_event = threading.Event()

        def _target():
            self.run_loop(pipeline, differ, fps, self._stop_event)

        t = threading.Thread(target=_target, daemon=True, name="VisionLoop")
        t.start()
        Logger.info(f"[VisionProc] Background thread started")
        return t

    def stop_loop(self):
        """停止后台循环"""
        self._running = False
        if hasattr(self, '_stop_event'):
            self._stop_event.set()

    # ── 状态 ──

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def error_count(self) -> int:
        return self._error_count

    def reset_stats(self):
        self._event_count = 0
        self._error_count = 0
