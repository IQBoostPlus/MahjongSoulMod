# MajsoulAutoMod v2.2 — 项目状态总结

> 最后更新: 2026-06-16

---

## ✅ 已完成

### 核心架构: Vision-First 视觉识别管线

用屏幕截图 + 图像识别替代 MITM 代理拦截, 零配置即可使用。

| 模块 | 文件 | 状态 |
|------|------|------|
| 帧采集 | `vision/capture.py` | ✅ DXcam (3ms) / PIL (50ms) / ADB 三后端 |
| ROI 区域定义 | `vision/regions.py` | ✅ 全屏百分比坐标, 手牌 83-94% 已校准 |
| 牌面识别 | `vision/tiles.py` | ✅ 多尺度模板匹配 + Canny 边缘 + CCORR_NORMED |
| 管线编排 | `vision/pipeline.py` | ✅ VisionFrame 输出, 采集→识别→组装 |
| 帧差分 | `vision/differ.py` | ✅ StateDiffer + StatefulDiffer(3帧迟滞) |
| 事件桥接 | `vision/processor.py` | ✅ VisionEvent → GameTracker, 与 MITM 同接口 |
| 按钮检测 | `vision/buttons.py` | ⚠️ Airtest/OpenCV/坐标回退, 缺按钮模板图片 |
| 动作验证 | `vision/verifier.py` | ✅ Plan→Execute→Verify 闭环, 3次重试 |
| 视觉执行器 | `vision/executor.py` | ✅ VisionActionExecutor, 带 fallback |
| ONNX 分类器 | `vision/classifier.py` | ✅ 模型加载框架 + 自举训练器, 缺 ONNX 模型文件 |

### 牌面模板

| 来源 | 数量 | 状态 |
|------|------|------|
| GitHub majsoul-generator | 37/37 | ✅ 已下载 (浅色主题, 80x129px) |
| 用户深色主题 | 11/34 | ⚠️ 已标注 (5,7,11,12,13,15,17,18,19,23,24) |
| 合成模板 | 37/37 | ✅ 备用 (中文字体生成) |

### AppContext 重构

- ✅ DI 注入模式, `AppContext.create_vision()` 工厂方法
- ✅ `AppContext.get()` 向后兼容 (MITM 模式)
- ✅ `start_vision()` / `stop_vision()` 生命周期
- ✅ 根据 platform 配置自动选择桌面/移动端执行器

### CLI & 配置

- ✅ `--vision` (默认), `--mitm` (兼容), `--steam`, `--listen-only`
- ✅ `config/__init__.py` 新增 7 个 vision 配置项
- ✅ Dashboard 保留 (端口 8083)

### 工具脚本

| 脚本 | 功能 | 状态 |
|------|------|------|
| `scripts/download_majsoul_tiles.py` | 下载 GitHub 雀魂素材 | ✅ |
| `scripts/generate_tile_templates.py` | 合成牌面模板 | ✅ |
| `scripts/capture_real_templates.py` | 从游戏截图采集模板 | ✅ |
| `scripts/smart_label_tiles.py` | 智能标注牌面 (颜色+位置) | ⚠️ 深色主题准确率低 |
| `scripts/test_vision_live.py` | 实机视觉测试 | ✅ |
| `scripts/auto_collect_templates.py` | 边玩边采集模板 | ✅ |

### 打包

- ✅ `build_exe.py` 更新至 v2.2
- ✅ `dist/MajsoulAutoMod_v2/` (265MB, 含 mitmproxy 等全部依赖)
- ✅ `Launch.bat` 一键启动

### 测试

| 套件 | 通过 | 说明 |
|------|------|------|
| `tests/test_shanten.py` | 12/12 | 向听数计算 |
| `tests/test_regression.py` | 15/15 | Bug 修复回归 |
| `tests/test_vision.py` | 25/25 | 视觉管线单元测试 |

### 杂项

- ✅ 清除 Steam 版雀魂的 BepInEx 残留 (旧 v1 MOD)
- ✅ 确认 ROI 坐标: 手牌 83-94%, x 8-92% (全屏百分比, 2560x1600)

---

## ❌ 未完成 / 待解决

### 牌种识别准确率 (核心瓶颈)

