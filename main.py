#!/usr/bin/env python3
"""
雀魂自动打牌 MOD - 主入口

使用方式:
  1. 完整模式 (mitmproxy + AI + 自动操作):
     python main.py

  2. 仅监听模式 (只显示牌局信息, 不自动操作):
     python main.py --listen-only

  3. 命令行模式:
     python main.py --cli

要求:
  - Python 3.10+
  - pip install mitmproxy pyautogui pygetwindow

工作原理:
  1. 启动 mitmproxy 作为系统代理
  2. 拦截雀魂 (mahjong-soul.com) 的 WebSocket 连接
  3. 解码 liqi 协议 → 重建完整牌局状态
  4. AI 引擎分析 → 最佳决策
  5. 通过 pyautogui 模拟鼠标操作
"""

import argparse
import os
import sys
import threading
import time
import signal
import subprocess
from pathlib import Path

# 确保项目目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.log import Logger
from config import cfg
from game_state import GameTracker
from ai import AIDecisionMaker
from action import ActionExecutor
from proto import LiqiDecoder


class MajsoulAutoMod:
    """
    雀魂自动打牌 MOD 主控制器

    协调各子系统:
      - mitmproxy → 网络拦截
      - GameTracker → 状态追踪
      - AIDecisionMaker → AI 决策
      - ActionExecutor → 动作执行
    """

    def __init__(self, listen_only: bool = False):
        self.listen_only = listen_only
        self.running = False
        self._mitm_process = None

        # 组件
        self.tracker = GameTracker()
        self.ai = AIDecisionMaker()
        self.executor = ActionExecutor()

        # 注册状态回调
        self.tracker.add_callback(self._on_state_update)

        Logger.info("=" * 50)
        Logger.info("  雀魂自动打牌 MOD v2.0")
        Logger.info(f"  模式: {'监听' if listen_only else '自动'}")
        Logger.info("=" * 50)

    def start(self):
        """启动 MOD"""
        self.running = True

        # 启动 mitmproxy
        self._start_mitmproxy()

        Logger.info("MOD 已启动")
        Logger.info("请在浏览器中设置代理: 127.0.0.1:8080")
        Logger.info("或通过启动脚本自动启动浏览器")

        # 主循环
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            Logger.info("收到退出信号")
        finally:
            self.stop()

    def stop(self):
        """停止 MOD"""
        self.running = False
        self._stop_mitmproxy()
        Logger.info("MOD 已停止")

    def _start_mitmproxy(self):
        """启动 mitmproxy 后台进程"""
        port = cfg.get("proxy_port", 8080)
        web_port = cfg.get("mitm_web_port", 8081)

        addon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "mitm", "addons.py"
        )

        try:
            self._mitm_process = subprocess.Popen(
                [
                    "mitmdump",
                    "-s", addon_path,
                    "--listen-port", str(port),
                    "--web-port", str(web_port),
                    "--set", "block_global=false",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            Logger.info(f"mitmproxy started on port {port} (web: {web_port})")
        except FileNotFoundError:
            Logger.error(
                "mitmproxy not found! Install: pip install mitmproxy"
            )
            Logger.info("Running in debug mode (no network capture)")

    def _stop_mitmproxy(self):
        """停止 mitmproxy"""
        if self._mitm_process:
            self._mitm_process.terminate()
            try:
                self._mitm_process.wait(timeout=5)
            except:
                self._mitm_process.kill()
            self._mitm_process = None
            Logger.info("mitmproxy stopped")

    def _on_state_update(self, msg_name: str, state):
        """游戏状态更新回调"""
        if not state.in_game:
            return

        try:
            # 更新 AI 策略
            self.ai.on_state_update(state)

            # 自动模式: 触发决策
            if not self.listen_only:
                self._auto_decision(state)

        except Exception as e:
            Logger.error(f"Decision error: {e}")

    def _auto_decision(self, state):
        """自动决策和执行"""
        # 检测需要决策的场景
        hand = state.players[state.self_seat].hand

        # 刚摸牌后
        if state.last_action == "draw" and len(hand) > 13:
            decision = self.ai.decide_discard(state)
            self.executor.execute(decision)

        # 对手出牌后可鸣牌
        if state.last_action == "discard" and len(hand) <= 13:
            # TODO: 检测鸣牌按钮是否存在
            pass


def main():
    parser = argparse.ArgumentParser(
        description="雀魂自动打牌 MOD"
    )
    parser.add_argument(
        "--listen-only", action="store_true",
        help="仅监听对局信息, 不自动操作"
    )
    parser.add_argument(
        "--cli", action="store_true",
        help="命令行模式 (调试用)"
    )
    args = parser.parse_args()

    # 安装证书提示
    cert_path = os.path.join(
        str(Path.home()), ".mitmproxy", "mitmproxy-ca-cert.p12"
    )
    if not os.path.exists(cert_path):
        Logger.info("首次运行需要安装 mitmproxy CA 证书")
        Logger.info("请信任该证书以拦截 HTTPS 连接")
        Logger.info("证书生成在: " + cert_path)

    # 启动
    mod = MajsoulAutoMod(listen_only=args.listen_only)
    try:
        mod.start()
    except KeyboardInterrupt:
        pass
    finally:
        mod.stop()


if __name__ == "__main__":
    main()
