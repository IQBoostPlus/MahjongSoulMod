# 雀魂自动麻将 MOD (MahjongSoul AutoMod)

> **声明**: 此项目仅供学习研究用途。在雀魂正式账号上使用第三方辅助程序可能导致封号，请自行承担风险。

## 架构

7层分层架构：

| 层 | 名称 | 职责 |
|----|------|------|
| L0 | MOD 框架层 | BepInEx IL2CPP 加载器 + Harmony 补丁 |
| L1A | 数据读取层 | Unity 对象遍历，获取牌局原始数据 |
| L1B | 动作执行层 | 执行打牌/鸣牌/立直等游戏动作 |
| L2 | 牌局状态重建层 | 将原始数据转换为结构化麻将逻辑状态 |
| L3 | AI 决策引擎 | 牌效率分析、防守分析、鸣牌/立直/和牌决策 |
| L4 | 策略控制器 | 根据局况调整攻击性、速度偏好、风险容忍度 |
| L5 | 安全与反检测层 | 人机化、随机延迟、KillSwitch |
| L6 | UI 配置层 | 配置面板、状态显示 |

## 项目结构

```
MahjongSoulMod/
├── src/
│   ├── MainPlugin.cs              # BepInEx 入口
│   ├── MyPluginInfo.cs            # 插件元数据
│   ├── Config.cs                  # 配置绑定
│   ├── MainLoop.cs                # 主循环
│   ├── DataLayer/                 # Layer 1: 数据层
│   ├── StateReconstruction/       # Layer 2: 状态重建
│   ├── AI/                        # Layer 3: AI 引擎
│   ├── Strategy/                  # Layer 4: 策略
│   ├── Safety/                    # Layer 5: 安全
│   ├── UI/                        # Layer 6: UI
│   └── Utils/                     # 工具
├── Libs/                          # 外部依赖
├── struct.md                      # 架构设计文档
└── README.md
```

## 开发环境

- .NET 6.0 SDK
- BepInEx 6 (IL2CPP)
- Harmony 2.x
- Il2CppInterop

## 构建 & 部署

```bash
dotnet build -c Release
```

将生成的 `MahjongSoulMod.dll` 复制到：
```
<雀魂游戏目录>/BepInEx/plugins/
```

## 开发路线

1. **Phase 1**: BepInEx 环境搭建 + MOD 注入验证
2. **Phase 2**: Unity 对象遍历定位数据 + 动作执行打通
3. **Phase 3**: AI 决策引擎实现
4. **Phase 4**: 人机化 + 安全机制
5. **Phase 5**: UI 配置界面
