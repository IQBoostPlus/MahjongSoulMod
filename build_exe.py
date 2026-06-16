#!/usr/bin/env python3
"""
Majsoul AutoMod v2.2 - Build script to generate distributable .exe

Usage:
    python build_exe.py                  # Full build (vision + MITM)
    python build_exe.py --vision-only    # Vision-only (no MITM, ~150MB)
    python build_exe.py --full           # Full build (vision + MITM, ~265MB)

Output: dist/MajsoulAutoMod/ or dist/MajsoulAutoMod_Vision/
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
EXE_NAME = "MajsoulAutoMod"

# 默认完整构建
_vision_only = False  # 命令行解析后设置


def get_dist_dir():
    """根据构建模式返回输出目录"""
    base = os.path.join(PROJECT_DIR, "dist")
    if _vision_only:
        return os.path.join(base, "MajsoulAutoMod_Vision")
    return os.path.join(base, "MajsoulAutoMod")


def clean_dist():
    """Clean old build artifacts"""
    dist_dir = get_dist_dir()
    # 只清理当前构建模式的目标目录
    build_dir = os.path.join(PROJECT_DIR, "build")
    for d in [build_dir, dist_dir]:
        if os.path.isdir(d):
            shutil.rmtree(d)
    for f in Path(PROJECT_DIR).glob("*.spec"):
        if f.name not in ("MajsoulAutoMod.spec", "MajsoulAutoMod_v2.spec"):
            f.unlink()


def build_exe():
    """Build main exe with PyInstaller"""
    mode_str = "Vision-Only" if _vision_only else "Full (Vision + MITM)"
    print("=" * 60)
    print(f"  Majsoul AutoMod v2.2 - Building .exe ({mode_str})")
    print("=" * 60)
    print()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--name", EXE_NAME,
        "--console",
        "--clean",
        "--noconfirm",
    ]

    # ── Hidden imports ──
    _add_hidden_import(cmd, "pyautogui")
    _add_hidden_import(cmd, "pygetwindow")
    _add_hidden_import(cmd, "cv2")
    _add_hidden_import(cmd, "numpy")
    _add_hidden_import(cmd, "pynput")
    _add_hidden_import(cmd, "json")
    _add_hidden_import(cmd, "urllib.request")
    _add_hidden_import(cmd, "airtest")
    _add_hidden_import(cmd, "airtest.core.api")
    _add_hidden_import(cmd, "airtest.core.cv")
    _add_hidden_import(cmd, "dxcam")
    _add_hidden_import(cmd, "PIL")

    # mitmproxy: 仅在完整构建时包含
    if not _vision_only:
        _add_hidden_import(cmd, "mitmproxy")

    # ── Data directories ──
    _add_data(cmd, "config")
    _add_data(cmd, "proto")
    _add_data(cmd, "ai")
    _add_data(cmd, "game_state")
    _add_data(cmd, "action")
    _add_data(cmd, "core")
    _add_data(cmd, "utils")
    _add_data(cmd, "dashboard")
    _add_data(cmd, "templates")
    _add_data(cmd, "vision")

    # MITM addon: 仅在完整构建时包含
    if not _vision_only:
        _add_data(cmd, "mitm")

    # ── Exclude heavy unused modules ──
    cmd += [
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL",
        "--exclude-module", "pandas",
        "--exclude-module", "scipy",
        "--exclude-module", "tkinter",
    ]

    # 主入口
    cmd.append("main.py")

    print("[1/3] PyInstaller compiling...")
    if _vision_only:
        print("  (Vision-only: skipping mitmproxy — saves ~115MB)")
    result = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=False)
    if result.returncode != 0:
        print("  [FAIL] PyInstaller build failed")
        return False
    print("  [OK] Compile done")
    return True


def _add_hidden_import(cmd, module):
    cmd += ["--hidden-import", module]


def _add_data(cmd, dir_name):
    cmd += ["--add-data", f"{dir_name}{os.pathsep}{dir_name}"]


def assemble_dist():
    """Assemble distribution package"""
    print()
    print("[2/3] Assembling distribution...")

    dist_dir = get_dist_dir()
    os.makedirs(dist_dir, exist_ok=True)

    # 1. Copy PyInstaller output
    build_exe_dir = os.path.join(PROJECT_DIR, "dist", EXE_NAME)
    if os.path.isdir(build_exe_dir):
        for item in os.listdir(build_exe_dir):
            src = os.path.join(build_exe_dir, item)
            dst = os.path.join(dist_dir, item)
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    # 2. Copy mitm addon script (完整构建时)
    if not _vision_only:
        addon_src = os.path.join(PROJECT_DIR, "mitm", "addons.py")
        if os.path.isfile(addon_src):
            shutil.copy2(addon_src, os.path.join(dist_dir, "addon.py"))
            print("  [OK] addon.py (MITM)")
    else:
        print("  [--] addon.py skipped (vision-only)")

    # 3. Copy templates (dashboard.html etc)
    templates_src = os.path.join(PROJECT_DIR, "templates")
    templates_dst = os.path.join(dist_dir, "templates")
    if os.path.isdir(templates_src) and os.listdir(templates_src):
        if os.path.exists(templates_dst):
            shutil.rmtree(templates_dst)
        shutil.copytree(templates_src, templates_dst)
        print("  [OK] templates/")
    else:
        os.makedirs(templates_dst, exist_ok=True)

    # 4. Copy default config to exe directory (user-editable)
    config_src = os.path.join(PROJECT_DIR, "config", "settings.json")
    if os.path.isfile(config_src):
        shutil.copy2(config_src, os.path.join(dist_dir, "settings.json"))
        print("  [OK] settings.json")

    # 5. Clean PyInstaller intermediates
    build_dir = os.path.join(PROJECT_DIR, "build")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir)
    for f in Path(PROJECT_DIR).glob("*.spec"):
        if f.name not in ("MajsoulAutoMod.spec", "MajsoulAutoMod_v2.spec"):
            f.unlink()
    if os.path.isdir(build_exe_dir):
        shutil.rmtree(build_exe_dir)

    print("  [OK] Assembly done")
    return True


def create_tutorial():
    """Create usage tutorial file"""
    print()
    print("[3/3] Creating tutorial...")

    dist_dir = get_dist_dir()
    if _vision_only:
        mitm_note = "  MITM proxy mode: NOT included (vision-only build)"
        size_note = "~150MB"
    else:
        mitm_note = "  MITM proxy mode: MajsoulAutoMod.exe --mitm"
        size_note = "~265MB"

    tutorial = f"""============================================================
       Majsoul AutoMod v2.2 (Vision-First) - Tutorial
