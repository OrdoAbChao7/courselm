"""Prompt 配置加载层：读取并校验 config/prompts.yaml。

结构约定（与 prompts.yaml 头部注释一致）：
    fixed:                     # 阶段一固定 Prompt，依次执行
      - id / title / output_file / template
    dynamic:
      question_type_detail:    # 阶段二动态 Prompt
        title / output_subdir / template（含 {type_name} {type_list} 占位符）

校验规则（启动即失败，避免运行到一半才暴露配置错误）：
- fixed id 唯一且必含 question_type_summary（阶段二题型解析依赖它）
- question_type_summary.template 必含 {max_types} 占位符（数量上限注入）
- dynamic.question_type_detail.template 必含 {type_name} 与 {type_list}
- 其余固定模板不得使用 {type_name}/{type_list}/{max_types}（防错填）
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from modules.path_manager import app_dir

REQUIRED_FIXED_IDS = {"knowledge_structure", "question_type_summary", "formula_summary"}
DYNAMIC_KEY = "question_type_detail"
_ALLOWED_DYNAMIC_PLACEHOLDERS = {"{type_name}", "{type_list}"}

MARKDOWN_OUTPUT_RULES = """

Markdown 与公式输出规范：
1. 输出必须为标准 Markdown。
2. 行内公式使用 $...$，独立公式使用 $$...$$。
3. 所有公式必须使用标准 LaTeX。
4. 数学下标必须使用 _，例如 E_0、\\epsilon_r、\\mu_r、S_{av}、E_{xm}。
5. 禁止使用 \\_ 表示数学下标，禁止使用 * 代替 LaTeX 下标。
6. 禁止输出 HTML Entity 或 HTML 标签控制换行。
7. 不要在 $ 或 $$ 外添加多余反斜杠。
8. 输出应能够直接保存为 .md，并由 Obsidian MathJax 正常渲染。
9. 面向基础薄弱学生：术语首次出现必须解释，先人话后术语，先直觉后公式。
10. 重要结论使用 > [!IMPORTANT]，学习提示使用 > [!TIP]，易错警告使用 > [!WARNING]，自测使用 > [!CHECK]。
11. 使用短段落、清单、表格、决策树和对照结构，避免连续大段文字。
12. 只依据课程资料；资料不足时明确说明，不得伪造频率、分值、原题来源或事实。
""".strip()


class PromptConfigError(Exception):
    """Prompt 配置缺失、语法错误或校验失败。"""


class FixedPrompt(BaseModel):
    id: str
    title: str
    output_file: str = Field(min_length=1)  # 相对 output/<课程>/md/
    template: str = Field(min_length=1)


class DynamicPrompt(BaseModel):
    title: str
    output_subdir: str = Field(min_length=1)
    template: str = Field(min_length=1)


class PromptBook(BaseModel):
    fixed: list[FixedPrompt] = Field(min_length=1)
    dynamic: dict[str, DynamicPrompt]

    @field_validator("fixed")
    @classmethod
    def _check_ids(cls, v: list[FixedPrompt]) -> list[FixedPrompt]:
        ids = [p.id for p in v]
        if len(ids) != len(set(ids)):
            raise PromptConfigError(f"fixed prompt id 重复：{ids}")
        missing = REQUIRED_FIXED_IDS - set(ids)
        if missing:
            raise PromptConfigError(f"缺少必需的固定 Prompt：{sorted(missing)}")
        return v

    def fixed_by_id(self, prompt_id: str) -> FixedPrompt | None:
        return next((p for p in self.fixed if p.id == prompt_id), None)

    @property
    def question_type_detail(self) -> DynamicPrompt:
        try:
            return self.dynamic[DYNAMIC_KEY]
        except KeyError as e:
            raise PromptConfigError(f"缺少动态 Prompt：{DYNAMIC_KEY}") from e


def _validate_placeholders(book: PromptBook) -> None:
    """占位符使用规则校验。"""
    for p in book.fixed:
        if p.id == "question_type_summary":
            if "{max_types}" not in p.template:
                raise PromptConfigError(
                    "question_type_summary.template 必须包含 {max_types} 占位符"
                )
        elif any(ph in p.template for ph in ("{max_types}", "{type_name}", "{type_list}")):
            raise PromptConfigError(
                f"固定 Prompt「{p.id}」不应使用动态占位符（{{max_types}}/{{type_name}}/{{type_list}}）"
            )
    detail = book.question_type_detail
    for ph in _ALLOWED_DYNAMIC_PLACEHOLDERS:
        if ph not in detail.template:
            raise PromptConfigError(
                f"question_type_detail.template 缺少占位符 {ph}"
            )
    if "{max_types}" in detail.template:
        raise PromptConfigError("question_type_detail.template 不应使用 {max_types}")


def load_prompts(path: Path | None = None) -> PromptBook:
    """加载并校验 prompts.yaml；缺省为项目根下 config/prompts.yaml。"""
    if path is None:
        path = app_dir() / "config" / "prompts.yaml"
    path = Path(path)

    if not path.is_file():
        raise PromptConfigError(f"Prompt 配置文件不存在：{path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PromptConfigError(f"prompts.yaml YAML 语法错误：{e}") from e
    if not isinstance(raw, dict):
        raise PromptConfigError("prompts.yaml 顶层结构应为键值映射")

    try:
        book = PromptBook.model_validate(raw)
    except ValidationError as e:
        raise PromptConfigError(f"prompts.yaml 校验失败：{e}") from e
    _validate_placeholders(book)
    return book


def render_fixed(prompt: FixedPrompt, max_types: int) -> str:
    """渲染固定模板。question_type_summary 注入题型数量上限。"""
    if prompt.id == "question_type_summary":
        rendered = prompt.template.format(max_types=max_types)
    else:
        rendered = prompt.template
    return f"{rendered.rstrip()}\n\n{MARKDOWN_OUTPUT_RULES}"


def render_dynamic(prompt: DynamicPrompt, type_name: str, type_list: str) -> str:
    """渲染动态模板（{type_name} / {type_list} 填充）。"""
    rendered = prompt.template.format(type_name=type_name, type_list=type_list)
    return f"{rendered.rstrip()}\n\n{MARKDOWN_OUTPUT_RULES}"
