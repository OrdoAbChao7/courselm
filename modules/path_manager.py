"""项目路径与 NotebookLM 登录态管理。"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_app_dir(*, source_file: Path | None = None) -> Path:
    """返回应用根目录，不依赖当前工作目录。"""
    source = source_file or Path(__file__)
    return source.resolve().parent.parent


def app_dir() -> Path:
    """当前运行实例的应用根目录。"""
    return resolve_app_dir()


def config_path() -> Path:
    return app_dir() / "config" / "config.yaml"


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
