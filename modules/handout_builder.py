"""Assemble existing Obsidian Markdown into an exam-focused handout manuscript."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import shutil
from modules.handout_template import HandoutTemplate, load_handout_template
from modules.question_index import ExampleEntry, index_chapter, is_current_generation, pdf_question_index


@dataclass(frozen=True)
class HandoutBuildResult:
    manuscript_path: Path
    tex_path: Path
    missing_inputs: tuple[str, ...]
    template: HandoutTemplate


def _sync_handout_figures(course_dir: Path, handout_dir: Path, manuscript: str) -> list[str]:
    """Legacy checker: never copy an unbound library or resolve by basename."""
    from modules.figure_integrity import image_references, local_file
    missing_images: list[str] = []
    for ref in image_references(manuscript):
        if not local_file(handout_dir, ref.path).is_file():
            missing_images.append(f"插图不存在: {ref.path}")
    return missing_images


def _safe_course_dir(output_dir: Path, course: str) -> Path:
    course_path = Path(course)
    if not course.strip() or course_path.name != course or course_path.is_absolute():
        raise ValueError("课程名不能包含路径分隔符或路径跳转")
    return output_dir.resolve() / course


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _section(title: str, content: str, *, level: int = 1) -> str:
    return f"{'#' * level} {title}\n\n{content}\n"


def _without_leading_h1(content: str) -> str:
    """源文档常自带 H1；目录标题由组装器统一提供，避免重复标题。"""
    content = re.sub(r"^\s*---\s*\n.*?\n---\s*\n*", "", content, count=1, flags=re.DOTALL)
    return re.sub(r"^\s*#\s+[^\n]+\n*", "", content, count=1).strip()


def _source_title(content: str, fallback: str) -> str:
    content = re.sub(r"^\s*---\s*\n.*?\n---\s*\n*", "", content, count=1, flags=re.DOTALL)
    match = re.match(r"^\s*#\s+([^\n]+)", content)
    return match.group(1).strip() if match else fallback


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
    prefer_source_titles: bool = False,
    rebuild_question_index: bool = True,
    figure_task_id: str | None = None,
    figure_course: str | None = None,
    figure_source_dir: Path | None = None,
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

    from modules.figure_integrity import prepare_markdown, copy_bound_figures
    from modules.figure_models import FigureManifest
    figure_manifest = FigureManifest.load(
        course_dir / 'figures' / 'manifest.json', figure_task_id or f'course_{course}',
        course if figure_course is None else figure_course)
    figure_sources = figure_source_dir if figure_source_dir is not None else courses_dir / course
    figure_omissions: list[dict] = []
    missing_figure_requests: list[dict] = []
    bound_assets: dict[str, str] = {}
    inserted_figures = 0
    approved_references: Counter = Counter()

    def prepare(content: str, path: Path) -> str:
        nonlocal inserted_figures
        result = prepare_markdown(content, path.relative_to(source_dir).as_posix(), figure_manifest,
                                  figure_root=course_dir, source_root=figure_sources)
        figure_omissions.extend(result.omissions)
        bound_assets.update(result.assets)
        inserted_figures += result.inserted
        from modules.figure_integrity import image_references
        approved_references.update(ref.path for ref in image_references(result.markdown))
        from modules.figure_matcher import FigureMatcher
        warnings, _ = FigureMatcher(figure_manifest).audit_markdown_content(
            result.markdown, path.relative_to(source_dir).as_posix())
        missing_figure_requests.extend(w.model_dump() for w in warnings)
        if warnings:
            from modules.figure_integrity import questions, OMITTED
            patches = []
            for question in questions(result.markdown):
                if (any(question.start_line <= w.line_number <= question.end_line for w in warnings)
                        and OMITTED not in result.markdown[question.start:question.end]):
                    patches.append(question.end)
            for position in reversed(patches):
                result.markdown = result.markdown[:position].rstrip() + '\n\n' + OMITTED + '\n\n' + result.markdown[position:]
        return result.markdown

    missing: list[str] = []
    parts: list[str] = []
    examples: list[ExampleEntry] = []
    written_chapters = 0
    outline_path = course_dir / "raw" / "v3" / "outline.json"
    expected_chapters: set[int] | None = None
    expected_outline: list[dict] | None = None
    if outline_path.is_file():
        outline = json.loads(_read(outline_path))
        chapters_list = outline.get("chapters", [])
        if max_chapters is not None:
            chapters_list = chapters_list[:max_chapters]
        expected_chapters = {int(chapter["index"]) for chapter in chapters_list}
        expected_outline = chapters_list

    for section in template.sections:
        if section.page_break:
            parts.extend(["<!-- PAGE_BREAK -->", ""])
        if section.source is not None:
            path = _safe_source(source_dir, section.source)
            if not path.is_file():
                if section.required:
                    missing.append(section.source)
                continue
            source = prepare(_read(path), path)
            title = _source_title(source, section.title) if prefer_source_titles else section.title
            parts.append(_section(title, _without_leading_h1(source)))
            continue

        pattern = section.glob or ""
        glob_root = _safe_source(source_dir, pattern.split("*")[0].rstrip("/"))
        detail_paths = sorted(
            (path for path in source_dir.glob(pattern) if path.is_file()),
            key=lambda path: path.name,
        )
        if section.id == "chapters":
            if expected_outline is not None:
                selected_paths: list[Path] = []
                for ch in expected_outline:
                    idx = int(ch["index"])
                    title = str(ch.get("title", "")).strip()
                    candidates = [
                        p for p in detail_paths
                        if (m := re.match(r"^0*(\d+)", p.stem)) and int(m.group(1)) == idx
                    ]
                    matched = None
                    for cand in candidates:
                        if is_current_generation(_read(cand)):
                            cleaned_title = re.sub(r'[\\/:*?"<>|\s]+', '_', title).strip('_')
                            if title and (title in cand.stem or (cleaned_title and cleaned_title in cand.stem)):
                                matched = cand
                                break
                    if matched is None and len(candidates) == 1:
                        if is_current_generation(_read(candidates[0])):
                            matched = candidates[0]
                    if matched is not None:
                        selected_paths.append(matched)
                    else:
                        missing.append(f"第{idx}章")
                detail_paths = selected_paths
            else:
                current = [path for path in detail_paths if is_current_generation(_read(path))]
                if current:
                    detail_paths = current
                if max_chapters is not None:
                    detail_paths = detail_paths[:max_chapters]
        if not detail_paths:
            if section.required and not (section.id == "chapters" and expected_chapters is not None):
                missing.append(pattern)
            continue
        if section.id != "chapters":
            parts.extend([f"# {section.title}", ""])
        for path in detail_paths:
            if section.id == "chapters" and written_chapters:
                parts.extend(["<!-- PAGE_BREAK -->", ""])
            if not path.resolve().is_relative_to(glob_root.parent.resolve()):
                raise ValueError(f"讲义源文件路径越界：{path}")
            source_content = prepare(_read(path), path)
            if section.id == "chapters":
                source_content, found = index_chapter(source_content, path.name, len(examples) + 1, annotate=True)
                examples.extend(found)
            content = _without_leading_h1(source_content)
            chapter_path = chapters_dir / path.name
            chapter_path.write_text(content + "\n", encoding="utf-8")
            display_title = re.sub(r"^\d+[-_. ]*", "", path.stem)
            if section.id == "chapters":
                ordinal = re.match(r"^(\d+)", path.stem)
                display_title = f"第{int(ordinal.group(1)) if ordinal else display_title}章 {display_title}"
                written_chapters += 1
            if prefer_source_titles:
                display_title = _source_title(source_content, display_title)
            if rebuild_question_index and section.id == "appendices" and "题型索引" in path.stem and examples:
                content = pdf_question_index(examples)
            parts.append(_section(display_title, content, level=2 if section.id == "appendices" else 1))

    manuscript_content = "\n".join(parts).rstrip() + "\n"
    # Reference definitions from another chapter can activate previously literal
    # image syntax only after assembly. Reparse and remove those unknown images.
    from modules.figure_integrity import image_references, OMITTED
    for ref in reversed(image_references(manuscript_content)):
        if ref.path not in bound_assets:
            manuscript_content = manuscript_content[:ref.start] + OMITTED + manuscript_content[ref.end:]
            figure_omissions.append({'document': 'manuscript.md', 'path': ref.path,
                                     'line': ref.line, 'reason': 'UNBOUND_ASSEMBLED_REFERENCE'})
    if Counter(ref.path for ref in image_references(manuscript_content)) != approved_references:
        raise ValueError('组装后的题图引用与已批准绑定不一致，已阻止构建')
    copy_bound_figures(course_dir, handout_dir, bound_assets)
    (handout_dir / 'figure-report.json').write_text(json.dumps({
        'policy': 'explicit-question-binding-v1', 'task_id': figure_manifest.task_id,
        'inserted': inserted_figures, 'omitted': len(figure_omissions),
        'omissions': figure_omissions, 'assets': bound_assets,
        'required_missing': len(missing_figure_requests), 'missing_requests': missing_figure_requests,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    missing_figs = _sync_handout_figures(course_dir, handout_dir, manuscript_content)
    if missing_figs:
        missing.extend(missing_figs)

    if missing:
        warning = "、".join(missing)
        manuscript_content = f"> 缺失输入：{warning}。本稿为部分生成结果，请补齐资料后重新构建。\n\n" + manuscript_content

    manuscript_path = handout_dir / "manuscript.md"
    manuscript_path.write_text(manuscript_content, encoding="utf-8")
    tex_path = handout_dir / "main.tex"
    return HandoutBuildResult(manuscript_path, tex_path, tuple(missing), template)
