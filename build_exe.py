#!/usr/bin/env python3
"""
雀魂 MOD 打包脚本 — 生成可分发的 .exe 和配套文件

用法:
    python build_exe.py

输出目录: dist/MajsoulAutoMod/
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist", "MajsoulAutoMod")


def clean_dist():
    """清理旧的构建产物"""
    dirs_to_clean = [
        os.path.join(PROJECT_DIR, "build"),
        os.path.join(PROJECT_DIR, "dist"),
    ]
    for d in dirs_to_clean:
        if os.path.isdir(d):
            shutil.rmtree(d)
    for f in Path(PROJECT_DIR).glob("*.spec"):
        f.unlink()


def build_exe():
    """使用 PyInstaller 构建主程序 exe"""
    print("=" * 60)
    print("  雀魂自动打牌 MOD — 构建 .exe")
    print("=" * 60)
    print()

    # PyInstaller 参数
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",                          # 目录模式 (配套文件需要和 exe 同目录)
        "--name", "雀魂MOD",
        "--console",                         # 显示控制台窗口
        "--clean",
        "--noconfirm",
        # 隐藏导入 (这些库 PyInstaller 可能检测不到)
        "--hidden-import", "mitmproxy",
        "--hidden-import", "pyautogui",
        "--hidden-import", "pygetwindow",
        "--hidden-import", "cv2",
        "--hidden-import", "numpy",
        "--hidden-import", "pynput",
        # 数据文件 (打包进 exe 目录)
        "--add-data", f"config{os.pathsep}config",
        "--add-data", f"proto{os.pathsep}proto",
        "--add-data", f"ai{os.pathsep}ai",
        "--add-data", f"game_state{os.pathsep}game_state",
        "--add-data", f"action{os.pathsep}action",
        "--add-data", f"core{os.pathsep}core",
        "--add-data", f"utils{os.pathsep}utils",
        # 排除不需要的大型库
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL",
        "--exclude-module", "pandas",
        "--exclude-module", "scipy",
        "--exclude-module", "tkinter",
        "main.py",
    ]

    print("[1/3] PyInstaller 编译中...")
    result = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=False)
    if result.returncode != 0:
        print("  ❌ PyInstaller 构建失败")
        return False
    print("  ✅ 编译完成")


def assemble_dist():
    """组装分发包"""
    print()
    print("[2/3] 组装分发包...")

    os.makedirs(DIST_DIR, exist_ok=True)

    # 1. 复制 PyInstaller 输出
    build_exe_dir = os.path.join(PROJECT_DIR, "dist", "雀魂MOD")
    if os.path.isdir(build_exe_dir):
        for item in os.listdir(build_exe_dir):
            src = os.path.join(build_exe_dir, item)
            dst = os.path.join(DIST_DIR, item)
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    # 2. 额外: 把 mitm addon 脚本也复制到发布目录 (独立于 exe)
    addon_src = os.path.join(PROJECT_DIR, "mitm", "addons.py")
    if os.path.isfile(addon_src):
        shutil.copy2(addon_src, os.path.join(DIST_DIR, "addon.py"))
        print("  ✅ addon.py (mitm 插件)")

    # 3. 模板目录
    templates_src = os.path.join(PROJECT_DIR, "templates")
    templates_dst = os.path.join(DIST_DIR, "templates")
    if os.path.isdir(templates_src):
        if os.path.exists(templates_dst):
            shutil.rmtree(templates_dst)
        shutil.copytree(templates_src, templates_dst)
        print("  ✅ templates/")
    else:
        os.makedirs(templates_dst, exist_ok=True)
        # 创建一个说明文件
        with open(os.path.join(templates_dst, "README.txt"), "w", encoding="utf-8") as f:
            f.write("按钮模板图片目录\n放置游戏截图裁剪的按钮图片以提高识别精度\n")

    # 4. 默认配置文件
    config_src = os.path.join(PROJECT_DIR, "config", "settings.json")
    if os.path.isfile(config_src):
        shutil.copy2(config_src, os.path.join(DIST_DIR, "settings.json"))
        print("  ✅ settings.json")

    # 5. 清理 PyInstaller 中间文件
    build_dir = os.path.join(PROJECT_DIR, "build")
    spec_file = os.path.join(PROJECT_DIR, "雀魂MOD.spec")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir)
    if os.path.isfile(spec_file):
        os.remove(spec_file)
    # 删除 PyInstaller 原始输出 (已复制)
    if os.path.isdir(build_exe_dir):
        shutil.rmtree(build_exe_dir)

    print("  ✅ 组装完成")


def create_readme():
    """创建使用说明"""
    print()
    print("[3/3] 创建使用说明...")

    readme = r"""╔══════════════════════════════════════════════════════╗
║       雀魂自动打牌 MOD v2.0 — 使用教程            ║
╚══════════════════════════════════════════════════════╝

【系统要求】
  Windows 10/11 64位
  Python 3.10+ (仅首次安装 mitmproxy 需要)
  浏览器: Chrome / Edge / Firefox

══════════════════════════════════════════════════════
  第一步: 安装依赖
