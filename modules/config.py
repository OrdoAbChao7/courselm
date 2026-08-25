"""配置加载层：读取并校验 config/config.yaml。

- 所有 pydantic 校验失败 / YAML 语法错误 / 文件缺失统一抛 ConfigurationError，
  消息面向使用者可读（直接打印给 CLI 用户）。
- 相对路径一律相对于项目根目录（config.yaml 的上上级目录）解析，
  与运行时工作目录无关。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator


class ConfigurationError(Exception):
    """配置文件缺失、语法错误或校验失败。"""


class PathConfig(BaseModel):
    courses_dir: Path
    output_dir: Path
    logs_dir: Path


class ObsidianConfig(BaseModel):
    """vault_path 允许为空（scan/login 不需要），generate 阶段强制校验。"""

    vault_path: str = ""
    course_folder: str = "课程"

    @property
    def vault_root(self) -> Path:
        return Path(self.vault_path)


class NotebookLMConfig(BaseModel):
    upload_wait_timeout: int = Field(gt=0)
    source_limit_warn: int = Field(gt=0)
    browser: str = Field(default="chromium", pattern="^(chromium|chrome|msedge)$")


class NetworkConfig(BaseModel):
    """proxy: auto（读系统代理）/ none / 显式地址（如 http://127.0.0.1:7897）。"""

    proxy: str = "auto"


class PromptRunnerConfig(BaseModel):
    retry: int = Field(ge=0)
    max_question_types: int = Field(gt=0)


class MarkdownConfig(BaseModel):
    tags: list[str] = Field(min_length=1)


class AppConfig(BaseModel):
    paths: PathConfig
    obsidian: ObsidianConfig
    notebooklm: NotebookLMConfig
    network: NetworkConfig = NetworkConfig()
    prompt_runner: PromptRunnerConfig
    markdown: MarkdownConfig
    file_types: list[str]

    @field_validator("file_types")
    @classmethod
    def validate_file_types(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("file_types 不能为空")
        for ext in v:
            if not ext.startswith(".") or ext != ext.lower() or len(ext) < 2:
                raise ValueError(f"扩展名格式应为小写 '.ext'，得到：{ext!r}")
        return v

    def require_vault(self) -> Path:
        """generate 等需要写入 Vault 的场景调用：确保 vault_path 已配置。"""
        if not self.obsidian.vault_path.strip():
            raise ConfigurationError(
                "config.yaml 中 obsidian.vault_path 未配置，无法写入 Obsidian Vault"
            )
        return self.obsidian.vault_root


def load_config(config_path: Path | None = None) -> AppConfig:
    """加载并校验 config.yaml；config_path 缺省为项目根下 config/config.yaml。"""
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
    config_path = Path(config_path)

    if not config_path.is_file():
        raise ConfigurationError(f"配置文件不存在：{config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigurationError(f"config.yaml YAML 语法错误：{e}") from e

    if not isinstance(raw, dict):
        raise ConfigurationError("config.yaml 顶层结构应为键值映射")

    # 相对路径基于项目根（config 文件上上级）解析
    project_root = config_path.parent.parent
    try:
        cfg = AppConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigurationError(f"config.yaml 校验失败：{e}") from e

    for name in ("courses_dir", "output_dir", "logs_dir"):
        p: Path = getattr(cfg.paths, name)
        if not p.is_absolute():
            setattr(cfg.paths, name, (project_root / p).resolve())

    logger.debug("配置加载完成：courses_dir={}", cfg.paths.courses_dir)
    return cfg
