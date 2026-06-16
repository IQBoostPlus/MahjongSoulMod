"""
Dashboard 仪表盘服务器

基于 Python 内置 http.server 的轻量 Web 仪表盘。
通过 SSE (Server-Sent Events) 向浏览器实时推送游戏状态。

用法:
    server = DashboardServer(port=8082)
    server.start()
    # 浏览器打开 http://127.0.0.1:8082
"""

import json
import threading
import time
import queue
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, List

from utils.log import Logger


# ═══════════════════════════════════════════════════════════════
#  SSE 事件队列
# ═══════════════════════════════════════════════════════════════

class SSEBroker:
    """SSE 消息代理 — 管理所有连接的客户端"""

    def __init__(self, max_clients: int = 16):
        self._clients: List[queue.Queue] = []
        self._max_clients = max_clients
        self._lock = threading.Lock()

    def register(self) -> queue.Queue:
        """注册新客户端，返回其消息队列"""
        q = queue.Queue(maxsize=512)
        with self._lock:
            if len(self._clients) >= self._max_clients:
                # 移除最老的客户端
                old = self._clients.pop(0)
                old.put(None)  # 发送关闭信号
            self._clients.append(q)
        return q

    def unregister(self, q: queue.Queue):
        """注销客户端"""
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def broadcast(self, event_type: str, data: Dict[str, Any]):
        """向所有客户端广播事件"""
        message = json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }, ensure_ascii=False)
        with self._lock:
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(message)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._clients.remove(q)

    def close_all(self):
        """关闭所有连接"""
        with self._lock:
            for q in self._clients:
                q.put(None)
            self._clients.clear()


# ═══════════════════════════════════════════════════════════════
#  HTTP 请求处理器
# ═══════════════════════════════════════════════════════════════

class DashboardHandler(BaseHTTPRequestHandler):
    """仪表盘 HTTP 请求处理"""

    # 类变量 (由 DashboardServer 设置)
    broker: SSEBroker = None
    html_content: str = ""

    def log_message(self, format, *args):
        """禁用默认的 HTTP 日志 (使用 Logger)"""
        pass

    def do_GET(self):
        path = self.path.rstrip("?") if self.path else "/"

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/events":
            self._serve_sse()
        elif path == "/api/status":
            self._serve_status()
        elif path == "/api/ping":
            self._serve_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def _serve_html(self):
        """返回仪表盘 HTML"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(self.html_content.encode("utf-8"))

    def _serve_sse(self):
        """SSE 事件流"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q = self.broker.register()
        try:
            # 发送初始连接事件
            self.wfile.write(f"data: {json.dumps({'type': 'connected', 'data': {}})}\n\n".encode())
            self.wfile.flush()

            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    # 心跳
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue

                if msg is None:  # 关闭信号
                    break

                self.wfile.write(f"data: {msg}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.broker.unregister(q)

    def _serve_status(self):
        """返回最新状态快照"""
        from core.context import AppContext
        ctx = AppContext.get()
        state = ctx.tracker.state

        status = {
            "auto_mode": ctx.auto_mode,
            "listen_only": getattr(ctx, '_listen_only', False),
            "in_game": state.in_game,
            "round_wind": state.round_wind,
            "round_number": state.round_number,
            "honba": state.honba,
            "dealer": state.dealer,
            "self_seat": state.self_seat,
            "left_tiles": state.left_tiles,
            "dora_indicator": state.dora_indicator,
            "last_action": state.last_action,
            "last_discard": state.last_discard,
            "players": [
                {
                    "seat": i,
                    "hand": p.hand if i == state.self_seat else [0] * len(p.hand),
                    "hand_count": len(p.hand),
                    "discards": p.discards[-20:] if p.discards else [],
                    "discards_count": p.discards_count,
                    "melds": [{"type": m.type.value, "tiles": m.tiles} for m in p.melds],
                    "is_liqi": p.is_liqi,
                    "is_menzen": p.is_menzen,
                    "score": p.score,
                }
                for i, p in enumerate(state.players)
            ],
            "deposits": state.deposits,
        }

        action_count = 0
        fail_count = 0
        if ctx.executor:
            action_count = getattr(ctx.executor, 'action_count', 0)
            fail_count = getattr(ctx.executor, 'fail_count', 0)

        status["executor"] = {
            "action_count": action_count,
            "fail_count": fail_count,
        }

        self._serve_json(status)

    def _serve_json(self, data):
        """返回 JSON 响应"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


# ═══════════════════════════════════════════════════════════════
#  DashboardServer
# ═══════════════════════════════════════════════════════════════

class DashboardServer:
    """仪表盘 HTTP 服务器"""

    def __init__(self, port: int = 8082):
        self._port = port
        self._broker = SSEBroker()
        self._httpd: Optional[HTTPServer] = None
        self._running = False

    @property
    def broker(self) -> SSEBroker:
        return self._broker

    def start(self):
        """启动仪表盘服务器 (后台线程)"""
        # 加载 HTML
        html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "dashboard.html")
        if os.path.isfile(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                DashboardHandler.html_content = f.read()
        else:
            DashboardHandler.html_content = self._fallback_html()

        DashboardHandler.broker = self._broker

        def _run():
            # 允许端口复用 (避免重启时 "Address already in use")
            HTTPServer.allow_reuse_address = True
            self._httpd = HTTPServer(("127.0.0.1", self._port), DashboardHandler)
            self._running = True
            Logger.info(f"Dashboard: http://127.0.0.1:{self._port}")
            try:
                self._httpd.serve_forever()
            except Exception:
                pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        # 等服务器就绪
        time.sleep(0.3)

    def stop(self):
        """停止服务器"""
        self._broker.close_all()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
        self._running = False

    def push_event(self, event_type: str, data: Dict[str, Any]):
        """推送事件到所有浏览器客户端"""
        self._broker.broadcast(event_type, data)

    @staticmethod
    def _fallback_html() -> str:
        """兜底 HTML (template 文件不存在时)"""
        return """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>雀魂 AutoMod</title></head>
<body><h1>Dashboard</h1><p>Template file not found.</p></body></html>"""
