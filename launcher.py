#!/usr/bin/env python3
"""雀魂自动打牌 MOD 启动器"""

import os, sys, subprocess, time, json, atexit, tempfile, shutil, ctypes
from pathlib import Path


def resource_path(relative_path):
    try:
        base = sys._MEIPASS
    except:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def set_proxy(enable, host="127.0.0.1", port=8080):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0, winreg.KEY_SET_VALUE)
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
    except:
        return False


def find_mitmdump():
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitmdump.exe"),
        os.path.join(os.path.dirname(sys.executable), "Scripts", "mitmdump.exe"),
    ]
    for p in os.environ.get("PATH", "").split(";"):
        c = os.path.join(p, "mitmdump.exe")
        if os.path.exists(c):
            return c
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def main():
    print("=" * 50)
    print("  雀魂自动打牌 MOD v2.0")
    print("=" * 50)
    print()

    admin = is_admin()
    log(f"管理员权限: {'是' if admin else '否'}")

    # 1. 提取 addon.py 到临时目录
    addon_src = resource_path("addon.py")
    addon_tmp = os.path.join(tempfile.gettempdir(), "majsoul_addon.py")

    if os.path.exists(addon_src):
        shutil.copy2(addon_src, addon_tmp)
        log(f"Addon: {addon_tmp}")
    else:
        log(f"错误: addon.py 未找到!")
        input("\n按 Enter 退出...")
        return

    # 2. 启动 mitmproxy
    mitmdump = find_mitmdump()
    if not mitmdump:
        log("错误: mitmdump.exe 未找到! 请安装 mitmproxy: pip install mitmproxy")
        input("\n按 Enter 退出...")
        return

    log(f"mitmdump: {mitmdump}")

    # 清理旧进程
    try:
        subprocess.run(["taskkill", "/f", "/im", "mitmdump.exe"],
                       capture_output=True, timeout=3)
        time.sleep(1)
    except:
        pass

    mitm_proc = None
    try:
        mitm_proc = subprocess.Popen(
            [mitmdump, "-s", addon_tmp, "--listen-port", "8080",
             "--set", "ssl_insecure=true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        time.sleep(2)
        if mitm_proc.poll() is not None:
            log(f"mitmproxy 启动失败 (code: {mitm_proc.poll()})")
            log("端口 8080 被占用或 mitmproxy 配置错误")
            mitm_proc = None
        else:
            log(f"mitmproxy 已启动 (PID: {mitm_proc.pid})")
    except Exception as e:
        log(f"mitmproxy 启动异常: {e}")

    # 清理函数
    def cleanup():
        if mitm_proc:
            mitm_proc.terminate()
            try:
                mitm_proc.wait(timeout=3)
            except:
                mitm_proc.kill()
            log("mitmproxy 已停止")
        if admin:
            set_proxy(False)
            log("系统代理已恢复")

    atexit.register(cleanup)

    # 设置系统代理
    if admin and mitm_proc:
        set_proxy(True)
        log("系统代理已启用")
    elif not admin:
        log("需要管理员权限才能自动设置代理")
        log("请手动设置: 设置 → 网络 → 代理 → 127.0.0.1:8080")

    print()
    print("  MOD 已就绪!")
    print()
    print("  1. 通过 Steam 启动雀魂")
    print("  2. 进入对局")
    print()
    print("  按 Ctrl+C 停止")
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        log("正在停止...")

    cleanup()
    input("\n按 Enter 退出...")


if __name__ == "__main__":
    main()
