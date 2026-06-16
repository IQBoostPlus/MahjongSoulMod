# CLAUDE.md — MajsoulAutoMod

雀魂自动打牌 MOD — 基于 MITM 代理 + AI 引擎的麻将自动决策系统。

## 架构

```
雀魂客户端 ──WebSocket──► 游戏服务器
              │
        mitmproxy 拦截
              │
        LiqiDecoder (2层: Wrapper + 内层Protobuf)
              │
        GameTracker (状态重建) ──► EventBus ──► AIDecisionMaker
              │                                      │
              └──────────────────────────────────────┘
                                                     │
                                              ActionExecutor
                                              (pyautogui 鼠标模拟)
```

### 核心模块

| 模块 | 职责 |
|------|------|
| `core/events.py` | 事件总线 (pub/sub)，解耦各子系统 |
| `core/context.py` | AppContext 单例容器，统一组件实例 |
| `proto/` | liqi 协议编解码 (Protobuf 两层解析) |
| `mitm/addons.py` | mitmproxy 插件 — 拦截 WebSocket |
| `game_state/tracker.py` | 牌局状态增量重建 |
| `ai/engine.py` | AI 决策 — 牌效率/防守/鸣牌/立直 |
| `ai/shanten.py` | 向听数计算 (标准/七对子/国士) |
| `action/executor.py` | 鼠标模拟 + 图像识别按钮 |
| `config/` | 全局配置 (settings.json) |

## 关键修复 (2024-06-14)

1. **Proto 内层解析**: 修复了只解析 Wrapper 外层、内层消息(bytes)未解码的致命 bug
2. **组件通信**: 引入 EventBus + AppContext，修复 main.py 和 addons.py 各创建独立实例的问题
3. **Config 路径**: 修复 `config/config/settings.json` 双写 bug
4. **策略漂移**: 修复 `_update_strategy` 参数每局累加不重置的问题
5. **AI 增强**: 添加 DoraCalculator、增强 DefenseAnalysis (筋/壁/早巡)、shanten 缓存
6. **快捷键**: 实现 F6(切换)/F7(停止) 全局热键

## 关键修复 (2024-06-15)

### Bug #1: `last_action` 未设置为 "draw" (致命)
- **位置**: `game_state/tracker.py:_on_draw_tile()`
- **问题**: 自家摸牌后未设置 `last_action = "draw"`，导致 `context.py` 中 `state.last_action == "draw"` 条件永远为 False，AI 永远不会被触发出牌决策
- **修复**: 在 `_on_draw_tile()` 自家摸牌分支中添加 `self.state.last_action = "draw"` 和 `self.state.last_discard = -1`

### Bug #2: `_should_kan` 要求错误的手牌数量
- **位置**: `ai/engine.py:_should_kan()`
- **问题**: 明杠 (对手舍牌时叫杠) 需要手中有 3 张相同牌 + 对手打出的 1 张，但代码检查 `hand.count(tile) < 4` (需要4张)
- **修复**: 改为 `hand.count(tile) < 3`，添加注释区分明杠/加杠/暗杠场景

### Bug #3: 自家舍牌也触发鸣牌判断
- **位置**: `core/context.py:_on_discard_tile()`
- **问题**: DISCARD_TILE 事件处理未区分自家和对手舍牌，对自家舍牌也进行吃/碰/杠判断
- **修复**: 添加 `last_discard_seat` 字段到 GameState，在 handler 中跳过自家舍牌 (`last_discard_seat == self_seat`)

### 移动端 (APP) 适配
- **新增**: `action/mobile_executor.py` — 基于 ADB 的触屏模拟执行器
- **新增**: `config` 添加 `platform` 和 `adb_device_id` 配置项
- **新增**: `core/context.py` 根据 platform 配置自动选择桌面端/移动端执行器
- **移动端特性**: ADB 设备自动检测、屏幕尺寸自适应、竖屏/横屏布局切换、拟人化延迟

## 测试

```bash
python tests/test_shanten.py     # 12 项向听数测试
python tests/test_regression.py  # 15 项回归测试 (Bug修复验证+集成+AI+移动端)
```

## 运行

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 (自动模式)
python main.py

# 启动 (仅监听)
python main.py --listen-only
```

## 测试

```bash
python tests/test_shanten.py  # 12 项向听数测试
```

## 已知限制

- 按钮检测优先用模板匹配，无模板时回退到硬编码坐标
- 协议基于公开逆向，可能不完全
- 未实现 WebSocket 断线重连
- 尚未实现图像识别手牌精确定位
