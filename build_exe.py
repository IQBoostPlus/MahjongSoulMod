#!/usr/bin/env python3
"""
Majsoul AutoMod - Build script to generate distributable .exe

Usage:
    python build_exe.py

Output: dist/MajsoulAutoMod/
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist", "MajsoulAutoMod")
EXE_NAME = "MajsoulAutoMod"


def clean_dist():
    """Clean old build artifacts"""
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
    """Build main exe with PyInstaller"""
    print("=" * 60)
    print("  Majsoul AutoMod - Building .exe")
    print("=" * 60)
    print()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--name", EXE_NAME,
        "--console",
        "--clean",
        "--noconfirm",
        "--hidden-import", "mitmproxy",
        "--hidden-import", "pyautogui",
        "--hidden-import", "pygetwindow",
        "--hidden-import", "cv2",
        "--hidden-import", "numpy",
        "--hidden-import", "pynput",
        "--add-data", f"config{os.pathsep}config",
        "--add-data", f"proto{os.pathsep}proto",
        "--add-data", f"ai{os.pathsep}ai",
        "--add-data", f"game_state{os.pathsep}game_state",
        "--add-data", f"action{os.pathsep}action",
        "--add-data", f"core{os.pathsep}core",
        "--add-data", f"utils{os.pathsep}utils",
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL",
        "--exclude-module", "pandas",
        "--exclude-module", "scipy",
        "--exclude-module", "tkinter",
        "main.py",
    ]

    print("[1/3] PyInstaller compiling...")
    result = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=False)
    if result.returncode != 0:
        print("  [FAIL] PyInstaller build failed")
        return False
    print("  [OK] Compile done")


def assemble_dist():
    """Assemble distribution package"""
    print()
    print("[2/3] Assembling distribution...")

    os.makedirs(DIST_DIR, exist_ok=True)

    # 1. Copy PyInstaller output
    build_exe_dir = os.path.join(PROJECT_DIR, "dist", EXE_NAME)
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

    # 2. Copy mitm addon script
    addon_src = os.path.join(PROJECT_DIR, "mitm", "addons.py")
    if os.path.isfile(addon_src):
        shutil.copy2(addon_src, os.path.join(DIST_DIR, "addon.py"))
        print("  [OK] addon.py")

    # 3. Templates directory
    templates_src = os.path.join(PROJECT_DIR, "templates")
    templates_dst = os.path.join(DIST_DIR, "templates")
    if os.path.isdir(templates_src) and os.listdir(templates_src):
        if os.path.exists(templates_dst):
            shutil.rmtree(templates_dst)
        shutil.copytree(templates_src, templates_dst)
        print("  [OK] templates/")
    else:
        os.makedirs(templates_dst, exist_ok=True)

    # 4. Default config
    config_src = os.path.join(PROJECT_DIR, "config", "settings.json")
    if os.path.isfile(config_src):
        shutil.copy2(config_src, os.path.join(DIST_DIR, "settings.json"))
        print("  [OK] settings.json")

    # 5. Clean PyInstaller intermediates
    build_dir = os.path.join(PROJECT_DIR, "build")
    spec_file = os.path.join(PROJECT_DIR, f"{EXE_NAME}.spec")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir)
    if os.path.isfile(spec_file):
        os.remove(spec_file)
    if os.path.isdir(build_exe_dir):
        shutil.rmtree(build_exe_dir)

    print("  [OK] Assembly done")


def create_tutorial():
    """Create usage tutorial file"""
    print()
    print("[3/3] Creating tutorial...")

    tutorial = """============================================================
       Majsoul AutoMod v2.0 - Tutorial
============================================================

[System Requirements]
  Windows 10/11 64-bit
  Python 3.10+ (only needed for initial mitmproxy install)
  Browser: Chrome / Edge / Firefox

============================================================
  Step 1: Install mitmproxy
============================================================

  Open CMD or PowerShell and run:

    pip install mitmproxy

  mitmproxy must be installed separately (runs as a separate
  process from the MOD).

