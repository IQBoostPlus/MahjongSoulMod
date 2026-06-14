"""
核心基础设施 — 事件总线 + 应用上下文
"""

from .events import EventBus, GameEvent
from .context import AppContext

__all__ = ["EventBus", "GameEvent", "AppContext"]
