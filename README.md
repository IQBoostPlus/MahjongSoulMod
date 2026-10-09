# 雀魂自动打牌 MOD (MajsoulAutoMod)

> 项目原声明：仅供学习和研究用途；使用第三方辅助程序可能违反雀魂用户协议并导致封号。

**当前阶段：v2.5 模块集成原型，手牌识别完成单场景验证，完整真实对局闭环尚未验收。**

文档核查日期：2026-10-08；2026-10-09 增补猫咪皮肤范围决定与手牌筛选复核结果。功能“已实现”不等于“已实机验证”，测试通过不等于能够稳定自动完成整场对局。

- [当前进度与证据](TODO.MD)
- [执行计划与验收标准](EXECUTION_PLAN.html)
- [历史记录说明](docs/history/README.md)

## 简介与可行性

本项目使用屏幕识别或 MITM 代理作为数据源，经状态重建和启发式麻将决策后模拟鼠标操作。当前默认入口为 **Vision 视觉模式**；MITM 为兼容入口，当前客户端协议兼容性待真实抓包验证。

模块分层与现有局部验证支持继续研发，但按钮误报、动作验证、麻将规则处理、状态完整性和多局泛化仍阻塞稳定自动对局。尚无独立牌力评估、连续整场对局成功率或“反检测”验证，不宣称无人值守可用。

## 架构

```text
屏幕截图 → ROI / 牌面 / 按钮识别 → VisionFrame → 帧差分 / 事件桥接 ┐
                                                                 ├→ GameTracker
WebSocket → mitmproxy → LiqiDecoder（协议兼容性待验证）              ┘
        → EventBus → AIDecisionMaker → 动作执行 → 结果验证
```

视觉管线目前识别手牌、摸牌区、牌河、宝牌和按钮，并传递真实牌面边界与按钮位置。副露、局况、立直棒和结果画面字段尚未在 `process_frame()` 中填充；OCR 模块尚未接入该状态链路。动作执行现在点击一次后轮询结果，缺帧、未确认结果或异常会停止自动模式，不重复盲点。

### 主要文件

```text
main.py                 CLI、启动与快捷键
core/                   事件总线、组件组装与决策触发
vision/                 采集、ROI、识别、差分、事件桥接与动作验证
ai/                     向听数计算、牌效率与防守等启发式策略
game_state/             对局状态追踪
proto/、mitm/           协议解码与代理插件
action/                 桌面、Airtest 与 ADB 执行器
config/                 配置与 settings.json
dashboard/              对局仪表盘
scripts/                采集、标注、识别诊断与批量验证工具
tests/                  单元测试、模拟流程测试与合成基准
```

## 安装与运行

桌面视觉路线主要面向 Windows，其他平台及 ADB 路线待验证。依赖没有锁定版本；`requirements.txt` 当前同时包含 mitmproxy、Airtest、DXcam 和 PaddleOCR/PaddlePaddle，安装环境与干净机器运行仍需验收。

```powershell
python -m pip install -r requirements.txt
```

### 先检查视觉识别

打开游戏窗口后运行以下诊断脚本。脚本检查窗口、截图和各 ROI 的识别结果，不代表 AI 自动操作闭环测试。

```powershell
python scripts/test_vision_live.py
```

### 视觉自动模式（实验入口）

```powershell
python main.py --vision
# python main.py 与上述命令采用相同的默认视觉模式
```

此入口无需代理配置，当前默认启用自动模式，可能模拟鼠标操作；仅用于受监督的研发验证。`--steam` 用于覆盖客户端启动配置，移动端视觉路线尚未验收。

- **F8**：切换自动模式。
- **F9**：紧急停止。

以上按键目前在 `main.py` 中固定绑定，修改配置中的按键字段不会改变实际绑定。

### MITM 监听模式（协议待验证）

```powershell
python main.py --mitm --listen-only
```

