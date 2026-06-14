"""
雀魂自动麻将 - 配置中心
"""

import json
import os
from pathlib import Path


class Config:
    """全局配置"""

    def __init__(self, path: str = None):
        if path is None:
            path = os.path.join(Path(__file__).parent, "config", "settings.json")
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        defaults = {
            # ── MITM 代理配置 ──
            "proxy_port": 8080,
            "proxy_host": "127.0.0.1",
            "mitm_web_port": 8081,

            # ── 游戏窗口 ──
            "browser_type": "chrome",  # chrome / edge / steam
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
