"""
打包脚本 - 将雀魂自动打牌 MOD 打包为 Windows .exe

使用方法:
  python build_exe.py            # 构建完整 one-file exe
  python build_exe.py --debug    # 构建调试版 (带控制台)
  python build_exe.py --installer # 构建 + NSIS 安装包

需要:
  pip install pyinstaller nsis
"""

import os
import sys
import shutil
import subprocess
import site
import glob
from pathlib import Path


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
VERSION = "2.0.0"


def find_mitmproxy_data():
    """查找 mitmproxy 的数据文件路径"""
    # 找到 mitmproxy 安装目录下的 web 资源
    for dir in site.getsitepackages():
        web_dir = os.path.join(dir, "mitmproxy", "web")
        if os.path.isdir(web_dir):
            return web_dir
        # 也可能是 mitmproxy 下的 mitmproxy 目录
        web_dir2 = os.path.join(dir, "mitmproxy", "mitmproxy", "web")
        if os.path.isdir(web_dir2):
            return web_dir2
        # pip 安装路径
        web_dir3 = os.path.join(dir, "mitmproxy-*-info", "mitmproxy", "web")
        for p in glob.glob(os.path.join(dir, "mitmproxy*", "mitmproxy", "web")):
            return p

    # 尝试 find 方式
    for root_dir in site.getsitepackages():
        for root, dirs, files in os.walk(root_dir):
            if root.endswith("mitmproxy\\web") or root.endswith("mitmproxy/web"):
                return root
            if "web" in dirs and root.endswith("mitmproxy"):
                return os.path.join(root, "web")
    return None


