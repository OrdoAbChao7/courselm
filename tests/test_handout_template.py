from pathlib import Path

import pytest

from modules.handout_template import HandoutTemplateError, load_handout_template


DEFAULT = """
version: 1
title_suffix: 考前三天冲刺讲义
subtitle: 面向基础薄弱学生
latex:
  primary_color: 1F4E79
  warning_color: B42318
sections:
  - id: study_guide
    title: 使用说明
    source: 00-使用说明.md
    required: true
    page_break: true
  - id: question_details
    title: 高频题型精讲
    glob: 08-高频题型精讲/*.md
    required: true
    page_break: true
"""


def _default(tmp_path: Path, text: str = DEFAULT) -> Path:
    path = tmp_path / "default.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_default_template(tmp_path: Path) -> None:
    template = load_handout_template("电磁场", tmp_path / "courses", _default(tmp_path))

    assert template.title_suffix == "考前三天冲刺讲义"
    assert [section.id for section in template.sections] == ["study_guide", "question_details"]
    assert template.latex["primary_color"] == "1F4E79"


def test_course_override_merges_title_and_latex(tmp_path: Path) -> None:
    course_dir = tmp_path / "courses" / "电磁场"
    course_dir.mkdir(parents=True)
    (course_dir / "handout.yaml").write_text(
        "title_suffix: 专项冲刺讲义\nlatex:\n  warning_color: FF0000\n",
        encoding="utf-8",
    )

    template = load_handout_template("电磁场", tmp_path / "courses", _default(tmp_path))

    assert template.title_suffix == "专项冲刺讲义"
    assert template.latex == {"primary_color": "1F4E79", "warning_color": "FF0000"}
    assert len(template.sections) == 2


def test_course_override_replaces_sections(tmp_path: Path) -> None:
    course_dir = tmp_path / "courses" / "电磁场"
    course_dir.mkdir(parents=True)
    (course_dir / "handout.yaml").write_text(
        "sections:\n  - id: only\n    title: 只保留速记\n    source: 11-考前速记.md\n",
        encoding="utf-8",
    )

    template = load_handout_template("电磁场", tmp_path / "courses", _default(tmp_path))

    assert [section.id for section in template.sections] == ["only"]
    assert template.sections[0].required is True


@pytest.mark.parametrize(
    "replacement, message",
    [
        ("id: study_guide", "重复"),
        ("source: 00-使用说明.md\n    glob: '*.md'", "source.*glob"),
        ("source: ../secret.md", "路径"),
    ],
)
def test_rejects_invalid_sections(tmp_path: Path, replacement: str, message: str) -> None:
    if replacement == "id: study_guide":
        bad = DEFAULT + "  - id: study_guide\n    title: 重复\n    source: x.md\n"
    else:
        bad = DEFAULT.replace("source: 00-使用说明.md", replacement)

    with pytest.raises(HandoutTemplateError, match=message):
        load_handout_template("电磁场", tmp_path / "courses", _default(tmp_path, bad))


def test_rejects_course_path_escape(tmp_path: Path) -> None:
    with pytest.raises(HandoutTemplateError, match="课程名"):
        load_handout_template("..\\outside", tmp_path / "courses", _default(tmp_path))
