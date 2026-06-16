"""
mitmproxy 插件脚本

拦截雀魂 WebSocket 消息:
1. 解码 liqi 协议二进制消息
2. 传递给 GameTracker 更新牌局状态
3. 通过 EventBus 触发 AI 决策和动作执行

用法: mitmdump -s addons.py --listen-port 8080
"""

import sys
import os
import time

# ═══════════════════════════════════════════════════════════════
#  路径修复: 确保能找到项目模块
#  两种情况:
#    A. 源码运行: addon.py 在 mitm/ 下, 项目根在上一级
#    B. EXE 运行:  addon.py 在 exe 同级, 模块在 _internal/ 下
# ═══════════════════════════════════════════════════════════════

_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))

# 情况 B: PyInstaller 打包 — _internal 包含所有模块
# 注意: 只加 _internal 本身, 不要加子目录!
# 否则 cv2/utils/ 等库会遮蔽我们的 utils/ 包
_internal = os.path.join(_ADDON_DIR, "_internal")
if os.path.isdir(_internal):
    if _internal not in sys.path:
        sys.path.insert(0, _internal)

# 情况 A: 源码运行 — 项目根在上一级
_project_root = os.path.dirname(_ADDON_DIR)
if os.path.isfile(os.path.join(_project_root, "main.py")):
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

from mitmproxy import ctx, http
import json

from core.context import AppContext
from core.events import GameEvent
from proto import LiqiDecoder, MSG_NAMES_S2C
from utils.log import Logger


# ═══════════════════════════════════════════════════════════════
#  WebSocket 重连追踪器
# ═══════════════════════════════════════════════════════════════

class WSReconnectTracker:
    """
    跟踪 WebSocket 连接生命周期, 支持断线重连。

    特性:
      - 记录连接/断开时间
      - 指数退避重连间隔 (1s → 2s → 4s → ... → 30s max)
      - 断线期间保留游戏状态
      - 重连后通知 EventBus
    """

    MAX_BACKOFF = 30.0       # 最大重连间隔 (秒)
    BASE_BACKOFF = 1.0       # 初始重连间隔 (秒)

    def __init__(self):
        self._connected = False
        self._connection_count = 0
        self._disconnect_count = 0
        self._last_connect_time = 0.0
        self._last_disconnect_time = 0.0
        self._current_backoff = self.BASE_BACKOFF
        self._total_disconnect_duration = 0.0
        self._active_ws_flows: set = set()
        self._game_state_snapshot: dict = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def connection_count(self) -> int:
        return self._connection_count

    @property
    def disconnect_count(self) -> int:
        return self._disconnect_count

    @property
    def total_downtime(self) -> float:
        return self._total_disconnect_duration

    def on_connect(self, flow_id=None):
        """WebSocket 连接建立"""
        now = time.time()
        was_disconnected = not self._connected

        self._connected = True
        self._connection_count += 1
        self._last_connect_time = now

        if flow_id:
            self._active_ws_flows.add(flow_id)

        if was_disconnected and self._disconnect_count > 0:
            downtime = now - self._last_disconnect_time
            self._total_disconnect_duration += downtime
            Logger.info(
                f"[WS] Reconnected (attempt #{self._disconnect_count}, "
                f"downtime: {downtime:.1f}s, total: {self._total_disconnect_duration:.1f}s)"
            )
            # 重置退避 (成功重连)
            self._current_backoff = self.BASE_BACKOFF

            # 通知事件总线
            try:
                ctx = AppContext.get()
                if ctx and ctx.event_bus:
                    ctx.event_bus.publish(
                        GameEvent.WS_RECONNECTED,
                        downtime=downtime,
                        total=self._total_disconnect_duration,
                    )
            except Exception:
                pass
        else:
            Logger.info(f"[WS] Connected (connection #{self._connection_count})")

    def on_disconnect(self, flow_id=None):
        """WebSocket 连接断开"""
        now = time.time()
        was_connected = self._connected

        self._connected = False
        self._disconnect_count += 1
        self._last_disconnect_time = now

        if flow_id and flow_id in self._active_ws_flows:
            self._active_ws_flows.discard(flow_id)

        if was_connected and self._connection_count > 0:
            session_duration = now - self._last_connect_time
            Logger.warning(
                f"[WS] Disconnected (connection #{self._connection_count}, "
                f"session: {session_duration:.1f}s, backoff: {self._current_backoff:.1f}s)"
            )

            # 保存游戏状态快照
            try:
                ctx = AppContext.get()
                if ctx and ctx.tracker:
                    self._game_state_snapshot = {
                        "tracker_state": str(ctx.tracker.state)[:500],
                        "timestamp": now,
                    }
            except Exception:
                pass

            # 通知事件总线
            try:
                ctx = AppContext.get()
                if ctx and ctx.event_bus:
                    ctx.event_bus.publish(
                        GameEvent.WS_DISCONNECTED,
                        reason="connection_closed",
                        backoff=self._current_backoff,
                    )
            except Exception:
                pass

            # 更新退避
            self._current_backoff = min(
                self._current_backoff * 2,
                self.MAX_BACKOFF,
            )
        else:
            self._connected = False

    def get_backoff(self) -> float:
        """获取当前重连等待时间"""
        return self._current_backoff

    def reset(self):
        """重置追踪器状态"""
        self._current_backoff = self.BASE_BACKOFF
        self._active_ws_flows.clear()
        self._game_state_snapshot = None

    @property
    def game_state_snapshot(self) -> dict:
        """断线前的游戏状态快照"""
        return self._game_state_snapshot


