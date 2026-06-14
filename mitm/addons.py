"""
mitmproxy 插件脚本

拦截雀魂 WebSocket 消息:
1. 解码 liqi 协议二进制消息
2. 传递给 GameTracker 更新牌局状态
3. 触发 AI 决策和动作执行

用法: mitmdump -s addons.py --listen-port 8080
"""

from mitmproxy import ctx, http, websocket
from mitmproxy.proxy import layers
import json

from proto import LiqiDecoder, MSG_NAMES_S2C
from game_state import GameTracker
from action import ActionExecutor
from ai import AIDecisionMaker
from utils.log import Logger


class MajsoulAddon:
    """mitmproxy 主插件"""

    def __init__(self):
        self.tracker = GameTracker()
        self.ai = AIDecisionMaker()
        self.executor = ActionExecutor()
        self._last_state = None

        # 注册状态更新回调
        self.tracker.add_callback(self._on_state_update)

        Logger.info("MajsoulAddon initialized")

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

        # 解码 liqi 协议
        parsed = LiqiDecoder.decode_message(data)
        if parsed is None or not parsed["name"]:
            return

        msg_name = parsed["name"]
        msg_data = parsed["data"]

        # 简化消息名
        short_name = MSG_NAMES_S2C.get(msg_name, msg_name)
        Logger.debug(f"WS < {short_name} ({len(data)} bytes)")

        # 传递给状态追踪器
        self.tracker.on_game_event(short_name, msg_data)

    def websocket_end(self, flow: websocket.WebSocketFlow):
        """WebSocket 连接关闭"""
        Logger.info("WebSocket connection closed")


# mitmproxy 需要的入口
addons = [MajsoulAddon]
