"""
mitmproxy 插件脚本

拦截雀魂 WebSocket 消息:
1. 解码 liqi 协议二进制消息
2. 传递给 GameTracker 更新牌局状态
3. 通过 EventBus 触发 AI 决策和动作执行

用法: mitmdump -s addons.py --listen-port 8080
"""

from mitmproxy import ctx, http, websocket
import json

from core.context import AppContext
from proto import LiqiDecoder, MSG_NAMES_S2C
from utils.log import Logger


class MajsoulAddon:
    """mitmproxy 主插件 — 使用共享 AppContext 组件"""

    def __init__(self):
        self._ctx = AppContext.get()
        Logger.info("MajsoulAddon initialized (shared context)")

    def websocket_message(self, flow: websocket.WebSocketFlow):
        """处理 WebSocket 消息"""
        if not flow.messages:
            return

        msg = flow.messages[-1]
        is_from_server = msg.from_client is False
        data = msg.content

        if data is None or len(data) < 2:
            return

        # 只处理服务端→客户端的消息
        if not is_from_server:
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

    def websocket_end(self, flow: websocket.WebSocketFlow):
        """WebSocket 连接关闭"""
        Logger.info("WebSocket connection closed — game may have ended")

    # ── HTTP 请求过滤 (可选) ──

    def request(self, flow: http.HTTPFlow):
        """过滤非雀魂流量"""
        host = flow.request.pretty_host
        if "mahjongsoul" in host or "maj-soul" in host:
            Logger.debug(f"HTTP → {host}")


# mitmproxy 需要的入口
addons = [MajsoulAddon]