**当前状态**: 定位 100% 准确, 牌种识别率 ~38% (深色主题)

| 问题 | 原因 | 方向 |
|------|------|------|
| GitHub 浅色模板 vs 深色主题 | 游戏主题导致颜色/亮度差异 | 采集完整深色模板库 |
| CCORR_NORMED 置信度 0.96 但分类不准 | 所有模板得分接近, margin 太小 | 相对得分(margin) + 排除白板 |
| 仅有 11/34 深色模板 | 需要玩多局收集 | 运行 auto_collect_templates.py |
| 缺 ONNX 神经网络模型 | 网络限制, 无法下载 | 网络通后下载 ViT 模型 |

### 按钮检测

- ❌ 没有按钮模板图片 (`templates/pon.png` 等)
- ❌ 当前回退到坐标估算, 所有按钮始终返回可见
- 需运行 `capture_templates.py` 采集真实按钮截图

### 完整对局流程测试

- ❌ 未在真实对局中端到端测试 (采集→识别→AI→执行→验证)
- ❌ 牌河识别未验证 (ROI 坐标是估算的)
- ❌ 副露(吃碰杠)检测未测试
- ❌ 立直检测未测试

### 功能缺失

- [ ] 从 `resources.assets` 提取雀魂原生牌面素材 (Unity AssetBundle 解析)
- [x] DXcam 已安装 (`pip install dxcam`, 3ms/帧 可用)
- [ ] 按钮模板图片采集
- [ ] 移动端 (ADB) 视觉采集未测试
- [x] 分数 OCR 读取 (`vision/ocr.py`, PaddleOCR 集成完成)
- [x] WebSocket 断线重连 (`mitm/addons.py`, 指数退避 + 事件通知)
- [x] 多显示器支持 (`vision/capture.py`, monitor_index 选择 + 枚举)
- [x] 窗口模式自适应 (`vision/pipeline.py`, 自动查找游戏窗口 + ROI 适配)

### 打包优化

- [x] 剥离 mitmproxy 减小体积 (`build_exe.py --vision-only`, 265MB→约 150MB)
- [ ] 增量模板更新机制

---

## 🎯 下一步计划

### 短期 (立即可做)

1. **运行 `auto_collect_templates.py`** — 边玩边收齐 34 张深色模板
2. **采集按钮模板** — `capture_templates.py` 截 7 个按钮
3. **实机对局测试** — 打开雀魂, `python scripts/test_vision_live.py`

### 中期

4. **从游戏文件提取原生素材** — 解析 `resources.assets` 拿雀魂真牌面图
5. ~~**安装 DXcam**~~ ✅ 已完成 — `pip install dxcam` (3ms/帧)
6. **ONNX 模型** — 网络通时下载 ViT (99.67%), 彻底解决识别问题

### 长期

7. ~~**剥离 MITM**~~ ✅ 已完成 — `build_exe.py --vision-only` (~150MB)
8. **完整的闭环验证** — Plan→Execute→Verify 全链路对局测试
9. **自适应 ROI** — 自动检测窗口大小/主题, 无需手动校准 (已实现窗口查找, 待完善主题自适应)

### v2.2.1 新增 (2026-06-16)

| 项目 | 文件 | 说明 |
|------|------|------|
| DXcam 安装 | `requirements.txt` | `dxcam>=0.3.0` |
| 多显示器支持 | `vision/capture.py` | `CaptureConfig.monitor_index` + `DXCAMCapture.enumerate_outputs()` |
| 窗口自适应查找 | `vision/pipeline.py` | `find_game_window()` + `update_window_rect()` 连多显示器 |
| 分数 OCR | `vision/ocr.py` | `ScoreOCR` + `ScoreInfo`, 多数投票平滑 |
| WebSocket 重连 | `mitm/addons.py` | `WSReconnectTracker` 指数退避 + 状态快照 + EventBus 通知 |
| Vision-only 打包 | `build_exe.py` | `--vision-only` 参数, 跳过 mitmproxy (~265→150MB) |
| 事件扩展 | `core/events.py` | `WS_CONNECTED` / `WS_DISCONNECTED` / `WS_RECONNECTED` |