============================================================

[Build Info]
  Type: {'Vision-Only' if _vision_only else 'Full (Vision + MITM)'}
  Size: {size_note}

[System Requirements]
  Windows 10/11 64-bit
  Python NOT required (standalone .exe)

============================================================
  Step 1: Start the MOD
============================================================

  Double-click Launch.bat or run in terminal:
    MajsoulAutoMod.exe

  Vision mode is DEFAULT — no proxy, no certificate, no setup.

============================================================
  Step 2: Open Mahjong Soul
============================================================

  Open in browser: https://game.mahjongsoul.com
  Or via Steam client
  Or on mobile (ADB mode)

  The MOD auto-detects your game window and starts playing.

============================================================
  Step 3 (first time): Collect tile templates
============================================================

  Run while playing:
    python scripts/auto_collect_templates.py

  This collects your game's tile images for accurate recognition.
  Templates are saved to vision/templates/tiles/

  Or use pre-built templates:
    python scripts/download_majsoul_tiles.py

============================================================
  Dashboard (Web UI)
============================================================

  Open browser and visit:
    http://127.0.0.1:8083

  Features:
    - Real-time game state display
    - AI decision log (live SSE updates)
    - Opponent tracking (discards, melds, riichi)

============================================================
  Modes
============================================================

  Vision mode (default):    MajsoulAutoMod.exe
  Vision listen-only:       MajsoulAutoMod.exe --listen-only
{mitm_note}
  Steam mode:               MajsoulAutoMod.exe --steam

============================================================
  Hotkeys
============================================================

  F6  ->  Toggle auto mode (on/off)
  F7  ->  Emergency stop
  F8  ->  Capture hand tiles (template collection mode)

============================================================
  Configuration (settings.json)
============================================================

  Edit settings.json in the same folder as the .exe:

    dashboard_port       Dashboard UI port (default 8083)
    platform             "desktop" or "mobile"
    browser_type         "chrome" / "edge" / "steam"
    aggression           AI aggression 1-5 (default 3)
    speed                Speed preference 1-5 (default 3)
    risk_tolerance       Risk tolerance 1-5 (default 3)
    min_delay_ms         Min action delay ms (default 300)
    max_delay_ms         Max action delay ms (default 1500)

============================================================
  Disclaimer
============================================================

  This software is for educational and research purposes
  only. Using third-party tools violates Mahjong Soul's
  Terms of Service and may result in a ban. Use at your
  own risk.

============================================================
"""

    tutorial_path = os.path.join(get_dist_dir(), "Tutorial.txt")
    with open(tutorial_path, "w", encoding="utf-8") as f:
        f.write(tutorial)
    print(f"  [OK] Tutorial.txt")


def create_launcher_bat():
    """Create launcher batch file"""
    mode_label = "Vision-Only" if _vision_only else "Vision Mode"
    bat_content = f"""@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Majsoul AutoMod v2.2 ({mode_label})
echo ========================================
echo   Majsoul AutoMod v2.2 ({mode_label})
echo ========================================
echo.
echo   No proxy needed! Just open the game.
echo   Dashboard: http://127.0.0.1:8083
echo.
echo   Starting... Close this window to stop
echo.
cd /d "%~dp0"
"MajsoulAutoMod.exe"
echo.
echo MOD stopped
pause
"""

    bat_path = os.path.join(get_dist_dir(), "Launch.bat")
    with open(bat_path, "w", encoding="utf-8-sig") as f:
        f.write(bat_content)
    print(f"  [OK] Launch.bat")


def main():
    global _vision_only

    # 解析命令行参数
    if "--vision-only" in sys.argv:
        _vision_only = True
    elif "--full" in sys.argv:
        _vision_only = False

    dist_dir = get_dist_dir()
    print()
    print(f"  Build mode: {'Vision-Only (~150MB)' if _vision_only else 'Full (~265MB)'}")
    print(f"  Output dir: {dist_dir}")
    print()

    try:
        clean_dist()
    except PermissionError:
        print("  [WARN] Some files locked, skipping clean...")
    if not build_exe():
        sys.exit(1)
    if not assemble_dist():
        sys.exit(1)
    create_tutorial()
    create_launcher_bat()

    print()
    print("=" * 60)
    print("  Build complete!")
    print(f"  Output: {dist_dir}")
    print()
    print("  Files:")
    for f in sorted(os.listdir(dist_dir)):
        full = os.path.join(dist_dir, f)
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
            print(f"    {f:<30s} [dir]")
    print()
    print("  Copy the output folder anywhere to use")
    print("=" * 60)


if __name__ == "__main__":
    main()
