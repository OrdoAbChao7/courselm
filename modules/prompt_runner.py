"""NotebookLM v2 pipeline: outline -> introduction -> chapters -> appendices."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from modules.config import AppConfig
    from modules.file_manager import CourseManifest
    from modules.notebooklm import NotebookLMService, UploadReport
    from modules.prompts import PromptBook

GENERATION_SCHEMA_VERSION = 2
_ILLEGAL_FN_CHARS = re.compile(r'[\\/:*?"<>|]')


class PromptRunnerError(Exception):
    """编排层错误基类。"""


class OutlineParseError(PromptRunnerError):
    """课程结构 JSON 无法解析或不满足契约。"""


class ChapterPlan(BaseModel):
    index: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=100)
    topics: list[str] = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def safe_title(cls, value: str) -> str:
        value = _ILLEGAL_FN_CHARS.sub("_", value).strip().strip(".")
        if not value or value in {".", ".."}:
            raise ValueError("章节名称清洗后不能为空")
        return value

    @field_validator("topics")
    @classmethod
    def clean_topics(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if not cleaned:
            raise ValueError("章节主题不能为空")
        return list(dict.fromkeys(cleaned))


class CourseOutline(BaseModel):
    course_name: str = Field(min_length=1)
    chapters: list[ChapterPlan] = Field(min_length=1)


def _extract_json_object(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            _, end = decoder.raw_decode(text[match.start():])
            return text[match.start():match.start() + end]
        except json.JSONDecodeError:
            continue
    raise OutlineParseError("未找到有效的课程结构 JSON")


def parse_course_outline(text: str) -> CourseOutline:
    try:
        payload = json.loads(_extract_json_object(text))
        outline = CourseOutline.model_validate(payload)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise OutlineParseError(f"课程结构 JSON 校验失败：{exc}") from exc
    unique: dict[int, ChapterPlan] = {}
    for chapter in sorted(outline.chapters, key=lambda item: item.index):
        unique.setdefault(chapter.index, chapter)
    chapters = [chapter.model_copy(update={"index": i}) for i, chapter in enumerate(unique.values(), 1)]
    if not chapters:
        raise OutlineParseError("课程结构至少需要一个有效章节")
    return outline.model_copy(update={"chapters": chapters})


def _slug(value: str, limit: int = 60) -> str:
    value = _ILLEGAL_FN_CHARS.sub("_", value).strip().strip(".")
    value = re.sub(r"\s+", "_", value)
    return (value or "未命名")[:limit]


class PipelineState(BaseModel):
    generation_schema_version: int = GENERATION_SCHEMA_VERSION
    notebook_id: str | None = None
    uploaded_files: list[str] = Field(default_factory=list)


class PromptOutcome(BaseModel):
    key: str
    title: str
    success: bool
    from_cache: bool = False
    error: str | None = None
    raw_file: str = ""


class PipelineResult(BaseModel):
    notebook_id: str
    outline: CourseOutline | None = None
    outline_outcome: PromptOutcome | None = None
    introduction_outcome: PromptOutcome | None = None
    chapter_outcomes: list[PromptOutcome] = Field(default_factory=list)
    appendix_outcomes: list[PromptOutcome] = Field(default_factory=list)

    @property
    def all_outcomes(self) -> list[PromptOutcome]:
        return [o for o in [self.outline_outcome, self.introduction_outcome] if o] + self.chapter_outcomes + self.appendix_outcomes

    @property
    def failures(self) -> list[PromptOutcome]:
        return [outcome for outcome in self.all_outcomes if not outcome.success]


async def _ask_with_retry(svc: NotebookLMService, notebook_id: str, question: str, retry: int) -> str:
    from modules.notebooklm import NotebookLMAuthError

    last_error: Exception | None = None
    for attempt in range(retry + 1):
        try:
            return await svc.ask(notebook_id, question)
        except NotebookLMAuthError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < retry:
                logger.warning("提问失败（{}），重试 {}/{}", exc, attempt + 1, retry)
    raise last_error  # type: ignore[misc]


def _load_state(path: Path, fresh: bool) -> PipelineState:
    if fresh or not path.is_file():
        return PipelineState()
    try:
        state = PipelineState.model_validate_json(path.read_text(encoding="utf-8"))
        if state.generation_schema_version != GENERATION_SCHEMA_VERSION:
            return PipelineState()
        return state
    except Exception as exc:
        logger.warning("state.json 解析失败，视为无状态：{}", exc)
        return PipelineState()


def _save_state(path: Path, state: PipelineState) -> None:
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


async def run_pipeline(
    cfg: AppConfig,
    book: PromptBook,
    course_name: str,
    manifest: CourseManifest,
    svc: NotebookLMService,
    *,
    stage: Literal["outline", "introduction", "appendices"] | None = None,
    chapter: int | None = None,
    fresh: bool = False,
) -> PipelineResult:
    """执行 v2 流程；stage/chapter 用于开发调试和断点恢复。"""
    from modules.prompts import render_appendix, render_chapter, render_introduction, render_outline

    out_dir = cfg.paths.output_dir / course_name
    raw_dir = out_dir / "raw" / f"v{GENERATION_SCHEMA_VERSION}"
    chapters_dir = raw_dir / "chapters"
    appendices_dir = raw_dir / "appendices"
    for directory in (raw_dir, chapters_dir, appendices_dir):
        directory.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"
    state = _load_state(state_path, fresh)
    if fresh:
        for path in raw_dir.rglob("*"):
            if path.is_file():
                path.unlink()

    notebook_id = await svc.get_or_create_notebook(course_name)
    state.notebook_id = notebook_id
    rel_files = [f.path.relative_to(manifest.root).as_posix() for f in manifest.files]
    uploaded = set() if fresh else set(state.uploaded_files)
    pending = [f for f, rel in zip(manifest.files, rel_files) if rel not in uploaded]
    if pending:
        partial = manifest.model_copy(update={"files": pending, "total_size_bytes": sum(f.size_bytes for f in pending)})
        report: UploadReport = await svc.upload_sources(notebook_id, partial)
        uploaded.update(rel for rel, f in zip(rel_files, manifest.files) if f in pending and f.path.name in set(report.uploaded))
        state.uploaded_files = sorted(uploaded)
        _save_state(state_path, state)
    else:
        _save_state(state_path, state)

    result = PipelineResult(notebook_id=notebook_id)
    outline_path = raw_dir / "outline.json"
    outline: CourseOutline | None = None
    if outline_path.is_file() and not fresh:
        try:
            outline = CourseOutline.model_validate_json(outline_path.read_text(encoding="utf-8"))
            result.outline_outcome = PromptOutcome(key="course_outline", title=book.planning.course_outline.title, success=True, from_cache=True, raw_file="outline.json")
        except Exception:
            outline = None
    if outline is None:
        try:
            answer = await _ask_with_retry(svc, notebook_id, render_outline(book.planning.course_outline), cfg.prompt_runner.retry)
            outline = parse_course_outline(answer)
            outline_path.write_text(outline.model_dump_json(indent=2), encoding="utf-8")
            result.outline_outcome = PromptOutcome(key="course_outline", title=book.planning.course_outline.title, success=True, raw_file="outline.json")
        except Exception as exc:
            result.outline_outcome = PromptOutcome(key="course_outline", title=book.planning.course_outline.title, success=False, error=str(exc))
            return result
    result.outline = outline
    if stage == "outline":
        return result

    outline_text = json.dumps(outline.model_dump(), ensure_ascii=False, indent=2)
    intro_path = raw_dir / "introduction.md"
    if intro_path.is_file() and not fresh:
        result.introduction_outcome = PromptOutcome(key="introduction", title=book.global_prompts.introduction.title, success=True, from_cache=True, raw_file="introduction.md")
    else:
        try:
            answer = await _ask_with_retry(svc, notebook_id, render_introduction(book.global_prompts.introduction, course_name, outline_text), cfg.prompt_runner.retry)
            intro_path.write_text(answer, encoding="utf-8")
            result.introduction_outcome = PromptOutcome(key="introduction", title=book.global_prompts.introduction.title, success=True, raw_file="introduction.md")
        except Exception as exc:
            result.introduction_outcome = PromptOutcome(key="introduction", title=book.global_prompts.introduction.title, success=False, error=str(exc))
    if stage == "introduction":
        return result

    selected = [item for item in outline.chapters if chapter is None or item.index == chapter]
    if chapter is not None and not selected:
        raise PromptRunnerError(f"不存在第 {chapter} 章")
    for item in selected:
        path = chapters_dir / f"{item.index:02d}-{_slug(item.title)}.md"
        key = f"chapter_{item.index:02d}"
        if path.is_file() and not fresh:
            result.chapter_outcomes.append(PromptOutcome(key=key, title=item.title, success=True, from_cache=True, raw_file=f"chapters/{path.name}"))
            continue
        try:
            answer = await _ask_with_retry(svc, notebook_id, render_chapter(book.dynamic.chapter, item.index, item.title, "、".join(item.topics), outline_text), cfg.prompt_runner.retry)
            path.write_text(answer, encoding="utf-8")
            result.chapter_outcomes.append(PromptOutcome(key=key, title=item.title, success=True, raw_file=f"chapters/{path.name}"))
        except Exception as exc:
            result.chapter_outcomes.append(PromptOutcome(key=key, title=item.title, success=False, error=str(exc)))

    if chapter is not None or stage == "chapters":
        return result
    for prompt in book.appendices:
        path = appendices_dir / f"{prompt.id}.md"
        if path.is_file() and not fresh:
            result.appendix_outcomes.append(PromptOutcome(key=prompt.id, title=prompt.title, success=True, from_cache=True, raw_file=f"appendices/{path.name}"))
            continue
        try:
            answer = await _ask_with_retry(svc, notebook_id, render_appendix(prompt, outline_text), cfg.prompt_runner.retry)
            path.write_text(answer, encoding="utf-8")
            result.appendix_outcomes.append(PromptOutcome(key=prompt.id, title=prompt.title, success=True, raw_file=f"appendices/{path.name}"))
        except Exception as exc:
            result.appendix_outcomes.append(PromptOutcome(key=prompt.id, title=prompt.title, success=False, error=str(exc)))
    return result
