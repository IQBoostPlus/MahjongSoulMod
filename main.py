#!/usr/bin/env python3
#
# 雀魂自动打牌 MOD - 主入口
#
# 使用方式:
#   1. Steam 模式:
#      MajsoulAutoMod.exe --steam
#
#   2. 网页模式:
#      MajsoulAutoMod.exe
#
#   3. 仅监听模式:
#      MajsoulAutoMod.exe --listen-only
#
# 工作原理:
#   1. 启动 mitmproxy 作为代理
#   2. 拦截雀魂 WebSocket → liqi 协议解码
#   3. GameTracker 重建完整牌局状态
#   4. AI 引擎分析 → 最佳决策
#   5. ActionExecutor 通过 pyautogui/ADB 模拟操作
#

import argparse
import os
import sys
import io

# ══════════════════════════════════════════════════════════
#  UTF-8 编码修复 — 必须在任何其他 import 之前执行
#  Windows 控制台默认 GBK，中文输出会乱码
# ══════════════════════════════════════════════════════════

def _fix_encoding():
    """强制 stdout/stderr 使用 UTF-8，解决 Windows 中文乱码"""
    # 0. 设置环境变量 (影响子进程和后续模块)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    if sys.platform != "win32":
        return

    # 1. 修改控制台代码页为 UTF-8 (65001)
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # 设置控制台输出代码页
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass

    # 2. 重新配置 Python 的 stdout/stderr wrapper
    for stream_name, stream in [("stdout", sys.stdout), ("stderr", sys.stderr)]:
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
            elif hasattr(stream, "buffer"):
                # 用 TextIOWrapper 替换
                new_stream = io.TextIOWrapper(
                    stream.buffer, encoding="utf-8", errors="replace"
                )
                setattr(sys, stream_name, new_stream)
        except Exception:
            pass

_fix_encoding()

