"""
动作执行系统 — 将 AI 决策转换为游戏内操作

支持:
  - AirtestActionExecutor: 桌面端 (Airtest 图像识别 + pyautogui 鼠标)
  - ActionExecutor:         桌面端 (OpenCV 模板匹配 + pyautogui 鼠标)
  - MobileActionExecutor:   移动端 (ADB 触屏模拟)
"""

from .executor import ActionExecutor, ButtonTemplate
from .mobile_executor import MobileActionExecutor, MobileLayout, ADB
from .airtest_executor import AirtestActionExecutor

__all__ = [
    "AirtestActionExecutor",
    "ActionExecutor",
    "ButtonTemplate",
    "MobileActionExecutor",
    "MobileLayout",
    "ADB",
]
