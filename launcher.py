#!/usr/bin/env python3
"""雀魂自动打牌 MOD - 启动器入口 (用于 PyInstaller 打包)"""

import os
import sys
import subprocess
import time
import ctypes
import json
from pathlib import Path


def resource_path(relative_path):
    """获取 exe 内部或外部资源路径"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def ensure_config():
    """确保配置文件存在"""
    config_dir = os.path.join(str(Path.home()), ".majsoul_automod")
    config_file = os.path.join(config_dir, "settings.json")
    if not os.path.exists(config_file):
        os.makedirs(config_dir, exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump({
                "proxy_port": 8080,
                "aggression": 3,
                "speed": 3,
                "risk_tolerance": 3,
                "auto_discard": True,
                "auto_call": True,
                "auto_riichi": True,
                "auto_agari": True,
                "min_delay_ms": 300,
                "max_delay_ms": 1500,
                "safety_mode": True,
            }, f, ensure_ascii=False, indent=2)
    return config_file


def setup_logging():
    """设置日志"""
    log_dir = os.path.join(str(Path.home()), ".majsoul_automod", "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def find_mitmdump():
    """查找 mitmdump.exe"""
    # 1. 同目录
    for f in ["mitmdump.exe"]:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), f)
        if os.path.exists(p):
            return p
    # 2. PATH 环境变量
    for p in os.environ.get("PATH", "").split(";"):
        candidate = os.path.join(p, "mitmdump.exe")
        if os.path.exists(candidate):
            return candidate
    # 3. Python Scripts 目录
    scripts = os.path.join(os.path.dirname(sys.executable), "Scripts", "mitmdump.exe")
    if os.path.exists(scripts):
        return scripts
    return None


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def set_proxy(enable, host="127.0.0.1", port=8080):
    try:
        import winreg
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
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
        ctypes.windll.wininet.InternetSetOptionW(0, 37, 0, 0)
        return True
    except Exception as e:
        print(f"  [!] 代理设置失败: {e}")
        return False


def main():
    print("========================================")
    print("  雀魂自动打牌 MOD v2.0")
    print("========================================")
    print()

    # 创建配置
    ensure_config()
    ensure_config()
    log_dir = setup_logging()
    print(f"[*] 日志目录: {log_dir}")

    # 检查 mitmproxy
    mitmdump = find_mitmdump()
    admin = is_admin()

    if not admin:
        print("[!] 建议以管理员权限运行")
        print("    否则需手动设置系统代理")
        print()

    mitm_proc = None
    addon_path = resource_path("mitm/addons.py") if os.path.exists(resource_path("mitm/addons.py")) else None

    if mitmdump and addon_path and os.path.exists(addon_path):
        print(f"[*] 启动 mitmproxy (端口 8080)...")
        try:
            mitm_proc = subprocess.Popen(
                [mitmdump, "-s", addon_path, "--listen-port", "8080",
                 "--set", "block_global=false"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            print(f"  [+] 已启动 (PID: {mitm_proc.pid})")
            time.sleep(2)
        except Exception as e:
            print(f"  [!] 启动失败: {e}")
            mitm_proc = None
    else:
        print("[!] mitmproxy 未安装或 addon 未找到")
        if not mitmdump:
            print("    请安装: pip install mitmproxy")
        if addon_path and not os.path.exists(addon_path):
            print(f"    addon 不存在: {addon_path}")

    # 设置系统代理
    if admin and mitm_proc:
        print()
        print("[*] 设置系统代理...")
        if set_proxy(True):
            print("  [+] 系统代理: 127.0.0.1:8080")
        else:
            print("  [!] 系统代理设置失败")

    print()
    print("=" * 40)
    print("  MOD 已就绪!")
    print()
    if admin and mitm_proc:
        print("  通过 Steam 启动雀魂后")
        print("  进入对局即可自动打牌")
    else:
        print("  手动设置代理: 127.0.0.1:8080")
        print("  然后启动游戏")
    print()
    print("  按 Ctrl+C 停止")
    print("=" * 40)
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        print("[*] 正在停止...")

    # 恢复代理
    if admin and mitm_proc:
        set_proxy(False)
        print("  [+] 系统代理已恢复")

    # 停止 mitmproxy
    if mitm_proc:
        mitm_proc.terminate()
        try:
            mitm_proc.wait(timeout=3)
        except:
            mitm_proc.kill()
        print("  [+] mitmproxy 已停止")

    print("[*] 已退出")
    input("按 Enter 键退出...")


if __name__ == "__main__":
    main()