import time
import signal
import subprocess
import threading
import webbrowser
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

    def __init__(self, listen_only: bool = False, force_steam: bool = False,
                 vision_mode: bool = True):
        self.listen_only = listen_only
        self._vision_mode = vision_mode
        self._mitm_process = None
        self._keyboard_listener = None

        # 根据模式创建上下文
        if vision_mode and not listen_only:
            self._ctx = AppContext.create_vision()
        else:
            self._ctx = AppContext.get()

        self._ctx.set_listen_only(listen_only)

        from config import cfg
        platform = cfg.get("platform", "desktop")
        browser_type = cfg.get("browser_type", "chrome")

        # --steam 参数强制覆盖配置
        if force_steam:
            cfg["browser_type"] = "steam"
            browser_type = "steam"

        Logger.info("=" * 50)
        Logger.info("  雀魂自动打牌 MOD v2.2")
        Logger.info(f"  模式: {'监听' if listen_only else '自动'}")
        Logger.info(f"  数据源: {'Vision (视觉识别)' if vision_mode else 'MITM (代理拦截)'}")
        Logger.info(f"  平台: {'移动端(ADB)' if platform == 'mobile' else '桌面端(pyautogui)'}")
        Logger.info(f"  客户端: {'Steam' if browser_type == 'steam' else '浏览器(Chrome/Edge)'}")
        Logger.info("=" * 50)

    def start(self):
        """启动 MOD"""
        # 启动数据源
        if self._vision_mode:
            # Vision 模式: 启动视觉处理后台循环
            self._ctx.start_vision(fps=10)
            Logger.info("视觉识别已启动 (无需代理配置)")
        else:
            # MITM 模式: 启动 mitmproxy
            self._start_mitmproxy()

        # 启动快捷键监听 (非阻塞)
        self._start_hotkeys()

        Logger.info("MOD 已启动")
        from config import cfg
        browser_type = cfg.get("browser_type", "chrome").lower()
        if cfg.get("platform", "desktop") == "mobile":
            Logger.info("请在手机 WiFi 设置中配置代理: 电脑IP:8080")
        elif not self._vision_mode:
            if browser_type == "steam":
                Logger.info("Steam 模式 — 请先配置代理工具 (Proxifier/Clash)")
                Logger.info("代理目标: 127.0.0.1:8080 | 配置: proxifier_profile.ppx")
            else:
                Logger.info("请在浏览器/系统中设置代理: 127.0.0.1:8080")
        Logger.info("按 F6 切换自动模式 | F7 紧急停止")

        # 自动打开雀魂网页
        self._launch_game()

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
        if not self._vision_mode:
            self._stop_mitmproxy()
        Logger.info("MOD 已停止")

    # ── mitmproxy 进程管理 ──

    def _start_mitmproxy(self):
        """启动 mitmproxy 后台进程"""
        from config import cfg
        import shutil

        port = cfg.get("proxy_port", 8080)
        web_port = cfg.get("mitm_web_port", 8081)

        # ── 1. 查找 mitmdump 可执行文件 ──
        mitmdump_path = shutil.which("mitmdump")
        if not mitmdump_path:
            # PyInstaller 打包后 PATH 可能不包含 Python Scripts
            # 尝试常见路径
            candidates = [
                os.path.join(sys.prefix, "Scripts", "mitmdump.exe"),
                os.path.join(os.path.expanduser("~"), "AppData", "Local",
                             "Programs", "Python", "Python312", "Scripts", "mitmdump.exe"),
                os.path.join(os.path.expanduser("~"), "AppData", "Local",
                             "Programs", "Python", "Python311", "Scripts", "mitmdump.exe"),
            ]
            for c in candidates:
                if os.path.isfile(c):
                    mitmdump_path = c
                    break

        if not mitmdump_path or not os.path.isfile(mitmdump_path):
            Logger.error("=" * 50)
            Logger.error("  mitmdump 未找到!")
            Logger.error("  请先安装 mitmproxy: pip install mitmproxy")
            Logger.error("  安装后重新运行 MajsoulAutoMod.exe")
            Logger.error("=" * 50)
            Logger.info("将以调试模式运行 (无网络拦截)")
            return

        Logger.info(f"mitmdump: {mitmdump_path}")

        # ── 2. 查找 addon 脚本 ──
        addon_path = os.path.join(_EXTERNAL_DIR, "addon.py")
        if not os.path.isfile(addon_path):
            addon_path = os.path.join(_BASE_DIR, "mitm", "addons.py")
        if not os.path.isfile(addon_path):
            Logger.error(f"Addon script not found! Checked: {_EXTERNAL_DIR}/addon.py, {_BASE_DIR}/mitm/addons.py")
            Logger.info("将以调试模式运行 (无网络拦截)")
            return

        Logger.info(f"Addon script: {addon_path}")

        # ── 3. 启动 mitmdump (保留 stderr 以便诊断) ──
        # Steam 模式: 添加 --ignore-hosts 避免拦截 Steam 许可证验证
        mitm_args = [
            mitmdump_path,
            "-s", addon_path,
            "--listen-port", str(port),
            "--set", "block_global=false",
        ]
        # Steam 需要忽略 Steam 服务器，避免 DRM 验证失败
        if cfg.get("browser_type", "").lower() == "steam":
            mitm_args += [
                "--ignore-hosts", "steampowered\\.com",
                "--ignore-hosts", "steamcontent\\.com",
                "--ignore-hosts", "steamstatic\\.com",
            ]
        try:
            self._mitm_process = subprocess.Popen(
                mitm_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,  # 保留 stderr
                text=True,
            )
        except FileNotFoundError:
            Logger.error(f"mitmdump 启动失败! 路径: {mitmdump_path}")
            Logger.info("将以调试模式运行 (无网络拦截)")
            return
        except Exception as e:
            Logger.error(f"启动 mitmdump 异常: {e}")
            Logger.info("将以调试模式运行 (无网络拦截)")
            return

        # ── 4. 等待并验证 mitmdump 是否真的启动了 ──
        time.sleep(1.5)
        if self._mitm_process.poll() is not None:
            # 进程已退出 — 读取 stderr
            stderr_output = ""
            try:
                stderr_output = self._mitm_process.stderr.read()
            except Exception:
                pass
            Logger.error("=" * 50)
            Logger.error("  mitmdump 启动失败! 进程已退出")
            if stderr_output:
                for line in stderr_output.strip().split("\n")[-5:]:
                    Logger.error(f"  {line}")
            Logger.error("=" * 50)
            Logger.info("  常见原因:")
            Logger.info("  1. CA 证书未安装 → 访问 http://mitm.it 安装证书")
            Logger.info("  2. 端口被占用 → 修改 settings.json 中的 proxy_port")
            Logger.info("  3. 权限不足 → 以管理员身份运行")
            Logger.info("将以调试模式运行 (无网络拦截)")
            self._mitm_process = None
            return

        # ── 5. 验证端口已监听 ──
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        port_ok = sock.connect_ex(("127.0.0.1", port)) == 0
        sock.close()
        if port_ok:
            Logger.info(f"✅ mitmproxy 已启动 (端口 {port}, Web UI: {web_port})")
        else:
            Logger.warning(f"⚠ mitmdump 进程运行中，但端口 {port} 尚未监听 (可能在初始化...)")

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

    # ── 自动打开雀魂 ──

    # ── 智能多模式启动器 ──

    # 浏览器路径注册表
    _BROWSERS = {
        "chrome": [
            os.path.expandvars("%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe"),
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        ],
        "edge": [
            "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
            "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
            os.path.expandvars("%PROGRAMFILES(x86)%\\Microsoft\\Edge\\Application\\msedge.exe"),
        ],
    }

    _STEAM_PATHS = [
        "C:\\Program Files (x86)\\Steam\\Steam.exe",
        "C:\\Program Files\\Steam\\Steam.exe",
        os.path.expandvars("%ProgramFiles(x86)%\\Steam\\Steam.exe"),
    ]

    def _find_browser(self, browser_type: str) -> str:
        """查找浏览器可执行文件路径"""
        paths = self._BROWSERS.get(browser_type, [])
        for p in paths:
            if os.path.isfile(p):
                return p
        return None

    def _find_steam(self) -> str:
        """查找 Steam 客户端路径"""
        for p in self._STEAM_PATHS:
            if os.path.isfile(p):
                return p
        return None

    def _launch_game(self):
        """智能多模式启动雀魂"""
        from config import cfg

        platform = cfg.get("platform", "desktop")
        if platform == "mobile":
            Logger.info("移动端: 请手动打开雀魂 APP")
            return

        if not cfg.get("auto_launch_browser", True):
            return

        mode = cfg.get("browser_type", "chrome").lower()
        url  = cfg.get("game_url", "https://game.mahjongsoul.com")
        steam_id = cfg.get("steam_app_id", "2739990")

        Logger.info("")
        Logger.info(f"  启动模式: {mode}")

        # ── 分发 ──
        if mode == "steam":
            self._launch_steam_mode(cfg)
        elif mode == "chrome-app":
            self._launch_pwa_mode(url, "chrome")
        elif mode == "edge-app":
            self._launch_pwa_mode(url, "edge")
        elif mode in ("chrome", "edge"):
            self._launch_browser_mode(url, mode)
        else:
            self._launch_browser_mode(url, "chrome")

    def _launch_browser_mode(self, url: str, browser_type: str):
        """普通浏览器模式"""
        exe = self._find_browser(browser_type)
        if not exe:
            Logger.warning(f"未找到 {browser_type}，用默认浏览器")
            webbrowser.open(url)
            return

        def _open():
            time.sleep(1.5)
            subprocess.Popen(
                [exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            Logger.info(f"已用 {browser_type} 打开雀魂")

        threading.Thread(target=_open, daemon=True).start()

    def _launch_pwa_mode(self, url: str, browser_type: str):
        """
        PWA 独立窗口模式 (像桌面应用)

        Chrome/Edge 的 --app 参数创建一个无边框独立窗口，
        体验接近 Steam 客户端，但走系统代理。
        """
        exe = self._find_browser(browser_type)
        if not exe:
            Logger.warning(f"未找到 {browser_type}，回退到普通浏览器")
            return self._launch_browser_mode(url, browser_type)

        def _open():
            time.sleep(1.5)
            subprocess.Popen(
                [exe, f"--app={url}", "--new-window"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            Logger.info(f"已用 {browser_type} PWA 模式打开雀魂 (独立窗口)")

        threading.Thread(target=_open, daemon=True).start()

    def _launch_steam_mode(self, cfg):
        """Steam 客户端模式"""
        steam_exe = self._find_steam()
        proxy_port = cfg.get("proxy_port", 8080)
        steam_id = cfg.get("steam_app_id", "2739990")

        # 生成 Proxifier 配置
        self._write_proxifier_config(proxy_port)

        Logger.info("")
        Logger.info("  ┌──────────────────────────────────────┐")
        Logger.info("  │ Steam 模式需要流量劫持工具:          │")
        Logger.info("  │ Proxifier → 导入 proxifier_profile.ppx│")
        Logger.info("  │ 或 Clash Verge TUN + 进程规则         │")
        Logger.info("  └──────────────────────────────────────┘")
        Logger.info("")

        def _open():
            time.sleep(1.5)
            if steam_exe:
                subprocess.Popen(
                    [steam_exe, "-applaunch", steam_id],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                Logger.info("已启动 Steam 雀魂")
            else:
                # 尝试 steam:// URI
                subprocess.Popen(
                    ["cmd", "/c", "start", f"steam://rungameid/{steam_id}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                Logger.info("已通过 steam:// 启动雀魂")

        threading.Thread(target=_open, daemon=True).start()

    def _write_proxifier_config(self, proxy_port: int = 8080):
        """生成 Proxifier 配置文件"""
        path = os.path.join(_EXTERNAL_DIR, "proxifier_profile.ppx")
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ProxifierProfile version="1" platform="Windows">\n'
            f'  <ProxyList><Proxy id="100" type="HTTP" address="127.0.0.1" port="{proxy_port}">'
            '<Options><Bitmask>16</Bitmask></Options></Proxy></ProxyList>\n'
            '  <RuleList>\n'
            '    <Rule enabled="true" name="Majsoul">'
            '<Applications>majsoul.exe;MahjongSoul.exe</Applications>'
            '<Ports>0-65535</Ports><Action type="Proxy">100</Action></Rule>\n'
            '    <Rule enabled="true" name="Direct">'
            '<Applications>*</Applications><Action type="Direct"/></Rule>\n'
            '  </RuleList><ChainList/>\n'
            '</ProxifierProfile>\n'
        )
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(xml)
            Logger.info(f"  Proxifier 配置: proxifier_profile.ppx")
        except Exception as e:
            Logger.warning(f"  Proxifier 配置写入失败: {e}")

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
        "--steam", action="store_true",
        help="Steam 客户端模式 (自动设置 browser_type=steam)"
    )
    parser.add_argument(
        "--cli", action="store_true",
        help="命令行模式 (调试用)"
    )
    parser.add_argument(
        "--vision", action="store_true", default=True,
        help="使用视觉识别模式 (默认, 无需代理)"
    )
    parser.add_argument(
        "--mitm", action="store_true",
        help="使用 MITM 代理模式 (需要安装 mitmproxy 和 CA 证书)"
    )
    args = parser.parse_args()

    # --mitm 覆盖 --vision
    vision_mode = args.vision and not args.mitm

    # CA 证书提示 (仅 MITM 模式)
    if not vision_mode:
        cert_dir = os.path.join(str(Path.home()), ".mitmproxy")
        if not os.path.exists(cert_dir):
            Logger.info("首次运行需要 mitmproxy CA 证书")
            Logger.info("启动后访问 http://mitm.it 下载并信任证书")

    # 启动
    mod = MajsoulAutoMod(
        listen_only=args.listen_only,
        force_steam=args.steam,
        vision_mode=vision_mode,
    )
    try:
        mod.start()
    except KeyboardInterrupt:
        pass
    finally:
        mod.stop()


if __name__ == "__main__":
    main()
