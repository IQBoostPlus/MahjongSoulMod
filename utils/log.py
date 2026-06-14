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
from datetime import datetime
from pathlib import Path


class _LoggerImpl:
    """Logger 的内部实现 — 真正的单例"""

    def __init__(self):
        self._logger = None
        self._setup_done = False

    def _ensure_setup(self):
        if self._setup_done:
            return
        self._setup_done = True

        self._logger = logging.getLogger("MajsoulAutoMod")
        self._logger.setLevel(logging.DEBUG)

        # 控制台 handler (INFO 级别)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)-7s %(message)s',
            datefmt='%H:%M:%S'
        ))
        self._logger.addHandler(console)

        # 文件 handler (DEBUG 级别)
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
