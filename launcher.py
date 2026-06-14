#!/usr/bin/env python3
"""雀魂自动打牌 MOD v2.0 — 启动器"""

import os, sys, subprocess, time, json, atexit, tempfile, shutil, ctypes
from pathlib import Path

# 可选 GUI 依赖
try: import pyautogui
except: pyautogui = None
try: import pygetwindow as gw
except: gw = None


HOME = str(Path.home())
BASE = os.path.join(HOME, ".majsoul_automod")
ACTION_QUEUE = os.path.join(BASE, "action_queue.json")
LOG_FILE = os.path.join(BASE, "logs", "launcher.log")
os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)

LOG = lambda msg: print(f"[{time.strftime('%H:%M:%S')}] {msg}")


# ═══════════════════════════════════════════════
# 动作执行器
# ═══════════════════════════════════════════════

class ActionExecutor:
    def __init__(self):
        self._stop = False

    def start(self):
        import threading
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self._stop = True

    def _run(self):
        while not self._stop:
            try:
                if not os.path.exists(ACTION_QUEUE):
                    time.sleep(0.5); continue
                with open(ACTION_QUEUE) as f:
                    action = json.load(f)
                os.remove(ACTION_QUEUE)
                if action.get("action") == "discard":
                    self._discard(action)
            except:
                time.sleep(1)

    def _discard(self, action):
        tile_str = action.get("tile_str", "?")
        pos = action.get("hand_pos", 0)
        LOG(f"打牌: {tile_str} (位置{pos})")

        if gw is None or pyautogui is None:
            LOG("  pip install pyautogui pygetwindow 启用自动点击")
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

            # 手牌: 窗口底部约 20% 区域
            hand_y = y + int(h * 0.76)
            hand_x0 = x + int(w * 0.05)
            hand_x1 = x + int(w * 0.95)
            n = action.get("hand_count", 14)

            slot_w = (hand_x1 - hand_x0) // max(n, 1)
            idx = min(max(pos, 0), n - 1)
            cx = hand_x0 + slot_w * idx + slot_w // 2
            cy = hand_y + int(h * 0.06)

            # 模拟人机鼠标轨迹
            pyautogui.moveTo(cx - 40, cy - 15, duration=0.1)
            time.sleep(0.05)
            pyautogui.moveTo(cx, cy + 5, duration=0.07)
            time.sleep(0.08)
            pyautogui.click()
            LOG(f"  点击: ({cx}, {cy})")

        except Exception as e:
            LOG(f"  点击异常: {e}")


# ═══════════════════════════════════════════════
# 代理工具
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
            # 排除本地地址和 Steam CDN
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                "localhost;127.*;10.*;192.168.*;*.local;*.steampowered.com;steamcommunity.com;*.akamaiedge.net;*.cloudfront.net;*.aliyuncs.com")
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

def check_cert():
    """检查 mitmproxy CA 证书是否已安装"""
    cert_files = [
        os.path.join(HOME, ".mitmproxy", "mitmproxy-ca-cert.cer"),
        os.path.join(HOME, ".mitmproxy", "mitmproxy-ca-cert.p12"),
    ]
    for f in cert_files:
        if os.path.exists(f):
            return f
    # 尝试让 mitmproxy 先生成证书
    try:
        subprocess.run(["mitmdump", "--version"], capture_output=True, timeout=5)
        time.sleep(2)
        for f in cert_files:
            if os.path.exists(f): return f
    except: pass
    return None

def launch_steam():
    """启动雀魂"""
    # 直接启动 exe
    game_paths = [
        r"D:\Steam\steamapps\common\MahjongSoul\Jantama_MahjongSoul.exe",
        r"C:\Program Files (x86)\Steam\steamapps\common\MahjongSoul\Jantama_MahjongSoul.exe",
        r"C:\Program Files\Steam\steamapps\common\MahjongSoul\Jantama_MahjongSoul.exe",
    ]
    for gp in game_paths:
        if os.path.exists(gp):
            subprocess.Popen([gp], cwd=os.path.dirname(gp))
            return True
    # 通过 Steam URL
    try:
        subprocess.Popen(["start", "steam://rungameid/1329410"], shell=True)
        return True
    except: return False


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

