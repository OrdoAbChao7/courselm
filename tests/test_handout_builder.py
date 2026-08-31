from pathlib import Path

import pytest

from modules.handout_builder import build_handout


def _write_sources(root: Path) -> None:
    md = root / "output" / "数学分析" / "md"
    (md / "chapters").mkdir(parents=True)
    (md / "appendix").mkdir()
    (md / "00-绪论.md").write_text("# 绪论", encoding="utf-8")
    (md / "chapters" / "02-极限.md").write_text("# 第2章 极限", encoding="utf-8")
    (md / "chapters" / "01-函数.md").write_text("# 第1章 函数", encoding="utf-8")
    for i, title in enumerate(["重要公式汇总", "典型题型索引", "考前复习提要"], 1):
        (md / "appendix" / f"{i:02d}-{title}.md").write_text(f"# {title}", encoding="utf-8")


def test_build_handout_follows_v2_dynamic_order(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    result = build_handout("数学分析", tmp_path / "output", courses_dir=tmp_path / "courses")
    assert result.missing_inputs == ()
    assert result.template.title_suffix == "期末复习讲义"
    manuscript = result.manuscript_path.read_text(encoding="utf-8")
    assert manuscript.index("绪论") < manuscript.index("函数") < manuscript.index("极限") < manuscript.index("重要公式汇总")
    assert manuscript.count("<!-- PAGE_BREAK -->") == 2
    assert manuscript.count("# 第1章 函数") == 1
    assert "# 第1章 函数" in manuscript
    assert not manuscript.startswith("# 数学分析")
    assert "# 绪论" in manuscript


def test_build_handout_strips_front_matter_before_source_heading(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    path = tmp_path / "output" / "数学分析" / "md" / "chapters" / "01-函数.md"
    path.write_text("---\ncourse: 数学分析\n---\n\n# 第1章 函数\n\n内容", encoding="utf-8")
    manuscript = build_handout("数学分析", tmp_path / "output", courses_dir=tmp_path / "courses").manuscript_path.read_text(encoding="utf-8")
    assert manuscript.count("# 第1章 函数") == 1


def test_build_handout_reports_missing_v2_source(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    (tmp_path / "output" / "数学分析" / "md" / "00-绪论.md").unlink()
    result = build_handout("数学分析", tmp_path / "output", courses_dir=tmp_path / "courses")
    assert result.missing_inputs == ("00-绪论.md",)


def test_build_handout_rejects_course_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="课程名"):
        build_handout("..\\outside", tmp_path / "output", courses_dir=tmp_path / "courses")
