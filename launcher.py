#!/usr/bin/env python3
"""雀魂自动打牌 MOD v2.0"""

import os, sys, subprocess, time, json, atexit, tempfile, \
       shutil, ctypes, threading, struct
from pathlib import Path

# Optional GUI support
try: import pyautogui
except: pyautogui = None
try: import pygetwindow as gw
except: gw = None


LOG = lambda msg: print(f"[{time.strftime('%H:%M:%S')}] {msg}")
ACTION_QUEUE = os.path.join(str(Path.home()), ".majsoul_automod", "action_queue.json")
os.makedirs(os.path.join(str(Path.home()), ".majsoul_automod", "logs"), exist_ok=True)


def resource_path(p):
    try: base = sys._MEIPASS
    except: base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, p)


# ═══════════════════════════════════════════════
# 动作执行器
# ═══════════════════════════════════════════════

class ActionExecutor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True

    def run(self):
        while self.running:
            try:
                if not os.path.exists(ACTION_QUEUE):
                    time.sleep(0.5); continue
                with open(ACTION_QUEUE) as f:
                    action = json.load(f)
                os.remove(ACTION_QUEUE)

                if action.get("action") == "discard":
                    self._discard(action)
                elif action.get("action") == "riichi":
                    LOG(f"立直: 打 {action.get('tile_str','?')}")
            except: time.sleep(1)

    def _discard(self, action):
        tile = action.get("tile", 0)
        LOG(f"打牌: {action.get('tile_str','?')} [{tile}]")

        if gw is None or pyautogui is None:
            LOG("  (需安装: pip install pyautogui pygetwindow)")
            return

        try:
            wins = gw.getWindowsWithTitle("雀魂") or \
                   gw.getWindowsWithTitle("MahjongSoul") or \
                   gw.getWindowsWithTitle("Jantama")
            if not wins:
                LOG("  未找到游戏窗口"); return
            win = wins[0]
            if win.isMinimized: win.restore()
            win.activate()
            time.sleep(0.3)

            x, y, w, h = win.left, win.top, win.width, win.height

            # 手牌区域: 窗口底部 ~25%
            ty = y + int(h * 0.78)
            tx0 = x + int(w * 0.08)
            tx1 = x + int(w * 0.92)
            slot = (tx1 - tx0) // 14
            idx = min(abs(tile) % 14, 13)
            cx = tx0 + slot * idx + slot // 2

            # 移动到手牌
            pyautogui.moveTo(cx - 30, ty - 10, duration=0.08)
            time.sleep(0.05)
            pyautogui.moveTo(cx, ty + 10, duration=0.06)
            time.sleep(0.1)
            pyautogui.click()
            LOG(f"  点击手牌: ({cx}, {ty+10})")
        except Exception as e:
            LOG(f"  异常: {e}")


# ═══════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

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
    except: return False

def find_mitmdump():
    for p in os.environ.get("PATH", "").split(";"):
        c = os.path.join(p, "mitmdump.exe")
        if os.path.exists(c): return c
    for p in [os.path.join(os.path.dirname(sys.executable), "Scripts"),
              os.path.dirname(os.path.abspath(__file__))]:
        c = os.path.join(p, "mitmdump.exe")
        if os.path.exists(c): return c
    return None


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

def main():
    print("=" * 50)
    print("  雀魂自动打牌 MOD v2.0")
    print("=" * 50 + "\n")

    admin = is_admin()
    LOG(f"管理员: {'是' if admin else '否'}")
    if gw is None: LOG("提示: pip install pyautogui pygetwindow 提升精度")

    # 1. 提取 addon
    addon_src = resource_path("addon.py")
    addon_tmp = os.path.join(tempfile.gettempdir(), "majsoul_addon.py")
    if not os.path.exists(addon_src):
        LOG("addon.py 未找到!"); input("按 Enter 退出..."); return
    shutil.copy2(addon_src, addon_tmp)

    # 2. mitmdump
    mitmdump = find_mitmdump()
    if not mitmdump:
        LOG("mitmdump.exe 未找到! 安装: pip install mitmproxy")
        input("按 Enter 退出..."); return
    LOG(f"mitmdump: {mitmdump}")

    try: subprocess.run(["taskkill", "/f", "/im", "mitmdump.exe"],
                        capture_output=True, timeout=3)
    except: pass
    time.sleep(1)

    mitm_proc = None
    try:
        mitm_proc = subprocess.Popen(
            [mitmdump, "-s", addon_tmp, "--listen-port", "8080",
             "--set", "ssl_insecure=true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(2)
        if mitm_proc.poll() is not None:
            LOG(f"mitmproxy 启动失败 (code: {mitm_proc.poll()})")
            LOG("端口 8080 被占用, 请检查"); mitm_proc = None
        else:
            LOG(f"mitmproxy 已启动 (PID: {mitm_proc.pid})")
    except Exception as e:
        LOG(f"mitmproxy 异常: {e}")

    def cleanup():
        nonlocal mitm_proc
        if mitm_proc:
            mitm_proc.terminate()
            try: mitm_proc.wait(timeout=3)
            except: mitm_proc.kill()
        if admin: set_proxy(False)
        LOG("已清理")

    atexit.register(cleanup)

    if admin and mitm_proc:
        set_proxy(True); LOG("系统代理: 127.0.0.1:8080")
    else:
        LOG("请手动设置系统代理: 127.0.0.1:8080")

    # 3. 启动动作执行器
    executor = ActionExecutor()
    executor.start()
    LOG("动作执行器已启动\n")

    print("  使用说明:")
    print("  1. Steam 启动雀魂")
    print("  2. 进入对局即可自动打牌")
    print("  3. Ctrl+C 停止\n")

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        LOG("\n正在停止...")

    executor.running = False
    cleanup()

if __name__ == "__main__":
    main()
