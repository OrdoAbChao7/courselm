"""日志初始化：控制台 INFO + logs/ 按日滚动 DEBUG。

Windows 控制台默认 GBK，文件 Sink 必须显式 UTF-8，否则中文日志乱码。
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(logs_dir: Path, verbose: bool = False) -> None:
    """初始化全局日志。重复调用安全（先移除旧 sink）。"""
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO", enqueue=False)
    logger.add(
        logs_dir / "courselm_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",       # 每日零点滚动
        retention="14 days",
        encoding="utf-8",
        enqueue=True,           # 多协程写文件安全
    )
