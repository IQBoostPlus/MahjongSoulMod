# 雀魂自动打牌 MOD

基于 MITM 代理的雀魂 (Mahjong Soul) 自动打牌工具。

## 原理

```
Steam 客户端 → WebSocket → 雀魂服务器
                   │
             mitmproxy 拦截
                   │
             解码 liqi 协议
                   │
             AI 引擎决策 → 写入动作队列
```

## 使用方法

1. **以管理员身份**运行 `MajsoulAutoMod.exe`
2. 程序自动：
   - 启动 mitmproxy (端口 8080)
   - 设置 Windows 系统代理
3. 通过 Steam 启动雀魂
4. 进入对局即可自动打牌

### 首次使用

首次运行需要安装 mitmproxy 的 CA 证书：
1. 启动 MOD
2. 浏览器访问 http://mitm.it
3. 下载并安装证书到"受信任的根证书颁发机构"

### 停止

按 `Ctrl+C` 退出，程序自动恢复代理设置。

## 文件结构

```
MajsoulAutoMod.exe  — 启动器 (8MB, 单文件)
addon.py            — MITM 代理插件 (mitmdump -s addon.py)
launcher.py         — 启动器源码
```

## 依赖

- Python 3.10+
- mitmproxy (`pip install mitmproxy`)

## 构建

```bash
pip install pyinstaller mitmproxy
python -m PyInstaller --name "MajsoulAutoMod" --onefile --add-data "addon.py;." launcher.py
```

## 免责声明

仅供学习研究使用。使用第三方辅助程序违反雀魂用户协议。
