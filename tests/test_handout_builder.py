from pathlib import Path

import pytest

from modules.handout_builder import build_handout


def _write_sources(root: Path) -> None:
    md = root / "output" / "电磁场" / "md"
    (md / "题型").mkdir(parents=True)
    (md / "知识结构.md").write_text("# 知识结构\n\n章节依赖", encoding="utf-8")
    (md / "公式总结.md").write_text("# 公式总结\n\n$$E=mc^2$$", encoding="utf-8")
    (md / "题型" / "题型总结.md").write_text("# 题型总结\n\n镜像法", encoding="utf-8")
    (md / "题型" / "02-分离变量法.md").write_text("# 分离变量法\n\n步骤", encoding="utf-8")
    (md / "题型" / "01-镜像法.md").write_text("# 镜像法\n\n步骤", encoding="utf-8")


def test_build_handout_orders_core_sections_before_question_types(tmp_path: Path) -> None:
    _write_sources(tmp_path)

    result = build_handout("电磁场", tmp_path / "output")

    assert result.missing_inputs == ()
    manuscript = result.manuscript_path.read_text(encoding="utf-8")
    assert manuscript.index("知识结构") < manuscript.index("公式总结")
    assert manuscript.index("公式总结") < manuscript.index("题型总结")
    assert manuscript.index("镜像法") < manuscript.index("分离变量法")
    assert "来源：知识结构.md" in manuscript


def test_build_handout_reports_missing_sources_and_writes_partial_manuscript(tmp_path: Path) -> None:
    md = tmp_path / "output" / "电磁场" / "md"
    md.mkdir(parents=True)
    (md / "知识结构.md").write_text("# 知识结构", encoding="utf-8")

    result = build_handout("电磁场", tmp_path / "output")

    assert set(result.missing_inputs) == {"公式总结.md", "题型/题型总结.md"}
    assert "缺失输入" in result.manuscript_path.read_text(encoding="utf-8")


def test_build_handout_rejects_course_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="课程名"):
        build_handout("..\\outside", tmp_path / "output")
