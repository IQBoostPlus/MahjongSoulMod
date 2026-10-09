# MajsoulAutoMod v2.5 — 项目状态总结

> 最后更新: 2026-09-07 (实机牌面识别修复: 连通域定位 + 缩放归一化 + SIFT/CCOEFF 融合)
> 上一版: 2026-06-17 v2.4 (SIFT 特征匹配引擎)

---

## 🟢 v2.5 最新进展 (2026-09-07) — 实机牌面识别已打通

**结论: 实机手牌识别从 0/13-15 修复到 13/13 + 牌背正确拒识**
(基于实机截图 `debug_output/1.png` 走完整管线端到端验证; 标注图见
`debug_output/scale_probe/e2e_annotated.png`)。

### 真正的根因 — 推翻 2026-06-16 "模板渲染质量差/低对比度" 的判断

实机截图为 2557×1597 (并非 1080p), 手牌条带 std=69 对比度充足, 完整牌面
SIFT 关键点 58-221 个 (并非旧观测的 0-3)。识别全灭是管线三处缺陷叠加:

| 层 | 缺陷 | 后果 |
|----|------|------|
| 切分尺寸写死 | `recognize_hand_tiles` 固定裁 86×139, 真实牌 122×190 (≈模板×1.5) | 只切到牌面中心局部; 旧观测的"低 std / SIFT 0-3 点"是残缺 crop 的假象 |
| 定位峰偏左 | 自适应二值化垂直投影峰受牌面左半文字牵引, 系统性偏左约半张牌 | 裁剪窗口错位 |
| 始终反转 + 单引擎 | `invert_dark` 无条件 bitwise_not, 浅色主题下反而有害; SIFT 命中即返回 | 反转后匹配率仅 8%、白板霸榜; 单一引擎约 77% |

> 即: 模板本身正确 (用户已确认), 不需要重采 live 模板 / 模板降级 / ONNX。

### v2.5 改动 (`vision/tiles.py`, +251/−85; 旧版备份 `debug_output/tiles_v24.py.bak`)

1. **定位** — 新增 `_locate_hand_tiles`: Otsu + 连通域取每张牌精确外接框 (14/14 对齐), 原投影法降为回退
2. **缩放归一化** — `match_single` 把任意尺寸牌面 resize 到模板尺寸 80×129 (放大 INTER_AREA)
3. **自适应反转** — 仅牌面 mean<127 (真深色) 时反转, 浅色实机不再反转
4. **SIFT × CCOEFF 融合** — 两路一致即采纳; 分歧时万子信 SIFT、筒/索/字信 CCOEFF; SIFT 关键点<8 判牌背/空块拒识
5. **赤宝歧义修正** — 赤宝以 <0.02 微弱优势压过对应普通牌时取普通牌
6. **性能** — SIFT 由 37 次逐模板建 FLANN 索引改为 numpy 精确 L2 距离矩阵一次计算, 整手 14 张 2570ms→约 490ms

### 验证

- 端到端 `1.png`: **13/13 全对 + 牌背拒识** (改前 0/13-15)
- 回归: `tests/test_tile_recognition.py` + `tests/test_vision.py` **共 72 项全过** (套件耗时 45s→19s)
- 接口兼容: `pipeline.recognize_hand` / `recognize_river` / benchmark 脚本调用签名未变

### v2.5 仍遗留

- [ ] 目前仅 1 张实机样本, 需多局 / 多分辨率 / 多主题截图验证泛化 (跑 `tests/benchmark_tile_accuracy.py`)
- [ ] 整手约 0.5s, 应配合 differ 帧差只在手牌变化时识别, 不逐帧全量
- [ ] 摸牌区 / 牌河 / 副露 / 立直 ROI 尚未套用 v2.5 管线验证
- [x] ~~Live 模板重采 / 模板降级 / ONNX~~ — v2.5 证明非必需, 优先级下调

---

## 🔬 工程评估 (2026-06-16)

---

## 🔬 工程评估 (2026-06-16)

### 架构评价

项目架构设计 **专业且扎实**：
- 事件总线 (`EventBus`) 完全解耦各子系统，新增数据源无需改动下游
- 双数据源 (MITM / Vision) 共享 `GameTracker` 接口，设计优雅
- 带迟滞的帧差分 (`StatefulDiffer`, 2-3 帧确认) 有效过滤识别噪声
- Plan→Execute→Verify 闭环 + 3 次重试，动作执行可靠性有保障
- AI 引擎（向听/牌效/防守/副露/立直判断）逻辑完整

### 2026-06-16 实机测试结论 — 牌识别完全失败

经过一整天的算法修复和实机调试，结论如下：

**牌面识别在真实游戏中完全不可用 (0/13-15 tiles recognized)。**

#### 根因分析

| 问题 | 数据 |
|------|------|
| 模板自身区分度 | 不同模板间 CCORR 高达 **0.97-0.98**（1m vs 2m = 0.976） |
| 游戏画面质量 | crop std=21（低对比度），模板 std=58（高对比度） |
| 模板 vs 游戏匹配 | CCORR 仅 **0.70-0.84**，远低于模板间自相似度 |
| 白板干扰 | 11/16 峰值的最佳匹配是 tile 31（白板） |
| Top-2 margin | 绝大多数 < 0.005，无法可靠区分 |