def main():
    print("=" * 50)
    print("  雀魂自动打牌 MOD v2.0")
    print("=" * 50)
    print()

    admin = is_admin()
    LOG(f"管理员: {'是' if admin else '否'}")
    if gw is None:
        LOG("提示: pip install pyautogui pygetwindow 启用自动点击")
    print()

    # 1. 检查证书
    cert = check_cert()
    if not cert:
        LOG("⚠ 首次使用需要安装 mitmproxy CA 证书!")
        LOG("  否则游戏无法通过代理连接服务器")
        LOG("  操作步骤:")
        LOG("  1. 启动 MOD")
        LOG("  2. 打开浏览器访问 http://mitm.it")
        LOG("  3. 下载 Windows 证书并安装到「受信任的根证书颁发机构」")
        print()

    # 2. 提取 addon.py
    addon_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "addon.py")
    try: addon_src = sys._MEIPASS + "/addon.py"
    except: pass

    if not os.path.exists(addon_src):
        addon_src = resource_path("addon.py")
    if not os.path.exists(addon_src):
        LOG("addon.py 未找到!"); input("\n按 Enter 退出..."); return

    addon_tmp = os.path.join(tempfile.gettempdir(), "majsoul_addon.py")
    shutil.copy2(addon_src, addon_tmp)

    # 3. 查找 mitmdump
    mitmdump = find_mitmdump()
    if not mitmdump:
        LOG("mitmdump.exe 未找到! 安装: pip install mitmproxy")
        input("\n按 Enter 退出..."); return
    LOG(f"mitmdump: {mitmdump}")

    # 清理旧 mitmproxy
    subprocess.run(["taskkill", "/f", "/im", "mitmdump.exe"],
                   capture_output=True)
    time.sleep(1)

    # 4. 启动 mitmproxy
    proc_container = [None]

    try:
        p = subprocess.Popen(
            [mitmdump, "-s", addon_tmp, "--listen-port", "8080",
             "--set", "ssl_insecure=true",
             "--set", "block_global=false"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(2)
        if p.poll() is not None:
            LOG(f"mitmproxy 启动失败 (code: {p.poll()})")
            LOG("端口 8080 被占用，请关闭其他代理程序")
        else:
            proc_container[0] = p
            LOG(f"mitmproxy 已启动 (PID: {p.pid})")
    except Exception as e:
        LOG(f"mitmproxy 异常: {e}")

    def cleanup():
        if proc_container[0]:
            proc_container[0].terminate()
            try: proc_container[0].wait(timeout=3)
            except: proc_container[0].kill()
        if admin: set_proxy(False)
        LOG("已清理")

    atexit.register(cleanup)

    # 5. 设置系统代理
    if admin and proc_container[0]:
        set_proxy(True)
        LOG("系统代理: 127.0.0.1:8080")
        LOG("(Steam/CDN 地址已排除)")
    else:
        LOG("请手动设置系统代理: 127.0.0.1:8080")

    print()

    # 6. 询问是否启动游戏
    try:
        r = input("  是否启动雀魂? (Y/n): ").strip().lower()
        if r != 'n' and r != 'no':
            if launch_steam():
                LOG("游戏已启动")
            else:
                LOG("自动启动失败, 请手动从 Steam 启动")
    except: pass

    # 7. 启动动作执行器
    executor = ActionExecutor()
    executor.start()
    LOG("动作执行器已启动\n")

    print("  使用说明:")
    print("  1. 进入对局即可自动打牌")
    print("  2. Ctrl+C 停止\n")

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        LOG("\n正在停止...")

    executor.stop()
    cleanup()


def resource_path(p):
    try: return sys._MEIPASS + "/" + p
    except: return os.path.join(os.path.dirname(os.path.abspath(__file__)), p)


if __name__ == "__main__":
    main()
