# 雀魂自动麻将 MOD 部署脚本
# 使用: powershell -File deploy.ps1

$GameDir = "D:\Steam\steamapps\common\MahjongSoul"
$PluginDir = "$GameDir\BepInEx\plugins"
$ModDll = ".\bin\Release\net6.0\MahjongSoulMod.dll"

# 检查目录
if (-not (Test-Path $GameDir)) {
    Write-Error "游戏目录不存在: $GameDir"
    exit 1
}

# 检查 BepInEx
if (-not (Test-Path "$GameDir\BepInEx")) {
    Write-Error "BepInEx 未安装! 请先解压 BepInEx-Unity.IL2CPP-win-x64-6.0.0-pre.2.zip 到游戏目录"
    exit 1
}

# 检查 MOD
if (-not (Test-Path $ModDll)) {
    Write-Warning "MOD DLL 不存在，尝试编译..."
    dotnet build -c Release
}

# 创建插件目录
if (-not (Test-Path $PluginDir)) {
    New-Item -ItemType Directory -Path $PluginDir -Force | Out-Null
}

# 复制 DLL
Copy-Item $ModDll $PluginDir -Force
Write-Host "MOD 已部署到: $PluginDir"

# 验证
$deployed = Get-ChildItem "$PluginDir\MahjongSoulMod.dll"
if ($deployed) {
    Write-Host "部署成功! ($($deployed.Length) bytes)"
    Write-Host ""
    Write-Host "启动游戏后 MOD 会自动加载。"
    Write-Host "配置在: $GameDir\BepInEx\config\com.mahjongsoul.automod.cfg"
} else {
    Write-Error "部署失败"
}