**核心矛盾**：模板和游戏画面是**不同渲染源**产生的。模板的像素模式（均值~190, std~58）与游戏截图的像素模式（均值~130, std~21）没有对应关系。这不是"深色 vs 浅色"的问题——反转后 CCORR 也仅从 0.79 提升到 0.94，仍然低于模板间自相似度 0.97。

#### 已尝试并失败的方案

| 方案 | 结果 |
|------|------|
| 灰度反转 | CCORR 0.79→0.94，仍然不够 |
| TM_CCOEFF_NORMED | 更差，实测 0.156 vs CCORR 0.855 |
| 中心聚焦裁剪 | 消除了白板优势，但 margin 仅 0.001-0.011 |
| Scale 粒度细化 | 无效果，匹配分数瓶颈在像素分布，不在尺寸 |
| 降低 margin 阈值 | 到 0.005 仍然全灭，到 0.0 被白板拦截 |
| 关闭白板排除 | 得分 0.70-0.84，且 top-1 无明显优势 |

#### 可行的前进方向

1. **SIFT/ORB 特征匹配** — 匹配形状关键点，对颜色/亮度/渲染差异不敏感
2. **ONNX 神经网络分类器** — 训练或下载针对雀魂牌面的分类模型
3. **实时采集真实模板** — 从当前游戏直接截图做模板，边玩边建库
4. **放弃视觉管线** — 回退到 MITM 代理模式（需要 mitmproxy）

---

## 🎯 修复状态

### ✅ 已完成

- [x] 灰度反转（始终反转，模板浅色 / 游戏深色）
- [x] CCORR 匹配（实测优于 CCOEFF）
- [x] ROI 区域按用户标注精确校准（HAND/DORA/BTNS/牌河）
- [x] 裁剪尺寸匹配模板宽高比 (80:129)
- [x] 自适应 scale + 细化范围
- [x] margin 检查 + 赤宝牌降级
- [x] 99 项单元测试全部通过
- [x] **SIFT 特征匹配引擎** — 同主题 97%, 跨主题 97% (v2.4 + CLAHE)
- [x] **CLAHE 对比度增强** — 自适应直方图均衡化, 桥接模板-游戏质量差
- [x] **Live 模板基础设施** — `tiles_live/` 目录 + labels.json 格式
- [x] **v2.5 实机牌面识别修复** — 连通域定位 + 缩放归一化 + 自适应反转 + SIFT/CCOEFF 融合, 实机 13/13
- [x] **v2.5 SIFT numpy 加速** — 精确 L2 距离矩阵替代逐模板 FLANN, 整手 5× 提速

### ✅ 牌面识别 — v2.5 已解决 (2026-09-07, 单样本 13/13)

> 下方表格与"低对比度/SIFT 0-3 点"为 v2.4 历史判断, 其根因已被 v2.5 推翻
> (真因是切分尺寸写死 + 定位偏左 + 始终反转, 详见顶部 v2.5 总览)。


牌面识别从 **完全不可用 (0/13-15)** 提升到 **97% 理论准确率** (干净反转图像)。

**真实情况**: 模板来自游戏资产 (majsoul-generator 渲染, 80x129 RGBA),
已确认为真实模板。问题不在模板来源, 而在 **游戏内渲染质量远低于模板**:

| 属性 | 模板 | 游戏截图 crop |
|------|------|---------------|
| mean | ~190 | ~132 |
| std | ~58 | ~21 |
| SIFT kp | 50-162 | 0-3 |
| 渲染 | 生成器 (高质量) | 游戏引擎 (主题+抗锯齿) |

**v2.4 改进**:
- SIFT + Canny 边缘 + CLAHE → 97% (干净反转), 但实机仍受限于低对比度
- CLAHE 提升 crop std 21→29, 但仍远低于模板 std 58
- 游戏 crop 的 SIFT 关键点仅 0-3 个 (需要 ≥8), 无法可靠匹配

### 下一步

牌面识别的根本解决需要 **缩小模板与游戏截图的渲染质量差距** (v2.4 判断, 已被 v2.5 推翻 — 下列三项均非必需, 仅作备选):

1. **Live 模板采集** (推荐) — `auto_collect_templates.py` 在游戏中边玩边采
   集, 模板与截图有相同渲染质量 → 模板匹配重新变得可靠
2. **模板降级** — 对现有模板应用模糊+降对比度, 模拟游戏渲染
3. **ONNX 分类器** — 在低质量图像上训练, 绕过质量差距

### ✅ 已解除阻塞 (v2.5, 2026-09-07)

- [x] ~~实机低对比度 crop 无法匹配 (需 live 模板或 ONNX)~~ — 真因是切分尺寸写死 + 定位峰偏左 + 始终反转, 已修复, 无需 live 模板 / ONNX

---

## 📋 原有状态记录

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

### 牌种识别准确率 (v2.5 单样本已打通, 待多局泛化)