# 全局单例
_reconnect_tracker = WSReconnectTracker()


# ═══════════════════════════════════════════════════════════════
#  MajsoulAddon
# ═══════════════════════════════════════════════════════════════

class MajsoulAddon:
    """
    mitmproxy 主插件 — 使用共享 AppContext 组件

    兼容 mitmproxy 12.x API:
      - websocket_start(flow):    WebSocket 连接建立
      - websocket_message(flow):  接收 WebSocketMessage
      - websocket_end(flow):      连接关闭
      - websocket_error(flow):    连接错误

    WebSocket 生命周期:
      websocket_start → websocket_message* → websocket_end
    """

    def __init__(self):
        self._ctx = AppContext.get()
        Logger.info("MajsoulAddon initialized (shared context)")

    # ── WebSocket 生命周期 ──

    def websocket_start(self, flow):
        """WebSocket 连接建立"""
        flow_id = None
        try:
            flow_id = flow.id
        except AttributeError:
            pass

        # 只关注雀魂服务器的 WebSocket
        if not self._is_majsoul_ws(flow):
            return

        _reconnect_tracker.on_connect(flow_id)
        Logger.info(f"[WS] New connection to game server")

    def websocket_message(self, flow):
        """
        处理 WebSocket 消息

        mitmproxy 12.x: flow 是 WebSocketMessage 对象
          - flow.from_client: bool
          - flow.content: bytes
        """
        try:
            data = flow.content
        except AttributeError:
            # 兼容旧版: flow.messages[-1]
            if not flow.messages:
                return
            msg = flow.messages[-1]
            data = msg.content
            is_from_server = msg.from_client is False
            if is_from_server:
                return

        # 旧版 flow.from_client 检查
        try:
            if flow.from_client:
                return
        except AttributeError:
            pass

        if data is None or len(data) < 2:
            return

        # 解码 liqi 协议 (两层: Wrapper + 内层消息)
        parsed = LiqiDecoder.decode_message(data)
        if parsed is None or not parsed.get("name"):
            return

        msg_name = parsed["name"]
        msg_data = parsed["data"]

        Logger.debug(f"WS < {msg_name} ({len(data)} bytes)")

        # 传递给共享的 GameTracker (自动通过 EventBus 广播)
        self._ctx.tracker.on_game_event(msg_name, msg_data)

    def websocket_end(self, flow):
        """WebSocket 连接关闭"""
        if not self._is_majsoul_ws(flow):
            return

        flow_id = None
        try:
            flow_id = flow.id
        except AttributeError:
            pass

        _reconnect_tracker.on_disconnect(flow_id)

        # 检测是否异常断开 (非正常游戏结束)
        close_code = None
        try:
            close_code = flow.close_code
        except AttributeError:
            pass

        if close_code and close_code != 1000:
            Logger.warning(
                f"[WS] Abnormal close (code={close_code}), "
                f"client may reconnect (backoff: {_reconnect_tracker.get_backoff():.1f}s)"
            )
        else:
            Logger.info("[WS] Connection closed")

    def websocket_error(self, flow):
        """WebSocket 连接错误"""
        if not self._is_majsoul_ws(flow):
            return

        error_msg = ""
        try:
            error_msg = str(flow.error)
        except AttributeError:
            error_msg = "unknown error"

        Logger.error(f"[WS] Error: {error_msg}")

        flow_id = None
        try:
            flow_id = flow.id
        except AttributeError:
            pass
        _reconnect_tracker.on_disconnect(flow_id)

    # ── HTTP 请求过滤 ──

    def request(self, flow):
        """过滤非雀魂流量 (兼容 mitmproxy 12.x)"""
        try:
            host = flow.request.pretty_host
            if "mahjongsoul" in host or "maj-soul" in host:
                Logger.debug(f"HTTP → {host}")
        except Exception:
            pass  # 忽略 request 处理中的任何错误

    # ── 内部 ──

    @staticmethod
    def _is_majsoul_ws(flow) -> bool:
        """判断 WebSocket 是否是雀魂服务器"""
        try:
            # 检查请求 URL
            url = ""
            if hasattr(flow, 'request') and flow.request:
                url = flow.request.pretty_url or ""
            elif hasattr(flow, 'url'):
                url = flow.url or ""

            majsoul_hosts = [
                "mahjongsoul", "maj-soul", "majsoul",
                "game.mahjongsoul.com", "gateway",
            ]
            for host in majsoul_hosts:
                if host.lower() in url.lower():
                    return True
        except Exception:
            pass
        return True  # 默认处理 (避免漏消息)


# mitmproxy 需要的入口
addons = [MajsoulAddon]

