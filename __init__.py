"""
雀魂 (Mahjong Soul) 自动打牌 MOD
基于 MITM 代理架构: WebSocket 拦截 → Protobuf 解码 → AI 决策 → 鼠标模拟

架构:
  游戏客户端 ──WebSocket──► 服务器
                │
          mitmproxy 拦截
                │
          ┌─────┘
          ▼
     liqi 协议解码器 → GameState → AI 引擎 → 动作执行器 → pyautogui
"""

__version__ = "2.0.0"
__author__ = "IQBoostPlus"
