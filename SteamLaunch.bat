@echo off
chcp 65001 >nul
title 雀魂 AutoMod - Steam 版
echo ================================================
echo   雀魂自动打牌 MOD v2.1 - Steam 客户端
echo ================================================
echo.
echo  [提示] 首次使用请先:
echo    1. 下载 Proxifier: https://www.proxifier.com
echo    2. 导入同目录下的 proxifier_profile.ppx
echo    3. 启动 Proxifier
echo.
echo  [免费方案]
echo    使用 Clash Verge TUN 模式
echo    规则: majsoul.exe --^> 127.0.0.1:8080
echo.
echo  按任意键启动...
pause >nul
echo  正在启动...
cd /d "%~dp0"
"MajsoulAutoMod.exe" --steam
pause
