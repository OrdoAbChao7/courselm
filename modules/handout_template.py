"""Validated handout table-of-contents templates with optional course overrides."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from modules.path_manager import app_dir


class HandoutTemplateError(Exception):
    """Raised when a default or course handout template is invalid."""


def _validate_relative_pattern(value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or not value.strip():
        raise ValueError("源文件路径必须是讲义 Markdown 目录内的相对路径")
    return value.replace("\\", "/")


class HandoutSection(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str | None = None
    glob: str | None = None
    required: bool = True
    page_break: bool = True

    @field_validator("source", "glob")
    @classmethod
    def _safe_paths(cls, value: str | None) -> str | None:
        return _validate_relative_pattern(value) if value is not None else None

    @model_validator(mode="after")
    def _one_source_kind(self) -> "HandoutSection":
        if (self.source is None) == (self.glob is None):
            raise ValueError("每个 section 必须且只能设置 source 或 glob")
        return self


class HandoutTemplate(BaseModel):
    version: int = 1
    title_suffix: str = Field(min_length=1)
    subtitle: str = "面向基础薄弱学生的考前三天复习方案"
    sections: list[HandoutSection] = Field(min_length=1)
    latex: dict[str, str] = Field(default_factory=dict)

    @field_validator("sections")
    @classmethod
    def _unique_section_ids(cls, value: list[HandoutSection]) -> list[HandoutSection]:
        ids = [section.id for section in value]
        if len(ids) != len(set(ids)):
            raise ValueError(f"section id 重复：{ids}")
        return value


def _read_yaml(path: Path, label: str) -> dict:
    if not path.is_file():
        raise HandoutTemplateError(f"{label}不存在：{path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise HandoutTemplateError(f"{label} YAML 语法错误：{exc}") from exc
    if not isinstance(raw, dict):
        raise HandoutTemplateError(f"{label}顶层必须是键值映射")
    return raw


def load_handout_template(
    course: str,
    courses_dir: Path,
    default_path: Path | None = None,
) -> HandoutTemplate:
    """Load the default template and merge an optional per-course override."""

    course_path = Path(course)
    if not course.strip() or course_path.name != course or course_path.is_absolute():
        raise HandoutTemplateError("课程名不能包含路径分隔符或路径跳转")

    if default_path is None:
        default_path = app_dir() / "config" / "handout_templates" / "default.yaml"
    merged = _read_yaml(Path(default_path), "默认讲义模板")

    override_path = Path(courses_dir).resolve() / course / "handout.yaml"
    if override_path.is_file():
        override = _read_yaml(override_path, "课程讲义模板")
        merged = {**merged, **override}
        merged["latex"] = {
            **(_read_yaml(Path(default_path), "默认讲义模板").get("latex") or {}),
            **(override.get("latex") or {}),
        }

    try:
        return HandoutTemplate.model_validate(merged)
    except ValidationError as exc:
        raise HandoutTemplateError(f"讲义模板校验失败：{exc}") from exc