def build_exe(debug=False):
    """使用 PyInstaller 构建 .exe"""
    print("=" * 60)
    print(f"  构建雀魂自动打牌 MOD v{VERSION}")
    print("=" * 60)

    # 清理旧构建
    for d in [BUILD_DIR, DIST_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)

    # 确定 mitmproxy web 资源路径
    mitm_web = find_mitmproxy_data()
    if mitm_web:
        print(f"  [+] 找到 mitmproxy web 资源: {mitm_web}")
    else:
        print(f"  [!] 未找到 mitmproxy web 资源 (运行时不可用)")

    # 创建入口脚本
    main_entry = os.path.join(PROJECT_DIR, "launcher.py")
    with open(main_entry, "w", encoding="utf-8") as f:
        f.write("""#!/usr/bin/env python3
\"\"\"雀魂自动打牌 MOD - 启动器\"\"\"

import os
import sys
import subprocess
import time
import threading
import ctypes
import signal
from pathlib import Path

# 确保工作目录正确
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 设置 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import cfg
from utils.log import Logger


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def set_proxy_windows(enable, host="127.0.0.1", port=8080):
    \"\"\"设置 Windows 系统代理\"\"\"
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings",
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
        Logger.error(f"代理设置失败: {e}")
        return False


def find_mitmdump():
    \"\"\"查找 mitmdump.exe\"\"\"
    # 1. 同目录
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitmdump.exe")
    if os.path.exists(local):
        return local

    # 2. Scripts 目录
    for p in os.environ.get("PATH", "").split(";"):
        candidate = os.path.join(p, "mitmdump.exe")
        if os.path.exists(candidate):
            return candidate

    # 3. Python Scripts 目录
    scripts = os.path.join(os.path.dirname(sys.executable), "Scripts", "mitmdump.exe")
    if os.path.exists(scripts):
        return scripts

    return None


def main():
    print("========================================")
    print("  雀魂自动打牌 MOD v{}".format(sys.argv[1] if len(sys.argv) > 1 else VERSION))
    print("========================================")
    print()

    admin = is_admin()
    if not admin:
        print("[!] 建议以管理员权限运行以获得完整功能")
        print()

    # 启动 mitmproxy
    mitmdump = find_mitmdump()
    mitm_proc = None

    if mitmdump:
        print(f"[*] 启动 mitmproxy...")
        addon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm", "addons.py")

        if os.path.exists(addon):
            mitm_proc = subprocess.Popen(
                [mitmdump, "-s", addon, "--listen-port", "8080",
                 "--set", "block_global=false"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            print(f"  [+] mitmproxy 已启动 (PID: {mitm_proc.pid})")
            time.sleep(2)
        else:
            print(f"  [!] addon 未找到: {addon}")
    else:
        print("  [!] mitmdump.exe 未找到")
        print("  请先安装: pip install mitmproxy")

    # 设置代理
    if admin and mitm_proc:
        print()
        print("[*] 设置系统代理...")
        set_proxy_windows(True)
        print("  [+] 系统代理已设置 (127.0.0.1:8080)")

    print()
    print("[*] MOD 已就绪!")
    if admin and mitm_proc:
        print("  [+] 请通过 Steam 启动雀魂")
        print("  [+] 进入对局后 MOD 将自动工作")
    else:
        print("  [!] 请手动设置代理: 127.0.0.1:8080")
        print("  [!] 然后通过 Steam 启动雀魂")
    print()
    print("[*] 按 Ctrl+C 停止 MOD 并恢复代理设置")
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        print("[*] 正在关闭...")

    if admin and mitm_proc:
        set_proxy_windows(False)
        print("  [+] 系统代理已恢复")

    if mitm_proc:
        mitm_proc.terminate()
        try:
            mitm_proc.wait(timeout=5)
        except:
            mitm_proc.kill()
        print("  [+] mitmproxy 已停止")

    print("[*] 已退出")
    input("按 Enter 键退出...")


VERSION = sys.argv[1] if len(sys.argv) > 1 else "2.0.0"

if __name__ == "__main__":
    main()
""")

    # PyInstaller 命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", f"MajsoulAutoMod_{VERSION}",
        "--onefile",          # 单个 exe
        "--windowed",         # 无控制台窗口 (GUI 模式)
        "--noconfirm",
        "--clean",
        "--distpath", DIST_DIR,
        "--workpath", BUILD_DIR,
        "--add-data", f"proto{os.pathsep}proto",
        "--add-data", f"mitm{os.pathsep}mitm",
        "--add-data", f"ai{os.pathsep}ai",
        "--add-data", f"game_state{os.pathsep}game_state",
        "--add-data", f"action{os.pathsep}action",
        "--add-data", f"config{os.pathsep}config",
        "--add-data", f"utils{os.pathsep}utils",
        # Hidden imports for mitmproxy
        "--hidden-import", "mitmproxy",
        "--hidden-import", "mitmproxy.tools.main",
        "--hidden-import", "mitmproxy.addons",
        "--hidden-import", "mitmproxy.proxy",
        "--hidden-import", "mitmproxy.http",
        "--hidden-import", "mitmproxy.websocket",
        "--hidden-import", "mitmproxy.flow",
        "--hidden-import", "mitmproxy.connection",
        "--hidden-import", "mitmproxy.options",
        "--hidden-import", "mitmproxy.ctx",
        "--hidden-import", "mitmproxy.net",
        "--hidden-import", "tornado",
        "--hidden-import", "wsproto",
        "--hidden-import", "h2",
        "--hidden-import", "cryptography",
        "--hidden-import", "pyOpenSSL",
        "--hidden-import", "OpenSSL",
        "--hidden-import", "brotli",
        "--hidden-import", "zstandard",
    ]

    # 添加 mitmproxy web 资源
    if mitm_web:
        # 找到 mitmproxy package 的父目录
        mitm_pkg_dir = os.path.dirname(os.path.dirname(mitm_web))  # mitmproxy/
        if os.path.exists(mitm_pkg_dir):
            cmd.extend(["--add-data", f"{mitm_pkg_dir}{os.pathsep}mitmproxy"])
            print(f"  [+] 打包 mitmproxy 数据")

    # 入口文件
    cmd.append(main_entry)

    if debug:
        cmd.remove("--windowed")
        cmd.append("--debug")

    print()
    print("[*] 开始构建...")
    print(f"    命令: {' '.join(cmd[:5])} ...")
    print()

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode == 0:
        print()
        print("  [+] 构建成功!")

        # 查找生成的 exe
        for f in os.listdir(DIST_DIR):
            if f.endswith(".exe"):
                exe_path = os.path.join(DIST_DIR, f)
                size_mb = os.path.getsize(exe_path) / (1024 * 1024)
                print(f"  [+] {f} ({size_mb:.1f} MB)")
                print(f"  [+] 路径: {exe_path}")
    else:
        print()
        print(f"  [!] 构建失败")
        if result.stderr:
            print(result.stderr[-1000:])

    return result.returncode


if __name__ == "__main__":
    debug = "--debug" in sys.argv
    build_exe(debug)
