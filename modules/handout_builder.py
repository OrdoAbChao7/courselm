"""Assemble existing Obsidian Markdown into an exam-focused handout manuscript."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from modules.handout_template import HandoutTemplate, load_handout_template


@dataclass(frozen=True)
class HandoutBuildResult:
    manuscript_path: Path
    tex_path: Path
    missing_inputs: tuple[str, ...]
    template: HandoutTemplate


def _safe_course_dir(output_dir: Path, course: str) -> Path:
    course_path = Path(course)
    if not course.strip() or course_path.name != course or course_path.is_absolute():
        raise ValueError("课程名不能包含路径分隔符或路径跳转")
    return output_dir.resolve() / course


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _section(title: str, source: str, content: str) -> str:
    return f"# {title}\n\n> 来源：{source}\n\n{content}\n"


def _without_leading_h1(content: str) -> str:
    """源文档常自带 H1；目录标题由组装器统一提供，避免重复标题。"""
    content = re.sub(r"^\s*---\s*\n.*?\n---\s*\n*", "", content, count=1, flags=re.DOTALL)
    return re.sub(r"^\s*#\s+[^\n]+\n*", "", content, count=1).strip()


def _safe_source(source_dir: Path, relative: str) -> Path:
    path = (source_dir / relative).resolve()
    if not path.is_relative_to(source_dir.resolve()):
        raise ValueError(f"讲义源文件路径越界：{relative}")
    return path


def build_handout(
    course: str,
    output_dir: Path,
    *,
    courses_dir: Path | None = None,
    template_path: Path | None = None,
    max_chapters: int | None = None,
) -> HandoutBuildResult:
    """Build a deterministic manuscript from the current Obsidian export."""

    if max_chapters is not None and max_chapters <= 0:
        raise ValueError("章节数量上限必须大于 0")

    course_dir = _safe_course_dir(Path(output_dir), course)
    if courses_dir is None:
        courses_dir = Path(output_dir).resolve().parent / "courses"
    template = load_handout_template(course, courses_dir, template_path)
    source_dir = course_dir / "md"
    handout_dir = course_dir / "handout"
    chapters_dir = handout_dir / "chapters"
    handout_dir.mkdir(parents=True, exist_ok=True)
    chapters_dir.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    parts = [
        f"> {template.subtitle}",
        "> 这是可人工审阅的初稿，正式发布前请完成事实、公式、例题和版权检查。",
        "",
    ]

    for section in template.sections:
        if section.page_break:
            parts.extend(["<!-- PAGE_BREAK -->", ""])
        if section.source is not None:
            path = _safe_source(source_dir, section.source)
            if not path.is_file():
                if section.required:
                    missing.append(section.source)
                continue
            parts.append(_section(section.title, section.source, _without_leading_h1(_read(path))))
            continue

        pattern = section.glob or ""
        glob_root = _safe_source(source_dir, pattern.split("*")[0].rstrip("/"))
        detail_paths = sorted(
            (path for path in source_dir.glob(pattern) if path.is_file()),
            key=lambda path: path.name,
        )
        if max_chapters is not None and section.id == "chapters":
            detail_paths = detail_paths[:max_chapters]
        if not detail_paths:
            if section.required:
                missing.append(pattern)
            continue
        if section.id != "chapters":
            parts.extend([f"# {section.title}", ""])
        for path in detail_paths:
            if not path.resolve().is_relative_to(glob_root.parent.resolve()):
                raise ValueError(f"讲义源文件路径越界：{path}")
            content = _without_leading_h1(_read(path))
            chapter_path = chapters_dir / path.name
            chapter_path.write_text(content + "\n", encoding="utf-8")
            relative = path.relative_to(source_dir).as_posix()
            display_title = re.sub(r"^\d+[-_. ]*", "", path.stem)
            if section.id == "chapters":
                ordinal = re.match(r"^(\d+)", path.stem)
                display_title = f"第{int(ordinal.group(1)) if ordinal else display_title}章 {display_title}"
            parts.append(_section(display_title, relative, content))

    if missing:
        warning = "、".join(missing)
        parts.insert(2, f"> 缺失输入：{warning}。本稿为部分生成结果，请补齐资料后重新构建。")

    manuscript_path = handout_dir / "manuscript.md"
    manuscript_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    tex_path = handout_dir / "main.tex"
    return HandoutBuildResult(manuscript_path, tex_path, tuple(missing), template)
