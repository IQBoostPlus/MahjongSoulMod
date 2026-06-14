#!/usr/bin/env python3
"""
雀魂自动打牌 MOD - 主入口

使用方式:
  1. 完整模式 (mitmproxy + AI + 自动操作):
     python main.py

  2. 仅监听模式 (只显示牌局信息, 不自动操作):
     python main.py --listen-only

  3. 命令行调试模式:
     python main.py --cli

要求:
  - Python 3.10+
  - pip install mitmproxy pyautogui pygetwindow pynput

工作原理:
  1. 启动 mitmproxy 作为系统代理
  2. 拦截雀魂 WebSocket → liqi 协议解码
  3. GameTracker 重建完整牌局状态
  4. AI 引擎分析 → 最佳决策
  5. ActionExecutor 通过 pyautogui 模拟鼠标操作
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
# PyInstaller 打包后使用 sys._MEIPASS，开发模式使用脚本所在目录
if getattr(sys, 'frozen', False):
    _BASE_DIR = sys._MEIPASS
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE_DIR)

# 外部文件目录 (exe 同级目录) — 用于配置文件、addon 脚本等
_EXTERNAL_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))

from core.context import AppContext
from core.events import GameEvent
from utils.log import Logger


class MajsoulAutoMod:
    """
    雀魂自动打牌 MOD 主控制器

    职责:
      - 启动/管理 mitmproxy 进程
      - 键盘快捷键监听
      - 主循环 (保活)
    """

    def __init__(self, listen_only: bool = False):
        self.listen_only = listen_only
        self._mitm_process = None
        self._keyboard_listener = None
        self._ctx = AppContext.get()

        self._ctx.set_listen_only(listen_only)

        Logger.info("=" * 50)
        Logger.info("  雀魂自动打牌 MOD v2.0")
        Logger.info(f"  模式: {'监听' if listen_only else '自动'}")
        Logger.info("=" * 50)

    def start(self):
        """启动 MOD"""
        # 启动 mitmproxy
        self._start_mitmproxy()

        # 启动快捷键监听 (非阻塞)
        self._start_hotkeys()

        Logger.info("MOD 已启动")
        Logger.info("请在浏览器中设置代理: 127.0.0.1:8080")
        Logger.info("按 F6 切换自动模式 | F7 紧急停止")

        # 主循环 — 保持进程存活
        try:
            while self._ctx.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            Logger.info("收到 Ctrl+C 退出信号")
        finally:
            self.stop()

    def stop(self):
        """停止 MOD"""
        self._ctx.stop()
        self._stop_hotkeys()
        self._stop_mitmproxy()
        Logger.info("MOD 已停止")

    # ── mitmproxy 进程管理 ──

    def _start_mitmproxy(self):
        """启动 mitmproxy 后台进程"""
        from config import cfg

        port = cfg.get("proxy_port", 8080)
        web_port = cfg.get("mitm_web_port", 8081)

        # 查找 addon 脚本: 优先 exe 同级目录的 addon.py，其次项目目录下的 mitm/addons.py
        addon_path = os.path.join(_EXTERNAL_DIR, "addon.py")
        if not os.path.isfile(addon_path):
            addon_path = os.path.join(_BASE_DIR, "mitm", "addons.py")
        if not os.path.isfile(addon_path):
            Logger.error(f"Addon script not found! Checked: {_EXTERNAL_DIR}/addon.py, {_BASE_DIR}/mitm/addons.py")
            Logger.info("将以调试模式运行 (无网络拦截)")
            return

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
            Logger.info(f"mitmproxy started on port {port} (web UI: {web_port})")
        except FileNotFoundError:
            Logger.error("mitmproxy not found! 请安装: pip install mitmproxy")
            Logger.info("将以调试模式运行 (无网络拦截)")

    def _stop_mitmproxy(self):
        """停止 mitmproxy"""
        if self._mitm_process:
            self._mitm_process.terminate()
            try:
                self._mitm_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._mitm_process.kill()
            self._mitm_process = None
            Logger.info("mitmproxy stopped")

    # ── 键盘快捷键 ──

    def _start_hotkeys(self):
        """启动全局热键监听"""
        try:
            from pynput import keyboard

            def on_press(key):
                try:
                    if key == keyboard.Key.f6:
                        self._ctx.event_bus.publish(GameEvent.TOGGLE_AUTO)
                    elif key == keyboard.Key.f7:
                        self._ctx.event_bus.publish(GameEvent.KILL_SWITCH)
                except Exception:
                    pass

            self._keyboard_listener = keyboard.Listener(on_press=on_press)
            self._keyboard_listener.daemon = True
            self._keyboard_listener.start()
            Logger.info("快捷键监听已启动 (F6=切换, F7=停止)")
        except ImportError:
            Logger.warning("pynput 未安装，快捷键不可用。安装: pip install pynput")

    def _stop_hotkeys(self):
        """停止热键监听"""
        if self._keyboard_listener:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
            self._keyboard_listener = None


def main():
    parser = argparse.ArgumentParser(description="雀魂自动打牌 MOD")
    parser.add_argument(
        "--listen-only", action="store_true",
        help="仅监听对局信息，不自动操作"
    )
    parser.add_argument(
        "--cli", action="store_true",
        help="命令行模式 (调试用)"
    )
    args = parser.parse_args()

    # CA 证书提示
    cert_dir = os.path.join(str(Path.home()), ".mitmproxy")
    if not os.path.exists(cert_dir):
        Logger.info("首次运行需要 mitmproxy CA 证书")
        Logger.info("启动后访问 http://mitm.it 下载并信任证书")

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