**v2.5 状态 (2026-09-07)**: 浅色主题实机截图 1.png 端到端 13/13 + 牌背拒识,
72 项单测全过。下列为 v2.4 及更早的历史问题与 v2.5 重新评估:

| 历史问题 | v2.5 评估 |
|------|------|
| ~~GitHub 浅色模板 vs 深色主题~~ | 自适应反转 + 双引擎融合已桥接; 深色主题仍需补样本验证 |
| ~~CCORR 置信度高但分类不准 / margin 太小 / 白板霸榜~~ | 归一化单尺度 CCOEFF + 白板排除 + SIFT 融合已解决 |
| ~~仅 11/34 深色模板, 需 live 采集~~ | 证明非必需 (模板正确); live 采集降级为可选增强 |
| ~~缺 ONNX 模型~~ | 非必需, 优先级下调 |
| 多局 / 多分辨率 / 多主题泛化 | **新遗留**: 目前仅 1 张实机样本, 需跑批量基准 |
| 整手约 0.5s 性能 | **新遗留**: 接入 differ 帧差, 仅手牌变化时识别 |

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

### 短期

**v2.5 优先 (2026-09-07 起):**
1. **多局泛化验证** — 存多份不同分辨率/主题的手牌截图, 跑 `tests/benchmark_tile_accuracy.py` 出批量准确率
2. **帧差触发识别** — 整手约 0.5s, 接入 differ 只在手牌变化时识别, 不逐帧全量
3. **摸牌区/牌河/副露/立直 ROI 验证** — 套用 v2.5 定位 + 融合管线并端到端测试
4. **实机完整对局** — `scripts/test_vision_live.py` 跑通 采集→识别→AI→执行→验证

**v2.4 历史项 (已完成):**

1. ✅ **SIFT 特征匹配引擎** — 同主题 97%, 跨主题 89% (P0 ✅)
2. ✅ **SIFT 测试套件** — 24 个新测试, 99 项全部通过
3. **采集按钮模板** — `capture_templates.py` 截 7 个按钮
4. **实机对局测试** — `python scripts/test_vision_live.py` 验证 SIFT
5. **收集深色 live 模板** — `auto_collect_templates.py` 收筒子/赤宝牌

### 中期

6. **从游戏文件提取原生素材** — 解析 `resources.assets` 拿雀魂真牌面图
7. **ONNX 模型** — 网络通时下载 ViT (99.67%), 彻底解决识别问题

### 长期

8. **完整的闭环验证** — Plan→Execute→Verify 全链路对局测试
9. **自适应 ROI** — 自动检测窗口大小/主题

### v2.4 新增 (2026-06-17)

| 项目 | 文件 | 说明 |
|------|------|------|
| SIFT 特征匹配 | `vision/tiles.py` | 主引擎: 形状关键点匹配, 亮度/对比度/主题不变 |
| 边缘 SIFT 降级 | `vision/tiles.py` | Canny 边缘图 SIFT, 跨主题 89% 准确率 |
| ORB 轻量降级 | `vision/tiles.py` | CPU 友好, 实时帧率备用 |
| SIFT 测试套件 | `tests/test_tile_recognition.py` | 24 个 SIFT 测试: 初始化/自匹配/深色/集成/ORB |

**SIFT 匹配流程:**
1. 原始图像 SIFT → 同主题匹配 (浅→浅 或 深→深)
2. Canny 边缘 SIFT → 跨主题匹配 (浅↔深, 边缘反转不变)
3. ORB 降级 → CPU 友好备用
4. 模板匹配 → 最终兜底 (CCORR + 灰度反转 + 多尺度)

### v2.5 更新 (2026-09-07)

| 项目 | 文件 | 说明 |
|------|------|------|
| 连通域牌定位 | `vision/tiles.py` | `_locate_hand_tiles`: Otsu+连通域精确外接框, 投影法回退 |
| 缩放归一化 | `vision/tiles.py` | `match_single` 统一 resize 到 80×129, 消除分辨率差异 |
| 自适应反转 | `vision/tiles.py` | 仅 mean<127 深色才反转, 修正浅色主题误反转 |
| SIFT×CCOEFF 融合 | `vision/tiles.py` | 一致采纳; 万子信 SIFT / 筒索字信 CCOEFF; kp<8 拒识牌背 |
| 赤宝歧义修正 | `vision/tiles.py` | 赤宝以 <0.02 微弱优势压普通牌时取普通牌 |
| SIFT numpy 加速 | `vision/tiles.py` | 精确 L2 距离矩阵替代逐模板 FLANN, 整手 2.57s→0.49s |

**v2.5 匹配流程 (`match_single`):**
1. CLAHE → resize 归一化到 80×129
2. 自适应反转 (仅深色 mean<127)
3. 通道 A: SIFT (numpy L2; 原始 + Canny 两阶段) / ORB 降级 — 只出候选不立即返回
4. 通道 B: 归一化单尺度 CCOEFF (排除白板 31)
5. 融合决策: 两路一致采纳 / 万子信 SIFT / 筒索字信 CCOEFF / SIFT kp<8 判牌背拒识
6. 白板排除 + 赤宝高置信判定
7. 两路全失败 → v2.3 多尺度 CCORR 兜底