══════════════════════════════════════════════════════

  打开 CMD 或 PowerShell，运行:

    pip install mitmproxy

  ⚠️ mitmproxy 必须单独安装，因为它以独立进程运行

══════════════════════════════════════════════════════
  第二步: 安装 CA 证书
══════════════════════════════════════════════════════

  1. 双击运行 雀魂MOD.exe
  2. 打开浏览器，设置代理:
       HTTP 代理:  127.0.0.1
       端口:       8080
  3. 浏览器访问 http://mitm.it
  4. 下载 Windows 证书 → 安装到「受信任的根证书颁发机构」
  5. 证书只需安装一次

  Windows 代理设置方法:
    设置 → 网络和 Internet → 代理 → 手动设置代理
    地址: 127.0.0.1  端口: 8080
    ✅ 勾选「对所有协议使用相同的代理服务器」

══════════════════════════════════════════════════════
  第三步: 启动 MOD
══════════════════════════════════════════════════════

  1. 双击 雀魂MOD.exe 启动
  2. 确保系统代理已设置为 127.0.0.1:8080
  3. 浏览器打开 https://game.mahjongsoul.com
  4. 进入匹配或好友房 → MOD 自动开始打牌

══════════════════════════════════════════════════════
  快捷键
══════════════════════════════════════════════════════

  F6  →  切换自动模式 (开启/暂停)
  F7  →  紧急停止 (立即停止所有操作)

══════════════════════════════════════════════════════
  仅监听模式 (不自动打牌)
══════════════════════════════════════════════════════

  命令行运行:
    雀魂MOD.exe --listen-only

  只显示牌局信息，AI 决策日志，不执行鼠标操作

══════════════════════════════════════════════════════
  配置修改
══════════════════════════════════════════════════════

  编辑同目录下的 settings.json:

    {
      "proxy_port": 8080,          // 代理端口
      "aggression": 3,             // AI 攻击性 (1-5)
      "speed": 3,                  // 速度偏好 (1-5)
      "risk_tolerance": 3,         // 风险容忍度 (1-5)
      "min_delay_ms": 300,         // 最小操作延迟
      "max_delay_ms": 1500,        // 最大操作延迟
      "auto_riichi": true,         // 自动立直
      "auto_call": true,           // 自动鸣牌
      "auto_agari": true           // 自动和牌
    }

══════════════════════════════════════════════════════
  常见问题
══════════════════════════════════════════════════════

  Q: 启动后没有反应?
  A: 检查系统代理是否设置正确 (127.0.0.1:8080)

  Q: 网页打不开?
  A: 需要先安装 mitmproxy CA 证书 → 访问 http://mitm.it

  Q: 按钮点不到?
  A: 将游戏窗口最大化，或在 templates/ 放入按钮截图

  Q: pip install mitmproxy 失败?
  A: 确保 Python 3.10+ 已安装且 pip 是最新版:
       python -m pip install --upgrade pip
       pip install mitmproxy

  Q: 如何卸载?
  A: 删除 MajsoulAutoMod 文件夹即可 (绿色软件)

══════════════════════════════════════════════════════
  免责声明
══════════════════════════════════════════════════════

  此软件仅供学习和研究用途。
  使用第三方辅助程序违反雀魂用户协议，可能导致封号。
  使用者自行承担所有风险。

══════════════════════════════════════════════════════
  GitHub: https://github.com/IQBoostPlus/MahjongSoulMod
══════════════════════════════════════════════════════
"""

    readme_path = os.path.join(DIST_DIR, "使用教程.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme)

    print(f"  ✅ 使用教程.txt")


def create_launcher_bat():
    """创建一键启动脚本"""
    bat_content = """@echo off
chcp 65001 >nul
title 雀魂自动打牌 MOD
echo ========================================
echo   雀魂自动打牌 MOD v2.0
echo ========================================
echo.
echo 正在启动...
echo.
cd /d "%~dp0"
start "" "雀魂MOD.exe"
echo.
echo MOD 已启动!
echo 请确保浏览器已设置代理 127.0.0.1:8080
echo 按 F6 切换自动模式 | F7 紧急停止
echo.
pause
"""
    bat_path = os.path.join(DIST_DIR, "启动雀魂MOD.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)
    print(f"  ✅ 启动雀魂MOD.bat")


def main():
    print()
    print("  目标目录:", DIST_DIR)
    print()

    clean_dist()
    if not build_exe():
        sys.exit(1)
    assemble_dist()
    create_readme()
    create_launcher_bat()

    print()
    print("=" * 60)
    print("  构建完成!")
    print(f"  输出目录: {DIST_DIR}")
    print()
    print("  文件清单:")
    for f in sorted(os.listdir(DIST_DIR)):
        full = os.path.join(DIST_DIR, f)
        if os.path.isfile(full):
            size = os.path.getsize(full)
            if size > 1024 * 1024:
                size_str = f"{size / 1024 / 1024:.1f} MB"
            elif size > 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            print(f"    {f:<30s} {size_str}")
        else:
            print(f"    {f:<30s} [目录]")
    print()
    print("  将 MajsoulAutoMod 文件夹复制到任意位置即可使用")
    print("=" * 60)


if __name__ == "__main__":
    main()
