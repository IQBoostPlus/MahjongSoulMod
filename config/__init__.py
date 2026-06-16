"""
雀魂自动麻将 - 配置中心
"""

import json
import os
import sys
from pathlib import Path


def _get_default_config_path() -> str:
    """获取配置文件路径 — 兼容开发模式和 PyInstaller 打包"""
    # 优先: exe 同级目录的 settings.json (用户可编辑)
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        external = os.path.join(exe_dir, "settings.json")
        if os.path.isfile(external):
            return external
        # 不存在则创建在 exe 同级目录
        return external

    # 开发模式: config/settings.json
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


class Config:
    """全局配置"""

    def __init__(self, path: str = None):
        if path is None:
            path = _get_default_config_path()
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        defaults = {
            # ── MITM 代理配置 ──
            "proxy_port": 8080,
            "proxy_host": "127.0.0.1",
            "mitm_web_port": 8081,
            "dashboard_port": 8082,   # 仪表盘 Web UI 端口

            # ── 平台模式 ──
            "platform": "desktop",  # "desktop" / "mobile"
            "adb_device_id": None,  # ADB 设备ID (None=自动选择)

            # ── 游戏窗口 (桌面端) ──
            "auto_launch_browser": True,  # 启动时自动打开雀魂网页
            "game_url": "https://game.mahjongsoul.com",
            "browser_type": "chrome",  # chrome / edge / steam
            "steam_uri": "steam://rungameid/2739990",  # 雀魂 Steam App ID
            "steam_app_id": "2739990",
            "window_title": "雀魂",

            # ── AI 策略 ──
            "aggression": 3,         # 攻击性 1-5
            "speed": 3,              # 速度偏好 1-5
            "risk_tolerance": 3,      # 风险容忍度 1-5
            "auto_discard": True,
            "auto_call": True,
            "auto_riichi": True,
            "auto_agari": True,

            # ── 人机化 ──
            "min_delay_ms": 300,
            "max_delay_ms": 1500,
            "safety_mode": True,     # 安全模式 (更拟人化)
            "error_rate": 0.02,      # 等优选项时犯错概率

            # ── Vision Pipeline (视觉识别) ──
            "vision_mode": True,
            "vision_capture_backend": "auto",  # "auto" | "dxcam" | "pil" | "adb"
            "vision_target_fps": 10,
            "vision_tile_threshold": 0.80,     # 模板匹配置信度阈值
            "vision_verify_actions": True,     # 启用 Plan→Execute→Verify 闭环
            "vision_max_retries": 3,           # 动作重试次数
            "vision_debug_overlay": False,     # 显示识别叠加窗口 (调试)

            # ── 快捷键 ──
            "toggle_key": "F6",
            "kill_switch_key": "F7",

            # ── 日志 ──
            "log_level": "INFO",     # DEBUG / INFO / WARNING / ERROR
            "log_to_file": True,
            "log_file": None,        # None = 自动生成路径
        }

        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    defaults.update(loaded)
            except Exception:
                pass

        # 确保配置目录存在
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(defaults, f, ensure_ascii=False, indent=2)

        return defaults

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key: str):
        return self._data[key]

    def __setitem__(self, key: str, value):
        self._data[key] = value
        self._save()

    def _save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)


# 全局单例
cfg = Config()
