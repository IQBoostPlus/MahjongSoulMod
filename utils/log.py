"""
统一日志系统

单例模式 — 确保全局只有一个 logger 实例。
用法:
    from utils.log import Logger
    Logger.info("message")
    Logger.error("something failed")
"""

import logging
import os
import sys
import io
from datetime import datetime
from pathlib import Path


def _ensure_utf8_stdout():
    """确保 stdout 使用 UTF-8 编码 (修复 Windows GBK 乱码)"""
    if sys.platform != "win32":
        return

    # 设置控制台代码页
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


class _SafeFormatter(logging.Formatter):
    """安全的 Formatter: 当控制台不支持 UTF-8 时，用 ASCII 替代"""

    def __init__(self, fmt, datefmt):
        super().__init__(fmt, datefmt)
        self._has_warned = False

    def format(self, record):
        s = super().format(record)
        try:
            # 测试是否能编码
            s.encode(sys.stdout.encoding or "utf-8")
            return s
        except UnicodeEncodeError:
            # fallback: ASCII + replace
            return s.encode("ascii", errors="replace").decode("ascii")


class _LoggerImpl:
    """Logger 的内部实现 — 真正的单例"""

    def __init__(self):
        self._logger = None
        self._setup_done = False

    def _ensure_setup(self):
        if self._setup_done:
            return
        self._setup_done = True

        # 必须在创建 handler 之前修复编码
        _ensure_utf8_stdout()

        self._logger = logging.getLogger("MajsoulAutoMod")
        self._logger.setLevel(logging.DEBUG)

        # 控制台 handler (INFO 级别, 安全编码)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(_SafeFormatter(
            '[%(asctime)s] %(levelname)-7s %(message)s',
            datefmt='%H:%M:%S'
        ))
        self._logger.addHandler(console)

        # 文件 handler (DEBUG 级别, 始终 UTF-8)
        log_dir = os.path.join(str(Path.home()), ".majsoul_automod", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(
            log_dir,
            f"majsoul_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)-7s %(name)s - %(message)s'
        ))
        self._logger.addHandler(fh)

        self._logger.info(f"Log file: {log_file}")

    def info(self, msg):
        self._ensure_setup()
        self._logger.info(msg)

    def debug(self, msg):
        self._ensure_setup()
        self._logger.debug(msg)

    def warning(self, msg):
        self._ensure_setup()
        self._logger.warning(msg)

    def error(self, msg):
        self._ensure_setup()
        self._logger.error(msg)

    def critical(self, msg):
        self._ensure_setup()
        self._logger.critical(msg)


# 模块级单例 — 所有 import 共享一个实例
_impl = _LoggerImpl()


class Logger:
    """统一日志接口 — 委托给模块级单例 _impl"""

    @staticmethod
    def info(msg):    _impl.info(msg)
    @staticmethod
    def debug(msg):   _impl.debug(msg)
    @staticmethod
    def warning(msg): _impl.warning(msg)
    @staticmethod
    def error(msg):   _impl.error(msg)
    @staticmethod
    def critical(msg): _impl.critical(msg)
