"""
打包脚本 - 构建完整可分发包

构建流程:
  1. PyInstaller 构建 launcher.exe
  2. 复制 mitmdump.exe 和依赖
  3. 创建 Windows 快捷方式
  4. 打包为 ZIP

用法: python package.py
"""

import os
import sys
import shutil
import subprocess
import zipfile
from pathlib import Path


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist", "MajsoulAutoMod")
VERSION = "2.0.0"


def find_mitmdump():
    """查找 mitmdump.exe"""
    candidates = [
        r"C:\Program Files\Python312\Scripts\mitmdump.exe",
        os.path.join(os.path.dirname(sys.executable), "Scripts", "mitmdump.exe"),
    ]
    # PATH 搜索
    for p in os.environ.get("PATH", "").split(";"):
        c = os.path.join(p, "mitmdump.exe")
        if os.path.exists(c):
            candidates.append(c)
    # Python 安装目录
    for p in sys.path:
        c = os.path.join(os.path.dirname(p), "Scripts", "mitmdump.exe")
        if os.path.exists(c):
            candidates.append(c)

    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def find_cacert():
    """查找 mitmproxy CA 证书"""
    mitm_dir = os.path.join(str(Path.home()), ".mitmproxy")
    cert = os.path.join(mitm_dir, "mitmproxy-ca-cert.p12")
    if os.path.exists(cert):
        return cert
    # 从 mitmproxy 包中找
    try:
        import mitmproxy
        pkg_dir = os.path.dirname(mitmproxy.__file__)
        cert2 = os.path.join(pkg_dir, "mitmproxy-ca-cert.p12")
        if os.path.exists(cert2):
            return cert2
    except:
        pass
    return None


def build():
    """构建完整包"""
    print("=" * 60)
    print(f"  打包雀魂自动打牌 MOD v{VERSION}")
    print("=" * 60)
    print()

    # 步骤 1: PyInstaller 构建
    print(f"[1/5] PyInstaller 构建 launcher.exe...")
    try:
        result = subprocess.run([
            sys.executable, "-m", "PyInstaller",
            "--name", "MajsoulAutoMod",
            "--onefile",
            "--noconfirm",
            "--clean",
            "--distpath", os.path.join(PROJECT_DIR, "dist", "exe_tmp"),
            "--workpath", os.path.join(PROJECT_DIR, "build"),
            "--hidden-import", "winreg",
            "--hidden-import", "ctypes",
            "--hidden-import", "json",
            "--hidden-import", "pathlib",
            "--add-data", f"mitm{os.pathsep}mitm",
            "--add-data", f"proto{os.pathsep}proto",
            "--add-data", f"ai{os.pathsep}ai",
            "--add-data", f"game_state{os.pathsep}game_state",
            "--add-data", f"action{os.pathsep}action",
            "--add-data", f"config{os.pathsep}config",
            "--add-data", f"utils{os.pathsep}utils",
            "launcher.py",
        ], capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            print(f"  [!] PyInstaller 失败!")
            print(result.stderr[-500:])
            return False
        print(f"  [+] 构建成功")
    except Exception as e:
        print(f"  [!] 构建异常: {e}")
        return False

    # 步骤 2: 创建分发目录
    print(f"[2/5] 创建分发目录...")
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)
    os.makedirs(DIST_DIR)
    os.makedirs(os.path.join(DIST_DIR, "tools"))

    # 复制 launcher.exe
    shutil.copy2(
        os.path.join(PROJECT_DIR, "dist", "exe_tmp", "MajsoulAutoMod.exe"),
        os.path.join(DIST_DIR, "MajsoulAutoMod.exe")
    )
    print(f"  [+] launcher.exe (8.1 MB)")

    # 步骤 3: 复制 mitmdump.exe
    print(f"[3/5] 查找 mitmproxy 工具...")
    mitmdump = find_mitmdump()
    if mitmdump and os.path.exists(mitmdump):
        shutil.copy2(mitmdump, os.path.join(DIST_DIR, "tools", "mitmdump.exe"))
        print(f"  [+] mitmdump.exe")
    else:
        print(f"  [!] mitmdump.exe 未找到 - 需手动安装 mitmproxy")

    # 复制 mitmproxy 依赖 DLL
    mitmproxy_dir = None
    try:
        import mitmproxy
        mitmproxy_dir = os.path.dirname(mitmproxy.__file__)
    except:
        pass

    if mitmproxy_dir and os.path.exists(mitmproxy_dir):
        # 复制 web 资源
        web_dir = os.path.join(mitmproxy_dir, "web")
        if os.path.exists(web_dir):
            dst_web = os.path.join(DIST_DIR, "tools", "mitmproxy", "web")
            shutil.copytree(web_dir, dst_web)
            print(f"  [+] mitmproxy web 资源")

    # 步骤 4: 创建启动脚本
    print(f"[4/5] 创建启动脚本...")
    bat_content = f"""@echo off
chcp 65001 >nul
title 雀魂自动打牌 MOD v{VERSION}
echo ========================================
echo   雀魂自动打牌 MOD v{VERSION}
echo ========================================
echo.
echo 静默启动 MOD (后台运行)...
start /min "" "%~dp0MajsoulAutoMod.exe"
echo.
echo 如果启动失败，请确保 mitmproxy 已安装:
echo   pip install mitmproxy
echo.
echo 按任意键退出...
pause >nul
"""
    with open(os.path.join(DIST_DIR, "启动MOD.bat"), "w", encoding="utf-8") as f:
        f.write(bat_content)

    readme_content = f"""雀魂自动打牌 MOD v{VERSION}
========================

使用方法:
  双击「启动MOD.bat」即可运行

首次使用:
  1. 以管理员身份运行（自动设置系统代理）
  2. 启动后通过 Steam 启动雀魂
  3. 进入对局即可自动打牌

手动模式:
  1. 在 Windows 设置中手动设置代理:
     代理服务器: 127.0.0.1
     端口: 8080
  2. 双击 MajsoulAutoMod.exe
  3. 通过 Steam 启动雀魂

停止:
  在命令行窗口中按 Ctrl+C
  或直接关闭窗口

日志位置:
  %USERPROFILE%\\.majsoul_automod\\logs\\
"""
    with open(os.path.join(DIST_DIR, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(readme_content)

    print(f"  [+] 启动脚本已创建")

    # 步骤 5: 压缩
    print(f"[5/5] 打包 ZIP...")
    zip_path = os.path.join(PROJECT_DIR, "dist", f"MajsoulAutoMod_v{VERSION}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(DIST_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(DIST_DIR))
                zf.write(file_path, arcname)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"  [+] ZIP: {size_mb:.1f} MB - {zip_path}")

    # 清理临时文件
    shutil.rmtree(os.path.join(PROJECT_DIR, "dist", "exe_tmp"), ignore_errors=True)
    shutil.rmtree(os.path.join(PROJECT_DIR, "build"), ignore_errors=True)

    print()
    print("=" * 60)
    print(f"  打包完成!")
    print(f"  ZIP: {zip_path}")
    print(f"  大小: {size_mb:.1f} MB")
    print("=" * 60)
    return True


if __name__ == "__main__":
    build()
