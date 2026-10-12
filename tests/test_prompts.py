from pathlib import Path

import pytest

from modules.prompts import PromptConfigError, load_prompts, render_chapter, render_introduction

ROOT = Path(__file__).parents[1]


def test_default_prompt_book_teaches_from_examples() -> None:
    book = load_prompts(ROOT / "config" / "prompts.yaml")
    assert book.schema_version == 3
    assert book.planning.course_outline.output_file == "outline.json"
    assert book.dynamic.chapter.output_subdir == "chapters"
    chapter = book.dynamic.chapter.template
    assert chapter.index("## 考情速览") < chapter.index("## 题型一")
    assert chapter.index("### 核心考点与速记口诀") < chapter.index("### 标准例题")
    assert chapter.index("### 标准例题") < chapter.index("### 避坑提醒") < chapter.index("### 自己试")
    assert "#### 解答" in chapter
    assert "## 课时过关练习" in chapter
    assert "为什么" in chapter and "不编造" in chapter


def test_renderers_fill_explicit_context() -> None:
    book = load_prompts(ROOT / "config" / "prompts.yaml")
    outline = '{"course_name":"数学分析","chapters":[]}'
    assert "课程结构分析" not in book.planning.course_outline.template or "JSON" in book.planning.course_outline.template
    assert "数学分析" in render_introduction(book.global_prompts.introduction, "数学分析", outline)
    chapter = render_chapter(book.dynamic.chapter, 2, "极限", "数列极限", outline)
    assert "第2章 极限" in chapter and "## 题型一" in chapter
    assert outline in chapter


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
