from __future__ import annotations

from pathlib import Path

import pytest

from studio.engine import MODES, STYLES, apply_mode, inventory, make_style_config, safe_slug
from studio.worker import atomic_json


def test_course_name_sanitization():
    assert safe_slug("高等数学 A") == "高等数学-A"
    with pytest.raises(ValueError):
        safe_slug(" / . ")


def test_file_inventory_and_limits(tmp_path: Path):
    (tmp_path / "a.pdf").write_bytes(b"abcd")
    (tmp_path / "b.txt").write_text("not a source")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "slides.pptx").write_bytes(b"xxxxxx")
    result = inventory(tmp_path)
    assert result["count"] == 2
    assert result["total_bytes"] == 10
    assert [item["relative"] for item in result["files"]] == ["a.pdf", "nested/slides.pptx"]
    assert inventory(tmp_path / "a.pdf")["count"] == 1


def test_invalid_path_and_empty(tmp_path: Path):
    with pytest.raises(ValueError): inventory(tmp_path / "missing")
    with pytest.raises(ValueError): inventory(tmp_path)


def test_mode_profile_mutates_template_without_touching_original():
    from pydantic import BaseModel
    class Chapter(BaseModel):
        template: str = "原文 {chapter_index}"
    class Dynamic(BaseModel):
        chapter: Chapter = Chapter()
    class Intro(BaseModel):
        template: str = "课程 {course_name}"
    class Global(BaseModel):
        introduction: Intro = Intro()
        appendices: list[Intro] = [Intro()]
    class Book(BaseModel):
        dynamic: Dynamic = Dynamic()
        global_prompts: Global = Global()
        @property
        def appendices(self): return self.global_prompts.appendices
    book = Book()
    altered = apply_mode(book, "practice")
    assert altered.dynamic.chapter.template.startswith(book.dynamic.chapter.template)
    assert "题型突破" in altered.dynamic.chapter.template
    assert "题型突破" not in book.dynamic.chapter.template
    assert "题型突破" in altered.global_prompts.appendices[0].template


def test_style_changes_real_latex_options():
    assert set(MODES) == {"sprint", "comprehensive", "practice"}
    assert len(STYLES) == 4
    v = make_style_config("sprint", "academic", "期末宝典", "复习", "#1122ff")
    assert v["title_suffix"] == "期末宝典"
    assert v["subtitle"] == "复习"
    assert v["latex"]["primary_color"] == "1122FF"
    with pytest.raises(ValueError):make_style_config("sprint", "academic", "", "", "red")


def test_atomic_status(tmp_path: Path):
    target=tmp_path/"status.json"
    atomic_json(target,{"status":"running","percent":35})
    assert target.read_text(encoding="utf-8").find('"percent": 35')>=0
