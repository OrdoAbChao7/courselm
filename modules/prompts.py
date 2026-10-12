"""Current prompt schema for a course-structure-driven handout pipeline."""

from __future__ import annotations

from string import Formatter
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from modules.path_manager import app_dir

GENERATION_SCHEMA_VERSION = 3

MARKDOWN_OUTPUT_RULES = """

输出规范：
1. 课程范围、考情和题目来源只依据已上传资料；资料未明确提及的事实写“[待确认]”。严禁凭空臆测考试时间、老师偏好或虚构真题年份。考情速览中的分值与重要程度依据资料及学科常规权重给出合理估计。允许为教学自编典型入门题，但须标[必要补充]并核对解答。不要输出[推测]、得分盘或冲刺盘等标签。
2. 输出标准 Markdown。行内公式使用 $...$，独立公式使用 $$...$$；使用标准 LaTeX，下标用 _，不要使用 HTML Entity、HTML 换行标签或反斜杠伪公式。
3. 面向有高中基础、刚学本课程的学生。术语首次出现必须解释；概念与公式紧密结合例题讲解。每个关键解题动作都说明原因，练习要有提示和有步骤的解答。
4. 例题来源只能使用 [真题·年份]、[老师题库]、[老师课件]、[作业原题]、[教材例题]、[改编题]、[必要补充]；无法证明来源时不得标真题。
5. 表格用于考情速览（4列表格：考点 / 题型、重要程度、预计分值、常见题型）或紧凑的对比总结；避免五列以上的宽表格。用短段落和清楚的编号步骤，避免多层嵌套列表与空泛总结。标题不要手写章内小节编号，以免 PDF 重复编号。
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


class GlobalPrompts(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    introduction: IntroductionPrompt


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

