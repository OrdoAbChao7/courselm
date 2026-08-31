from pathlib import Path

import pytest

from modules.prompts import PromptConfigError, load_prompts, render_appendix, render_chapter, render_introduction

ROOT = Path(__file__).parents[1]


def test_default_prompt_book_is_v2() -> None:
    book = load_prompts(ROOT / "config" / "prompts.yaml")
    assert book.schema_version == 2
    assert book.planning.course_outline.output_file == "outline.json"
    assert book.dynamic.chapter.output_subdir == "chapters"
    assert [p.id for p in book.appendices] == ["formula_appendix", "question_index", "final_review"]


def test_renderers_fill_explicit_context() -> None:
    book = load_prompts(ROOT / "config" / "prompts.yaml")
    outline = '{"course_name":"数学分析","chapters":[]}'
    assert "课程结构分析" not in book.planning.course_outline.template or "JSON" in book.planning.course_outline.template
    assert "数学分析" in render_introduction(book.global_prompts.introduction, "数学分析", outline)
    chapter = render_chapter(book.dynamic.chapter, 2, "极限", "数列极限", outline)
    assert "第2章 极限" in chapter and "2.1 核心知识" in chapter
    assert outline in render_appendix(book.appendices[0], outline)


def test_prompt_config_rejects_old_schema(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text("fixed: []\ndynamic: {}\n", encoding="utf-8")
    with pytest.raises(PromptConfigError):
        load_prompts(path)


def test_prompt_config_rejects_missing_chapter_placeholders(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text((ROOT / "config" / "prompts.yaml").read_text(encoding="utf-8").replace("{topics}", "主题"), encoding="utf-8")
    with pytest.raises(PromptConfigError, match="chapter"):
        load_prompts(path)
