"""
日志工具
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path


class Logger:
    """统一日志系统"""

    _instance = None
    _logger = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup()
        return cls._instance

    def _setup(self):
        self._logger = logging.getLogger("MajsoulAutoMod")
        self._logger.setLevel(logging.DEBUG)

        # 控制台 handler
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)-7s %(message)s',
            datefmt='%H:%M:%S'
        ))
        self._logger.addHandler(console)

        # 文件 handler
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

    @classmethod
    def info(cls, msg): cls.__new__(cls)._logger.info(msg)
    @classmethod
    def debug(cls, msg): cls.__new__(cls)._logger.debug(msg)
    @classmethod
    def warning(cls, msg): cls.__new__(cls)._logger.warning(msg)
    @classmethod
    def error(cls, msg): cls.__new__(cls)._logger.error(msg)
    @classmethod
    def critical(cls, msg): cls.__new__(cls)._logger.critical(msg)
