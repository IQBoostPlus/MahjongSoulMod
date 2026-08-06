# CLAUDE.md — MajsoulAutoMod v2.4

雀魂自动打牌 MOD — Vision-First 视觉识别 + MITM 代理 + AI 引擎的麻将自动决策系统。

## 架构

```
雀魂客户端 ──WebSocket──► 游戏服务器
      │                        │
      │                  mitmproxy 拦截
      │                        │
  Vision Pipeline        LiqiDecoder (Protobuf)
  (屏幕截图+识别)              │
      │                 GameTracker (状态重建)
      │                        │
      └────────┬───────────────┘
               │
           EventBus ──► AIDecisionMaker
               │                │
               └────────────────┘
                        │
                 ActionExecutor
                 (pyautogui 鼠标模拟)
```

### 核心模块

| 模块 | 职责 |
|------|------|
| `core/events.py` | 事件总线 (pub/sub)，解耦各子系统 |
| `core/context.py` | AppContext 单例容器，支持 Vision/MITM 双模式 |
| `vision/tiles.py` | **牌面识别引擎** — SIFT 特征匹配 (v2.4) + 模板匹配兜底 |
| `vision/capture.py` | 帧采集 — DXcam (3ms) / PIL / ADB 三后端 |
| `vision/pipeline.py` | 视觉管线编排 — 采集→ROI→识别→VisionFrame |
| `vision/regions.py` | ROI 区域定义 — 全屏百分比坐标 |
| `vision/differ.py` | 帧差分 — StatefulDiffer (3 帧迟滞) |
| `vision/classifier.py` | ONNX 神经网络分类器框架 (缺模型文件) |
| `proto/` | liqi 协议编解码 (Protobuf 两层解析) |
| `mitm/addons.py` | mitmproxy 插件 — 拦截 WebSocket |
| `game_state/tracker.py` | 牌局状态增量重建 |
| `ai/engine.py` | AI 决策 — 牌效率/防守/鸣牌/立直 |
| `ai/shanten.py` | 向听数计算 (标准/七对子/国士) |
| `action/executor.py` | 鼠标模拟 + 图像识别按钮 |
| `config/` | 全局配置 (settings.json) |

## 牌面识别 (v2.4)

### SIFT 特征匹配引擎 (主)

SIFT 匹配形状关键点，对亮度/对比度/主题不变：

1. **原始图像 SIFT** → 同主题匹配 (浅→浅): **97%** 准确率
2. **Canny 边缘 SIFT** → 跨主题匹配 (浅↔深): **89%** 准确率
   - 边缘图对颜色反转完全不变
3. **ORB 降级** → CPU 友好的轻量备用
4. **模板匹配** → CCORR_NORMED + 灰度反转 + 多尺度 (最终兜底)

### 牌编码

```
0-8   = 万子 (1m-9m)    9-17  = 筒子 (1p-9p)
18-26 = 索子 (1s-9s)    27-33 = 字牌 (东南西北白发中)
34-36 = 赤宝牌 (赤5万, 赤5筒, 赤5索)
```

## 测试

```bash
# 全部测试 (99 项)
python -m unittest discover tests/ -v

# 分套件
python -m unittest tests.test_shanten        # 12 项向听数
python -m unittest tests.test_regression      # 15 项回归
python -m unittest tests.test_vision          # 25 项视觉管线
python -m unittest tests.test_tile_recognition # 47 项牌识别 (含 24 项 SIFT)
```

## 运行

```bash
# 安装依赖
pip install -r requirements.txt

# Vision-First 模式 (默认, 屏幕截图识别)
python main.py --vision

# MITM 代理模式 (需要 mitmproxy)
python main.py --mitm

# 仅监听
python main.py --listen-only

# 实机视觉测试
python scripts/test_vision_live.py
```

## 已知限制

- SIFT 跨主题匹配筒子牌准确率约 78% (同心圆特征难区分)
- ONNX 神经网络模型文件缺失 (网络限制)
- 按钮检测优先用模板匹配，无模板时回退到硬编码坐标
- 未在真实对局中端到端测试完整闭环
