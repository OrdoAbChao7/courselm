"""NotebookLM pipeline: outline -> introduction -> chapters."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from modules.config import AppConfig
    from modules.file_manager import CourseManifest
    from modules.notebooklm import NotebookLMService, UploadReport
    from modules.prompts import PromptBook

GENERATION_SCHEMA_VERSION = 3
_ILLEGAL_FN_CHARS = re.compile(r'[\\/:*?"<>|]')


class PromptRunnerError(Exception):
    """编排层错误基类。"""


class OutlineParseError(PromptRunnerError):
    """课程结构 JSON 无法解析或不满足契约。"""


class ChapterFormatError(PromptRunnerError):
    """章节缺少由例题到练习的可读教学顺序。"""


SOURCE_LABEL_PATTERN = re.compile(
    r"[\[【(（](?:来源[：:])?(?:(?:往年|历年|期末|考研)?真题(?:[·.\s/_-][^\]】)）]+)?|老师题库|老师课件|作业原题|作业题|教材例题|教材习题|课后习题|改编题|必要补充)[\]】)）]"
)


def repair_missing_source_labels(text: str) -> str:
    """自动为缺少来源标记的标准例题补充 [教材例题]，避免模型因细微标签遗漏丢弃整章。"""
    types = list(re.finditer(r"(?m)^##\s+(?:题型|考点)(?:[一二三四五六七八九十]+|\d+)\s*[：:].+$", text))
    end = re.search(r"(?m)^##\s+(?:课时过关练习|章末过关|课时练习)\s*$", text)
    if not types or not end:
        return text

    new_text = text
    for number in range(len(types) - 1, -1, -1):
        cur_types = list(re.finditer(r"(?m)^##\s+(?:题型|考点)(?:[一二三四五六七八九十]+|\d+)\s*[：:].+$", new_text))
        cur_end = re.search(r"(?m)^##\s+(?:课时过关练习|章末过关|课时练习)\s*$", new_text)
        if not cur_types or not cur_end or number >= len(cur_types):
            break
        block_end = cur_types[number + 1].start() if number + 1 < len(cur_types) else cur_end.start()
        match = cur_types[number]
        block = new_text[match.end():block_end]
        headings = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", block))
        found = next((item for item in headings if any(item.group(1).startswith(opt) for opt in ("标准例题", "典型例题"))), None)
        if found is None:
            continue
        following = next((item.start() for item in headings if item.start() > found.start()), len(block))
        example_content = block[found.start():following]
        if not SOURCE_LABEL_PATTERN.search(example_content):
            post_heading = block[found.end():following]
            lines = post_heading.splitlines(keepends=True)
            for idx, line in enumerate(lines):
                if line.strip():
                    stripped = line.rstrip("\r\n")
                    eol = line[len(stripped):]
                    lines[idx] = f"{stripped} [教材例题]{eol}"
                    repaired_post = "".join(lines)
                    new_block = block[:found.end()] + repaired_post + block[following:]
                    new_text = new_text[:match.end()] + new_block + new_text[block_end:]
                    break
    return new_text


def validate_chapter_markdown(text: str, chapter_index: int) -> None:
    """Reject a chapter that omits the agreed cram-course worked-example learning loop."""
    if not re.search(rf"(?m)^#\s+第{chapter_index}章\s+.+$", text):
        raise ChapterFormatError(f"第{chapter_index}章缺少正确章标题")
    if re.search(r"\[推测\]|得分盘|冲刺盘", text):
        raise ChapterFormatError("章节出现未经证实的考试标签")
    route = re.search(r"(?m)^##\s+(?:考情速览|本章路线)\s*$", text)
    end = re.search(r"(?m)^##\s+(?:课时过关练习|章末过关|课时练习)\s*$", text)
    types = list(re.finditer(r"(?m)^##\s+(?:题型|考点)(?:[一二三四五六七八九十]+|\d+)\s*[：:].+$", text))
    valid_h2 = {"考情速览", "本章路线", "课时过关练习", "章末过关", "课时练习"}
    for heading in re.findall(r"(?m)^##\s+(.+?)\s*$", text):
        if heading not in valid_h2 and not re.fullmatch(r"(?:题型|考点)(?:[一二三四五六七八九十]+|\d+)\s*[：:].+", heading):
            raise ChapterFormatError(f"出现与例题教学顺序无关的二级标题：{heading}")
    if not route or not end or not types or not (route.start() < types[0].start() and all(item.start() < end.start() for item in types)):
        raise ChapterFormatError("章节须按考情速览/本章路线、题型、课时过关练习/章末过关的顺序组织")
    required_stages = [
        ("核心考点与速记口诀", "先知道什么", "核心考点", "考点速记"),
        ("标准例题", "典型例题"),
        ("跟着做", "规范解答"),
        ("避坑提醒", "从题归纳", "解题技巧"),
        ("自己试", "独立练习"),
    ]
    for number, match in enumerate(types):
        block_end = types[number + 1].start() if number + 1 < len(types) else end.start()
        block = text[match.end():block_end]
        headings = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", block))
        positions: list[int] = []
        for stage_options in required_stages:
            found = next((item for item in headings if any(item.group(1).startswith(opt) for opt in stage_options)), None)
            if found is None:
                raise ChapterFormatError(f"题型{number + 1}缺少{stage_options[0]}")
            positions.append(found.start())
            following = next((item.start() for item in headings if item.start() > found.start()), len(block))
            if not block[found.end():following].strip():
                raise ChapterFormatError(f"题型{number + 1}的{stage_options[0]}没有内容")
            if any(opt in stage_options for opt in ("标准例题", "典型例题")) and not SOURCE_LABEL_PATTERN.search(
                block[found.start():following],
            ):
                raise ChapterFormatError(f"题型{number + 1}的标准例题缺少来源标记")
        if positions != sorted(positions):
            raise ChapterFormatError(f"题型{number + 1}的小节顺序错误：应先讲标准例题再归纳")
        practice = block[positions[-1]:]
        solution = re.search(r"(?m)^####\s+(?:解答|答案与解析|详细解答)\s*$", practice)
        if not solution or "提示" not in practice[:solution.start()] or not practice[solution.end():].strip():
            raise ChapterFormatError(f"题型{number + 1}的自己试需要先给提示，再给独立的解答标题和内容")


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

    @property
    def all_outcomes(self) -> list[PromptOutcome]:
        return [o for o in [self.outline_outcome, self.introduction_outcome] if o] + self.chapter_outcomes

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
            return PipelineState(notebook_id=state.notebook_id, uploaded_files=state.uploaded_files)
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
    fresh: bool = False,
    on_progress=None,
) -> PipelineResult:
    """生成大纲、绪论与全部章节，自动跳过有效缓存。"""
    from modules.prompts import render_chapter, render_introduction, render_outline

    out_dir = cfg.paths.output_dir / course_name
    raw_dir = out_dir / "raw" / f"v{GENERATION_SCHEMA_VERSION}"
    chapters_dir = raw_dir / "chapters"
    for directory in (raw_dir, chapters_dir):
        directory.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"
    state = _load_state(state_path, fresh)
    if fresh:
        for path in raw_dir.rglob("*"):
            if path.is_file():
                path.unlink()

    report_progress = on_progress or (lambda stage, detail: None)
    report_progress('NotebookLM 连接', '连接当前任务独立 Notebook')
    notebook_id = await svc.get_or_create_notebook(course_name)
    state.notebook_id = notebook_id
    rel_files = [f.path.relative_to(manifest.root).as_posix() for f in manifest.files]
    uploaded = set() if fresh else set(state.uploaded_files)
    pending = [f for f, rel in zip(manifest.files, rel_files) if rel not in uploaded]
    if pending:
        report_progress('NotebookLM 资料上传', f'上传 {len(pending)} 份资料并等待索引')
        partial = manifest.model_copy(update={"files": pending, "total_size_bytes": sum(f.size_bytes for f in pending)})
        report: UploadReport = await svc.upload_sources(notebook_id, partial)
        uploaded.update(rel for rel, f in zip(rel_files, manifest.files) if f in pending and f.path.name in set(report.uploaded))
        state.uploaded_files = sorted(uploaded)
        _save_state(state_path, state)
    else:
        _save_state(state_path, state)

    report_progress('课程大纲生成', '读取有效缓存或请求课程大纲')
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

    outline_text = json.dumps(outline.model_dump(), ensure_ascii=False, indent=2)
    report_progress('绪论生成', '读取有效缓存或生成绪论')
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
    for item in outline.chapters:
        report_progress('逐章节生成', f'第 {item.index} 章：{item.title}；已完成 {sum(o.success for o in result.chapter_outcomes)}/{len(outline.chapters)} 章')
        path = chapters_dir / f"{item.index:02d}-{_slug(item.title)}.md"
        key = f"chapter_{item.index:02d}"
        if path.is_file() and not fresh:
            try:
                validate_chapter_markdown(path.read_text(encoding="utf-8"), item.index)
                result.chapter_outcomes.append(PromptOutcome(key=key, title=item.title, success=True, from_cache=True, raw_file=f"chapters/{path.name}"))
                continue
            except ChapterFormatError as exc:
                logger.warning("章节缓存结构无效，重新生成第{}章：{}", item.index, exc)
        try:
            question = render_chapter(book.dynamic.chapter, item.index, item.title, "、".join(item.topics), outline_text)
            for attempt in range(2):
                answer = await _ask_with_retry(svc, notebook_id, question, cfg.prompt_runner.retry)
                try:
                    validate_chapter_markdown(answer, item.index)
                    break
                except ChapterFormatError as exc:
                    if "缺少来源标记" in str(exc):
                        repaired = repair_missing_source_labels(answer)
                        try:
                            validate_chapter_markdown(repaired, item.index)
                            answer = repaired
                            logger.info("第{}章自动补全例题来源标记成功，通过校验", item.index)
                            break
                        except ChapterFormatError:
                            pass
                    if attempt:
                        raise
                    question += f"\n\n上次输出不符合讲义结构：{exc}。请重新完整生成本章，逐题型遵守标准例题→跟着做→从题归纳→自己试的顺序。注意每道标准例题必须附带[教材例题]、[真题·年份]等来源标记。"
            path.write_text(answer, encoding="utf-8")
            result.chapter_outcomes.append(PromptOutcome(key=key, title=item.title, success=True, raw_file=f"chapters/{path.name}"))
        except Exception as exc:
            logger.error("生成第{}章《{}》失败：{}", item.index, item.title, exc)
            result.chapter_outcomes.append(PromptOutcome(key=key, title=item.title, success=False, error=str(exc)))

    return result
