"""运行时路径管理：兼容源码、开发版 EXE 和 Portable 发行版。"""

from __future__ import annotations

import os
from pathlib import Path
import sys


def resolve_app_dir(
    frozen: bool | None = None,
    *,
    executable: Path | None = None,
    source_file: Path | None = None,
) -> Path:
    """返回应用根目录，不依赖当前工作目录。"""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return (executable or Path(sys.executable)).resolve().parent
    source = source_file or Path(__file__)
    return source.resolve().parent.parent


def app_dir() -> Path:
    """当前运行实例的应用根目录。"""
    return resolve_app_dir()


def config_path() -> Path:
    return app_dir() / "config" / "config.yaml"


def user_data_dir() -> Path:
    path = app_dir() / "user_data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_runtime_env(
    root: Path | None = None, base: dict[str, str] | None = None
) -> dict[str, str]:
    """构造运行环境，将 NotebookLM 登录态隔离到应用目录。"""
    root = root or app_dir()
    data_dir = root / "user_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    env = dict(base if base is not None else os.environ)
    env["NOTEBOOKLM_HOME"] = str(data_dir)
    env["COURSELM_APP_DIR"] = str(root)
    return env
