"""
雀魂 Steam 客户端启动器

通过设置 Windows 全局代理让 Steam 客户端的 WebSocket 流量经过 mitmproxy。

原理:
  方法1 (推荐): 修改 Windows 代理设置 → 启动游戏 → 恢复代理
  方法2: 使用 Proxinject 注入 SOCKS5 代理到游戏进程
  方法3: 通过 hosts + nginx 转发

使用方法:
  python launch_steam.py              # 启动游戏 + MOD
  python launch_steam.py --no-mod     # 仅启动游戏(不启动MOD)
  python launch_steam.py --restore    # 恢复代理设置
"""

import argparse
import os
import subprocess
import sys
import time
import ctypes
import winreg
from pathlib import Path

# 确保项目目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.log import Logger


STEAM_APP_ID = "1329410"  # 雀魂 Steam AppID
GAME_EXE = "Jantama_MahjongSoul.exe"


def is_admin():
    """检查是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def set_proxy(enable: bool, host="127.0.0.1", port=8080):
    """设置 Windows 系统代理"""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0, winreg.KEY_SET_VALUE
        )

        if enable:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                            "localhost;127.*;10.*;192.168.*;*.local")
            Logger.info(f"系统代理已启用: {host}:{port}")
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            Logger.info("系统代理已关闭")

        winreg.CloseKey(key)

        # 通知系统代理变更
        ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
        ctypes.windll.wininet.InternetSetOptionW(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH

    except Exception as e:
        Logger.error(f"设置代理失败: {e}")


def find_game_path() -> str:
    """从 Steam 注册表找到雀魂安装路径"""
    try:
        # Steam 库路径
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path = winreg.QueryValueEx(key, "SteamPath")[0]

        # 默认库路径
        common = os.path.join(steam_path, "steamapps", "common", "MahjongSoul")
        if os.path.exists(os.path.join(common, GAME_EXE)):
            return common

        # 其他库路径 (读取 libraryfolders.vdf)
        vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf_path):
            with open(vdf_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if '"path"' in line:
                        path = line.split('"')[3]
                        candidate = os.path.join(path, "steamapps", "common", "MahjongSoul")
                        if os.path.exists(os.path.join(candidate, GAME_EXE)):
                            return candidate
    except:
        pass

    # 常见路径
    candidates = [
        r"D:\Steam\steamapps\common\MahjongSoul",
        r"C:\Program Files (x86)\Steam\steamapps\common\MahjongSoul",
        r"C:\Program Files\Steam\steamapps\common\MahjongSoul",
    ]
    for c in candidates:
        if os.path.exists(os.path.join(c, GAME_EXE)):
            return c

    return ""


def launch_game():
    """启动雀魂 Steam 客户端"""
    game_dir = find_game_path()
    if game_dir:
        exe_path = os.path.join(game_dir, GAME_EXE)
        if os.path.exists(exe_path):
            Logger.info(f"启动游戏: {exe_path}")
            subprocess.Popen([exe_path], cwd=game_dir)
            return True

    # 通过 Steam URL 启动
    Logger.info("通过 Steam 启动 (steam://rungameid/1329410)")
    subprocess.Popen(["start", f"steam://rungameid/{STEAM_APP_ID}"], shell=True)
    return True


def launch_mitmproxy():
    """启动 mitmproxy 后台"""
    addon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm", "addons.py")

    try:
        proc = subprocess.Popen(
            ["mitmdump", "-s", addon_path, "--listen-port", "8080",
             "--set", "block_global=false"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        Logger.info(f"mitmproxy 已启动 (PID: {proc.pid})")
        return proc
    except FileNotFoundError:
        Logger.error("mitmproxy 未安装! 请执行: pip install mitmproxy")
        return None


def main():
    parser = argparse.ArgumentParser(description="雀魂 Steam 客户端启动器")
    parser.add_argument("--no-mod", action="store_true", help="仅启动游戏")
    parser.add_argument("--restore", action="store_true", help="恢复代理设置")
    args = parser.parse_args()

    # 检查管理员权限
    if not is_admin():
        Logger.warning("建议以管理员权限运行以修改系统代理")
        Logger.warning("请右键 → 以管理员身份运行")

    if args.restore:
        set_proxy(False)
        return

    mitm_proc = None
    if not args.no_mod:
        Logger.info("=" * 50)
        Logger.info("  雀魂自动打牌 MOD v2.0 - Steam 启动器")
        Logger.info("=" * 50)

        # 启动 mitmproxy
        mitm_proc = launch_mitmproxy()
        time.sleep(2)

        # 启用系统代理
        set_proxy(True)

        Logger.info("MOD 已就绪，正在启动游戏...")
        Logger.info("提示: 按 Ctrl+C 停止 MOD 并恢复代理设置")

    # 启动游戏
    launch_game()

    try:
        # 等待用户退出
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        Logger.info("正在关闭...")
    finally:
        if not args.no_mod:
            set_proxy(False)
            if mitm_proc:
                mitm_proc.terminate()
                try:
                    mitm_proc.wait(timeout=5)
                except:
                    mitm_proc.kill()
        Logger.info("已退出")


if __name__ == "__main__":
    main()
