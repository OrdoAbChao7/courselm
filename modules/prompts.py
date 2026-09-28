"""Version 2 prompt schema for a course-structure-driven handout pipeline."""

from __future__ import annotations

from string import Formatter
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from modules.path_manager import app_dir

GENERATION_SCHEMA_VERSION = 3

MARKDOWN_OUTPUT_RULES = """

输出规范：
1. 只依据已上传的课程资料；资料未提供的事实写“[待确认]”，根据资料作出的判断写“[推测]”。禁止编造考试时间、题型、分值、频率、老师偏好、真题年份和题目来源。
2. 输出标准 Markdown。行内公式使用 $...$，独立公式使用 $$...$$；使用标准 LaTeX，下标用 _，不要使用 HTML Entity、HTML 换行标签或反斜杠伪公式。
3. 面向有高中基础、刚学本课程的学生。术语首次出现必须解释；概念放在首次用到它的例题旁。每个关键解题动作都说明原因，练习要有提示和有步骤的解答。
4. 例题来源只能使用 [真题·年份]、[老师题库]、[老师课件]、[作业原题]、[教材例题]、[改编题]、[必要补充]；无法证明来源时不得标真题。
5. 用短段落和清楚的编号步骤；仅在对比确有帮助时用不超过三列的小表。避免多层列表、表情符号、营销化标题、空泛总结和重复讲解。标题不要手写章内小节编号，以免 PDF 重复编号。
""".strip()


class PromptConfigError(Exception):
    """Prompt 配置缺失、语法错误或校验失败。"""


class PromptBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    output_file: str = Field(min_length=1)
    template: str = Field(min_length=1)


class OutlinePrompt(PromptBase):
    id: str = "course_outline"


class IntroductionPrompt(PromptBase):
    id: str = "introduction"


class AppendixPrompt(PromptBase):
    id: str


class GlobalPrompts(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    introduction: IntroductionPrompt
    appendices: list[AppendixPrompt] = Field(min_length=3, max_length=3)

    @field_validator("appendices")
    @classmethod
    def unique_ids(cls, value: list[AppendixPrompt]) -> list[AppendixPrompt]:
        ids = [item.id for item in value]
        if ids != ["formula_appendix", "question_index", "final_review"]:
            raise PromptConfigError("appendices 必须按公式、题型索引、考前提要顺序配置")
        return value


class ChapterPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    output_subdir: str = Field(min_length=1)
    template: str = Field(min_length=1)


class PlanningPrompts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_outline: OutlinePrompt


class DynamicPrompts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter: ChapterPrompt


class PromptBook(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_version: int = Field(default=GENERATION_SCHEMA_VERSION, alias="generation_schema_version")
    planning: PlanningPrompts
    global_prompts: GlobalPrompts = Field(alias="global")
    dynamic: DynamicPrompts

    @property
    def appendices(self) -> list[AppendixPrompt]:
        return self.global_prompts.appendices


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name}


def _check_prompt(template: str, required: set[str], forbidden: set[str], label: str) -> None:
    actual = _placeholders(template)
    missing = required - actual
    illegal = actual - required
    if missing:
        raise PromptConfigError(f"{label} 缺少占位符：{sorted(missing)}")
    if illegal or actual & forbidden:
        raise PromptConfigError(f"{label} 使用了非法占位符：{sorted(illegal or actual & forbidden)}")


def _validate_placeholders(book: PromptBook) -> None:
    _check_prompt(book.planning.course_outline.template, set(), {"chapter_index", "chapter_title", "topics", "outline"}, "course_outline")
    _check_prompt(book.global_prompts.introduction.template, {"course_name", "outline"}, {"chapter_index", "chapter_title", "topics"}, "introduction")
    _check_prompt(book.dynamic.chapter.template, {"chapter_index", "chapter_title", "topics", "outline"}, set(), "chapter")
    for appendix in book.appendices:
        _check_prompt(appendix.template, {"outline"}, {"chapter_index", "chapter_title", "topics"}, appendix.id)


def load_prompts(path: Path | None = None) -> PromptBook:
    if path is None:
        path = app_dir() / "config" / "prompts.yaml"
    path = Path(path)
    if not path.is_file():
        raise PromptConfigError(f"Prompt 配置文件不存在：{path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        book = PromptBook.model_validate(raw)
    except yaml.YAMLError as exc:
        raise PromptConfigError(f"prompts.yaml YAML 语法错误：{exc}") from exc
    except (ValidationError, TypeError) as exc:
        raise PromptConfigError(f"prompts.yaml 校验失败：{exc}") from exc
    if book.schema_version != GENERATION_SCHEMA_VERSION:
        raise PromptConfigError(f"只支持 generation_schema_version={GENERATION_SCHEMA_VERSION}")
    _validate_placeholders(book)
    return book


def _render(template: str, **values: object) -> str:
    return f"{template.format(**values).rstrip()}\n\n{MARKDOWN_OUTPUT_RULES}"


def render_outline(prompt: OutlinePrompt) -> str:
    return _render(prompt.template)


def render_introduction(prompt: IntroductionPrompt, course_name: str, outline: str) -> str:
    return _render(prompt.template, course_name=course_name, outline=outline)


def render_chapter(prompt: ChapterPrompt, chapter_index: int, chapter_title: str, topics: str, outline: str = "") -> str:
    return _render(prompt.template, chapter_index=chapter_index, chapter_title=chapter_title, topics=topics, outline=outline)


def render_appendix(prompt: AppendixPrompt, outline: str) -> str:
    return _render(prompt.template, outline=outline)
