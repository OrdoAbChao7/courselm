"""Assemble existing Obsidian Markdown into an exam-focused handout manuscript."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HandoutBuildResult:
    manuscript_path: Path
    tex_path: Path
    missing_inputs: tuple[str, ...]


def _safe_course_dir(output_dir: Path, course: str) -> Path:
    course_path = Path(course)
    if not course.strip() or course_path.name != course or course_path.is_absolute():
        raise ValueError("课程名不能包含路径分隔符或路径跳转")
    return output_dir.resolve() / course


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _section(title: str, source: str, content: str) -> str:
    return f"## {title}\n\n> 来源：{source}\n\n{content}\n"


def build_handout(course: str, output_dir: Path, *, max_types: int = 12) -> HandoutBuildResult:
    """Build a deterministic manuscript from the current Obsidian export."""

    if max_types <= 0:
        raise ValueError("题型数量上限必须大于 0")

    course_dir = _safe_course_dir(Path(output_dir), course)
    source_dir = course_dir / "md"
    handout_dir = course_dir / "handout"
    chapters_dir = handout_dir / "chapters"
    handout_dir.mkdir(parents=True, exist_ok=True)
    chapters_dir.mkdir(parents=True, exist_ok=True)

    fixed = (
        ("知识结构", "知识结构.md"),
        ("公式总结", "公式总结.md"),
        ("题型总结", "题型/题型总结.md"),
    )
    missing: list[str] = []
    parts = [
        f"# {course}期末复习讲义初稿",
        "",
        "> 面向基础一般、复习时间有限的同学。本讲义按“先抓框架，再记公式，最后练题型”的顺序组织。",
        "> 这是可人工审阅的初稿，正式发布前请完成事实、公式、例题和版权检查。",
        "",
    ]

    for title, relative in fixed:
        path = source_dir / relative
        if not path.is_file():
            missing.append(relative)
            continue
        parts.append(_section(title, relative, _read(path)))

    question_dir = source_dir / "题型"
    detail_paths = sorted(
        (p for p in question_dir.glob("*.md") if p.name != "题型总结.md"),
        key=lambda p: p.name,
    )
    for path in detail_paths[:max_types]:
        content = _read(path)
        chapter_path = chapters_dir / path.name
        chapter_path.write_text(content + "\n", encoding="utf-8")
        parts.append(_section(path.stem, f"题型/{path.name}", content))

    if missing:
        warning = "、".join(missing)
        parts.insert(2, f"> 缺失输入：{warning}。本稿为部分生成结果，请补齐资料后重新构建。")

    manuscript_path = handout_dir / "manuscript.md"
    manuscript_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    tex_path = handout_dir / "main.tex"
    return HandoutBuildResult(manuscript_path, tex_path, tuple(missing))