代理默认地址为 `127.0.0.1:8080`，可由配置覆盖。此模式需要客户端连接代理并信任 mitmproxy CA；首次证书安装入口为 [mitm.it](http://mitm.it)。浏览器与 Steam 的代理方式不同，连接成功仍需确认消息能够正确解码。

视觉监听入口已修正上下文创建，可使用 `python main.py --vision --listen-only`。完整窗口与时序行为仍待实机验收；单帧视觉检查也可使用上面的诊断脚本。

### 配置、仪表盘与日志

源码配置为 `config/settings.json`；打包程序使用 exe 同目录的 `settings.json`。当前仓库配置的 Dashboard 端口是 **8083**，配置类缺省值是 8082，以实际配置和启动日志为准。日志写入用户目录 `.majsoul_automod/logs/`，受限环境可能禁止该写入。

## 已有验证与边界

2026-10-08 验证工具加入后复核：27 项向听数/回归测试、25 项视觉测试、47 项牌识别测试、46 项闭环回归、17 项数据集/评测回归，合计 **162 项通过**。测试进程关闭文件日志以绕过用户目录写权限限制；闭环测试使用注入点击和标注状态，不操作真实桌面。部分旧测试只检查初始化或返回类型，不保证完整业务正确性；本次未验收真实对局或构建。

常规测试入口（需要相应依赖和日志写权限）：

```powershell
python -m unittest discover -s tests -p '*unittest.py' -v
python -m unittest discover -s tests -p 'test_vision.py' -v
python -m unittest discover -s tests -p 'test_tile_recognition.py' -v
python -m unittest discover -s tests -p 'test_closed_loop.py' -v
python -m unittest discover -s tests -p 'test_real_dataset.py' -v
```

已有本地报告 `debug_output/batch_validation/REPORT.md`（2026-09-08）记录：

- A：一张实机截图，13 张有效牌识别正确，加 1 个牌背正确拒识，合计 14/14；手牌识别耗时记录为 258ms。
- B：同一截图裁出的 14 个区域经 13 类扰动，182/182。
- C：37 张模板经 3 类变换，111/111。

合计 307/307 是历史脚本口径的成功数，**不是 307 张独立真实截图，也不是完整牌种实机准确率**。当时 C 层将白板拒识计为正确，反转赤牌允许回落普通牌；当前已增加白板匹配和赤牌计数归一化，仍需实机验证，历史基准的白板期望也需更新。258ms 仅为已有报告中的手牌耗时，不能代表全管线延迟或当前机器性能。

```powershell
python scripts/batch_validate.py
```

该脚本依赖本地 `debug_output/1.png`，会更新验证输出。`debug_output/` 被 Git 忽略，干净克隆未必有截图和报告，复现前需准备该样本及核对脚本中的人工标注。

`tests/benchmark_tile_accuracy.py` 使用模板反转和噪声合成样本，不是多局实机基准；`tests/test_e2e.py` 与 `tests/test_pipeline.py` 为模拟流程，不能当作完整真实对局验收。

### 独立实机验证工具

[验证集说明](datasets/real_game/README.md) 包含采集、导入、按对局隔离、人工标注和评测命令。现有 6 张旧图全部登记为 development 且均已完成标注（其中 5 张为 2026-10-09 助手逐牌目视复核，含 3 处 ROI 修正）；**独立 test 样本目前为 0**，不能宣称 T4 验收完成，助手标注仍建议由用户抽检。

```powershell
python scripts/validate_real_dataset.py --check
python scripts/validate_real_dataset.py --split development --no-file-log
```

2026-10-09 开发评测（全部 6 张均标注后）：默认牌面 5 帧 60 张牌命中 55 张（91.7%）、整手全对 1/5、拒识 0，剩余错误为赤五降级 3 处（阈值行为）与低分辨率小尺寸牌误识 2 处；猫咪牌面样本 1/13 牌正确、整手不正确，无操作按钮区域未误报。以上均为 development 结果，不能作为泛化评估或验收依据。已决定（2026-10-09）：不再进行猫咪皮肤适配，验收范围限定默认牌面，该样本仅作为已知缺口记录，不阻塞主线。结果与代码/模板哈希记录在 [开发基线](datasets/real_game/development-baseline.json)（2026-10-09 刷新为 6 张全部标注后的评测）。新对局截图从 pending 开始，经人工复核后才能进入评测；脚本禁止字节重复、同局跨集合及已调参样本进入 test。

## 闭环修复与剩余限制

- 已移除按钮坐标误报回退；点击使用识别边界，缺牌、缺边界或低置信度时不出牌。实际按钮误报率仍待独立实机基准验证。
- 已修正出牌验证：目标牌从手中移除且出现在自家牌河才成功；缺帧、无窗口、未确认或异常均停止自动模式，不重复点击。
- 已修正立直/和牌分支、立直后摸切、赤牌归一化、副露后摸牌及吃碰后的出牌触发；和牌机会须由已确认操作触发。未确认的完整牌型不会被当作合法和牌。
- 已增加白板专门匹配和牌背拒识，模板与单元验证通过，真实白板/赤牌泛化仍待验收。
- 副露、局况、立直与和牌机会尚未形成完整状态和合法动作链路。
- 副露、立直棒及结果画面未接入实时识别，相关操作即使点击也可能无法确认结果并暂停；多候选吃碰杠尚未完成，不能据此宣称整场自动对局可用。
- 单张手牌已验证，多局、多分辨率、多主题、牌河及实际点击成功率尚未验收。
- MITM 的封包、消息名和字段假设需要真实样本确认，网络代理不构成反检测保证。

## 下一步

按 [执行计划](EXECUTION_PLAN.html) 推进：P0 已有代码修正与回归证据，继续建立独立实机数据集、补全状态与合法动作、验收受监督连续对局，最后优化性能与打包。ONNX、素材提取和移动端扩展为后置备选；P0 的实机验收仍未完成。

## 打包

```powershell
python -m pip install pyinstaller
python build_exe.py                 # 完整构建
python build_exe.py --vision-only   # 视觉构建
```

脚本定义的目标目录分别为 `dist/MajsoulAutoMod/` 和 `dist/MajsoulAutoMod_Vision/`。本次未执行构建；已有 dist 目录不代表当前版本通过交付验收。PIL 既被列为隐藏导入又被排除等打包配置需核查，并在干净机器验证截图、模板加载和启动。

## License

项目原声明为 AGPL-3.0。
