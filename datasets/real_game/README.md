# 实机截图验证集

此目录用于独立截图与标注基准，不模拟点击或自动操作。入口为 `scripts/collect_real_dataset.py` 与 `scripts/validate_real_dataset.py`。

## 当前数据

2026-10-08 登记 6 张已有游戏截图：1 张本地历史截图和 5 张来源 URL 未记录的网络截图。它们已被旧识别调试使用，全部属于 **development**；其中 1 张由评审助手目视标注，5 张待复核。历史截图有 ROI 框等叠加，不能视为原始新采集样本。

当前 **test 独立验收样本为 0**，不能发布泛化准确率或声称 T4 验收完成。6 张旧图保守归入同一 `legacy-unknown-session-group`，该分组不表示它们确实来自同一局；它只阻止未知来源样本被拆分为独立训练/验证数据。

`images/` 保存逐字节复制的原图，`manifest.json` 记录来源、SHA256、尺寸、集合、标注和复核人。标注来自目视检查，不使用识别输出作为真值；助手标注仍建议由用户复核。当前代码不会联网下载、生成合成数据、修改模板或自动修正模型错误。

## 收集与隔离

同一场完整对局使用同一个 `session_id`，连续帧、同局裁图和衍生图不能跨 development/test。已经用于调整算法、ROI、阈值或模板的样本一律 `used_for_tuning: true`，不得改成 test。未知来源的网络图片只能作为 development。

先将新的、本地未用于调参的截图按对局收集并导入。以下参数中的对局编号、来源描述必须换成真实记录：

```powershell
python scripts/collect_real_dataset.py --image D:\captures\game-001.png --session-id actual-game-001 --split test --provenance "Local capture; actual date, client, theme and window mode"
```

也可捕获一个明确指定的游戏窗口，要求窗口标题完全一致、可见且处于前台。脚本只截图，不点击、不启动游戏；未变化的重复截图会跳过。窗口失去焦点会停止，避免把其他前台应用误作游戏样本。

```powershell
python scripts/collect_real_dataset.py --capture-window "雀魂麻将" --session-id actual-game-002 --split test --provenance "Local new game; actual capture conditions" --count 10 --interval 2
```

每次导入默认状态为 `pending`，不会参与评测。建议至少准备多个独立对局，覆盖窗口/全屏、不同分辨率、白板、赤牌、重复牌、摸牌、吃碰杠与按钮出现/消失；牌面主题按 2026-10-09 决定限定默认牌面，不再进行猫咪皮肤适配。当前未设置未经用户确认的通过率或局数门槛。

## 人工标注

逐张查看原图，在 `manifest.json` 编辑以下字段：

- `hand.roi`：原图归一化边界 `[left, top, right, bottom]`，从 0 到 1。默认 ROI 仅为待复核初值，不能自动当作正确位置。
- `hand.tiles`：ROI 中所有牌从左到右，0–33 为普通牌，34/35/36 为赤五万/筒/索。**白板必须标 31**；明确的牌背或应拒识块标 -1，不把识别失败当作牌背。无法确认则保留 null 和 pending。
- `buttons.roi` 与 `buttons.visible`：操作按钮区域及其中实际可见的 `pon/chi/kan/riichi/ron/tsumo/pass`。空数组 `[]` 是已复核的负样本，null 是未标注。切勿漏标实际按钮。
- `theme`：实际牌面主题；`reviewer`：真实复核人和日期；完成至少一个区域标注后将 `status` 改为 `reviewed`。
- 一个 reviewed 样本可以只有手牌或按钮区域被标注；未标注的区域不进入对应指标。

标注只定位测试区域，不代表程序自动 ROI 校准通过；目前评测范围是手牌/按钮，牌河、副露、局况、完整对局时序和动作成功率仍是后续独立项目。

## 校验与评测

```powershell
# 完整性检查：标注结构、文件存在、SHA256、字节重复、来源和集合隔离
python scripts/validate_real_dataset.py --check

# 已知开发样本：只能用于发现错误，不能作为验收结果
python scripts/validate_real_dataset.py --split development --no-file-log

# 正式独立样本：仅复核过且未参与调参的本地截图
python scripts/validate_real_dataset.py --split test --no-file-log
```

未复核样本被跳过；选定集合没有可用标注则非零退出，不输出假成功。缺图、内容变化、同图重复、同局跨集合、非法 ROI/牌码、未注明来源/复核人会报错。`--check` 不解码图片；实际评测会核对图像解码和真实尺寸。

输出在 `debug_output/real_validation/results.json` 与 `REPORT.md`，包括逐帧预测/置信度、牌类计数、分辨率和主题分组。输出是当前开发评测证据，`acceptance_passed` 保持 null，成功生成报告不代表验收通过。

指标口径：

- 牌种准确率：已标注有效牌的精确身份命中率，白板拒识、赤牌降级均为错误。
- 整手正确率：数量、顺序和牌种全部一致才成功。
- 序列正确率：基于编辑距离，漏检和多检均扣分，避免 zip 截断造成虚高。
- 拒识率：有效牌未检出或返回 -1 的比例；额外检出单独计数。
- 按钮误报率：七类按钮的 `FP/(FP+TN)`；另报告无按钮画面的整帧误报率、召回率。没有对应样本时指标为 null。
- 延迟 p50/p95：模型初始化后的已标注手牌/按钮 ROI 识别耗时，不包含截图、全管线或鼠标操作。

## 可移交与复现

交付验证集时需要同时提供 manifest 和其引用的 images。原图已复制到本目录，当前无需依赖被忽略的 debug_output；新增数据也按此方式保存。脚本不会自动提交或上传数据。

新 test 集一旦被用于修改模型/阈值/ROI，就应改为 development，并另收新的独立对局。不要仅通过改 session_id 或 split 让旧样本变成“独立”数据。
