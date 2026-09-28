"""v2 课程结构驱动讲义的行为契约。"""

from pathlib import Path

import pytest

from modules.prompt_runner import OutlineParseError, parse_course_outline
from modules.prompts import PromptConfigError, load_prompts, render_chapter


def test_outline_parser_accepts_json_fence_and_deduplicates() -> None:
    text = "分析结果如下：\n```json\n{" \
        "\"course_name\": \"数学分析\", \"chapters\": [" \
        "{\"index\": 2, \"title\": \"极限\", \"topics\": [\"数列极限\"]}," \
        "{\"index\": 1, \"title\": \"函数\", \"topics\": [\"连续性\"]}," \
        "{\"index\": 2, \"title\": \"极限（重复）\", \"topics\": [\"无穷小\"]}]" \
        "}\n```"

    outline = parse_course_outline(text)

    assert outline.course_name == "数学分析"
    assert [(chapter.index, chapter.title) for chapter in outline.chapters] == [
        (1, "函数"), (2, "极限")
    ]


def test_outline_parser_rejects_empty_or_invalid_chapters() -> None:
    with pytest.raises(OutlineParseError):
        parse_course_outline('{"course_name":"数学分析","chapters":[]}')
    with pytest.raises(OutlineParseError):
        parse_course_outline('{"course_name":"数学分析","chapters":[{"index":0,"title":""}]}')


def test_v2_prompt_config_has_outline_chapter_and_appendices() -> None:
    book = load_prompts(Path(__file__).parents[1] / "config" / "prompts.yaml")

    assert book.planning.course_outline.output_file == "outline.json"
    assert book.dynamic.chapter.output_subdir == "chapters"
    assert [item.id for item in book.global_prompts.appendices] == [
        "formula_appendix", "question_index", "final_review"
    ]
    rendered = render_chapter(book.dynamic.chapter, 2, "极限", "数列极限、函数极限")
    assert "第2章" in rendered and "## 题型一" in rendered
