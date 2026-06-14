"""
雀魂自动打牌 MOD - 一键安装器

用法: python setup.py [install|uninstall]
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def install():
    """一键安装"""
    print("=" * 50)
    print("  雀魂自动打牌 MOD v2.0 - 一键安装")
    print("=" * 50)
    print()

    # 1. 检查 Python 版本
    print("[1/4] 检查 Python 环境...")
    py_ver = sys.version_info
    if py_ver.major < 3 or (py_ver.major == 3 and py_ver.minor < 10):
        print(f"  ❌ 需要 Python 3.10+, 当前: {py_ver.major}.{py_ver.minor}")
        print("     请从 https://www.python.org/downloads/ 下载")
        return
    print(f"  ✅ Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}")

    # 2. 安装依赖
    print()
    print("[2/4] 安装依赖包...")
    req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if os.path.exists(req_path):
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", req_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("  ✅ 依赖安装完成")
        else:
            print(f"  ⚠️ 部分依赖安装失败: {result.stderr[:200]}")
    else:
        print("  ⚠️ requirements.txt 不存在")

    # 3. 配置
    print()
    print("[3/4] 初始化配置...")
    config_dir = os.path.join(str(Path.home()), ".majsoul_automod")
    os.makedirs(config_dir, exist_ok=True)
    print(f"  ✅ 配置目录: {config_dir}")

    # 4. 创建快捷方式
    print()
    print("[4/4] 创建启动脚本...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bat_path = os.path.join(script_dir, "启动雀魂MOD.bat")

    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(f"""@echo off
chcp 65001 >nul
title 雀魂自动打牌 MOD
echo ========================================
echo   雀魂自动打牌 MOD v2.0
echo ========================================
echo.
echo 正在启动 MOD...
echo 提示: 请确保浏览器已设置代理 127.0.0.1:8080
echo.
cd /d "{script_dir}"
python main.py
pause
""")
    print(f"  ✅ 启动脚本: {bat_path}")
    print()

    # 完成
    print("=" * 50)
    print("  安装完成!")
    print()
    print("  使用方式:")
    print("  1. 双击「启动雀魂MOD.bat」")
    print("  2. 设置系统代理为 127.0.0.1:8080")
    print("  3. 在浏览器中打开雀魂网页版")
    print("  4. 进入对局即可自动打牌")
    print()
    print("  ℹ️ 首次运行需要安装 mitmproxy CA 证书")
    print("     访问 http://mitm.it 下载并信任")
    print("=" * 50)


def uninstall():
    """卸载"""
    config_dir = os.path.join(str(Path.home()), ".majsoul_automod")

    print("正在卸载...")
    if os.path.exists(config_dir):
        shutil.rmtree(config_dir)
        print(f"  已删除配置目录: {config_dir}")
    print("卸载完成")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "uninstall":
        uninstall()
    else:
        install()
