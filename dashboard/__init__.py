"""
仪表盘模块 — Web 前端可视化监控

提供:
  - DashboardServer: HTTP + SSE 实时推送服务器
  - SSEBroker: 客户端连接管理
"""

from .server import DashboardServer, SSEBroker

__all__ = ["DashboardServer", "SSEBroker"]
