# 雀魂自动打牌 MOD (MajiSoul AutoMod)

> **声明**: 此项目仅供学习和研究用途。使用第三方辅助程序违反雀魂用户协议，可能导致封号，请自行承担风险。

## 简介

基于 **MITM 代理** + **AI 引擎**的雀魂自动打牌 MOD。通过拦截 WebSocket 网络包解码游戏状态，使用麻将 AI 决策后模拟鼠标点击。

### 架构

```
雀魂客户端 ──WebSocket (Protobuf)──► 游戏服务器
                │
          mitmproxy 拦截
                │
          ┌─────┘
          ▼
     Liqi 协议解码器
          │
          ▼
     GameTracker (状态重建)
          │
          ├── ShantenCalculator (向听数计算)
          ├── TileEfficiency (牌效率)
          ├── DefenseAnalysis (防守分析)
          └── AIDecisionMaker (决策)
                │
                ▼
     ActionExecutor (pyautogui 鼠标模拟)
```

### 文件结构

```
MajsoulAutoMod/
├── main.py                  # 主入口
├── setup.py                 # 一键安装器
├── requirements.txt         # 依赖
├── proto/
│   ├── __init__.py          # liqi 协议编解码器
│   └── liqi.proto           # Protobuf 协议定义
├── mitm/
│   └── addons.py            # mitmproxy 插件
├── game_state/
│   └── tracker.py           # 对局状态追踪
├── ai/
│   ├── shanten.py           # 向听数计算 (3种: 标准/七对子/国士)
│   └── engine.py            # AI 决策引擎
├── action/
│   └── executor.py          # 动作执行 (鼠标模拟)
├── config/
│   └── __init__.py          # 配置中心
├── utils/
│   └── log.py               # 日志系统
├── tests/
│   └── test_shanten.py      # 向听数测试 (12项)
└── setup/
    └── installer.py         # 安装程序
```

## 安装

### 方式一: 一键安装

```bash
python setup.py
```

### 方式二: 手动安装

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行 MOD
python main.py
```

## 使用

### 1. 启动 MOD

```bash
python main.py
```

### 2. 设置系统代理

| 设置 | 值 |
|------|-----|
| HTTP 代理 | `127.0.0.1:8080` |
| HTTPS 代理 | `127.0.0.1:8080` |

### 3. 信任 CA 证书

首次运行需要安装 mitmproxy 的 CA 证书:
- 访问 [http://mitm.it](http://mitm.it)
- 下载并安装 `mitmproxy-ca-cert.p12`

### 4. 打开雀魂

- 浏览器打开 [https://game.mahjongsoul.com](https://game.mahjongsoul.com)
- 或通过 Steam 客户端启动 (需通过命令行设置代理)

### 5. 进入对局

进入匹配或好友房后，MOD 会自动开始打牌。

### 快捷键

| 按键 | 功能 |
|------|------|
| `F6` | 切换自动模式 |
| `F7` | 紧急停止 |

### 仅监听模式

```bash
python main.py --listen-only
```

只显示牌局信息，不自动操作。

## AI 引擎

| 功能 | 状态 |
|------|------|
| 向听数计算 (标准手) | ✅ |
| 向听数计算 (七对子) | ✅ |
| 向听数计算 (国士无双) | ✅ |
| 牌效率分析 | ✅ |
| 防守分析 (现物/筋/壁) | ✅ |
| 鸣牌决策 (吃/碰/杠) | ✅ |
| 立直决策 | ✅ |
| 和牌决策 | ✅ |
| 策略控制 (局况调整) | ✅ |
| 人机化延迟 | ✅ |

## 协议参考

雀魂使用 `liqi` 协议通过 WebSocket 通信，消息使用 Protobuf 编码:

- `liqi.proto` — 协议定义 (基于公开逆向)
- 消息类型: `NewRound`, `DrawTile`, `DiscardTile`, `Hu`, `Liqi` 等
- 牌编码: 0-8(万) 9-17(筒) 18-26(索) 27-33(字)

## 对比旧版 (BepInEx 版)

| 对比项 | BepInEx 版 (V1) | MITM 版 (V2) |
|--------|-----------------|--------------|
| 数据来源 | Unity 场景遍历 | WebSocket 网络包 |
| 状态完整度 | ⚠️ 碎片化 | ✅ 完整牌局状态 |
| 反检测 | ❌ 进程注入 | ✅ 网络代理 |
| 跨版本 | 每更新需适配 | 协议较稳定 |
| 执行方式 | Harmony/反射 | 鼠标模拟 |
| 语言 | C# | Python |
| 开发复杂度 | 高 | 中 |

## License

AGPL-3.0