============================================================
  Step 2: Install CA Certificate
============================================================

  1. Double-click MajsoulAutoMod.exe (or Launch.bat)
  2. Set system proxy to 127.0.0.1:8080
  3. Visit http://mitm.it in your browser
  4. Download Windows certificate and install it to
     "Trusted Root Certification Authorities"
  5. Certificate only needs to be installed once

  Windows proxy settings:
    Settings -> Network & Internet -> Proxy -> Manual setup
    Address: 127.0.0.1  Port: 8080

============================================================
  Step 3: Start MOD and play
============================================================

  1. Double-click MajsoulAutoMod.exe (or Launch.bat)
  2. Ensure system proxy is set to 127.0.0.1:8080
  3. Open https://game.mahjongsoul.com in browser
  4. Enter a match -> MOD plays automatically

============================================================
  Hotkeys
============================================================

  F6  ->  Toggle auto mode (on/off)
  F7  ->  Emergency stop

============================================================
  Listen-only mode (no auto-play)
============================================================

  Run from command line:
    MajsoulAutoMod.exe --listen-only

  Displays game info and AI analysis without clicking.

============================================================
  Configuration (settings.json)
============================================================

  Edit settings.json in the same folder:

    proxy_port       Proxy port (default 8080)
    aggression       AI aggression 1-5 (default 3)
    speed            Speed preference 1-5 (default 3)
    risk_tolerance   Risk tolerance 1-5 (default 3)
    min_delay_ms     Min action delay ms (default 300)
    max_delay_ms     Max action delay ms (default 1500)
    auto_riichi      Auto riichi true/false
    auto_call        Auto meld true/false
    auto_agari       Auto win true/false

============================================================
  FAQ
============================================================

  Q: Nothing happens after startup?
  A: Check proxy is set to 127.0.0.1:8080

  Q: Web pages won't load?
  A: Install mitmproxy CA cert -> visit http://mitm.it

  Q: Button clicks miss?
  A: Maximize game window, or add button screenshots
     to templates/ folder

  Q: pip install mitmproxy fails?
  A: Make sure Python 3.10+ is installed:
       python --version
       python -m pip install --upgrade pip
       pip install mitmproxy

  Q: How to uninstall?
  A: Delete the MajsoulAutoMod folder (portable, no
     registry entries)

============================================================
  Disclaimer
============================================================

  This software is for educational and research purposes
  only. Using third-party tools violates Mahjong Soul's
  Terms of Service and may result in a ban. Use at your
  own risk.

============================================================
  GitHub: https://github.com/IQBoostPlus/MahjongSoulMod
============================================================
"""

    tutorial_path = os.path.join(DIST_DIR, "Tutorial.txt")
    with open(tutorial_path, "w", encoding="utf-8") as f:
        f.write(tutorial)

    print(f"  [OK] Tutorial.txt")


def create_launcher_bat():
    """Create launcher batch file"""
    bat_content = """@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Majsoul AutoMod
echo ========================================
echo   Majsoul AutoMod v2.0
echo ========================================
echo.
echo Starting... Close this window to stop MOD
echo.
cd /d "%~dp0"
"MajsoulAutoMod.exe"
echo.
echo MOD stopped
pause
"""
    bat_path = os.path.join(DIST_DIR, "Launch.bat")
    with open(bat_path, "w", encoding="utf-8-sig") as f:
        f.write(bat_content)
    print(f"  [OK] Launch.bat")


def main():
    print()
    print("  Output dir:", DIST_DIR)
    print()

    clean_dist()
    if not build_exe():
        sys.exit(1)
    assemble_dist()
    create_tutorial()
    create_launcher_bat()

    print()
    print("=" * 60)
    print("  Build complete!")
    print(f"  Output: {DIST_DIR}")
    print()
    print("  Files:")
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
            print(f"    {f:<30s} [dir]")
    print()
    print("  Copy MajsoulAutoMod folder anywhere to use")
    print("=" * 60)


if __name__ == "__main__":
    main()
