from pathlib import Path

import pytest

from modules.handout_builder import build_handout


FIXED_FILES = [
    "00-使用说明.md",
    "01-考前三天学习规划.md",
    "02-考试地图.md",
    "03-零基础补给站.md",
    "04-一页知识骨架.md",
    "05-核心考点卡.md",
    "06-公式工具箱.md",
    "07-题型识别地图.md",
    "09-易错点诊断室.md",
    "10-最小训练集.md",
    "11-考前速记.md",
    "12-综合自测与补救路线.md",
]


def _write_sources(root: Path) -> None:
    md = root / "output" / "电磁场" / "md"
    detail = md / "08-高频题型精讲"
    detail.mkdir(parents=True)
    for name in FIXED_FILES:
        (md / name).write_text(f"# {Path(name).stem}\n\n{name} 内容", encoding="utf-8")
    (detail / "02-分离变量法.md").write_text("# 分离变量法\n\n步骤", encoding="utf-8")
    (detail / "01-镜像法.md").write_text("# 镜像法\n\n步骤", encoding="utf-8")


def test_build_handout_follows_default_three_day_order(tmp_path: Path) -> None:
    _write_sources(tmp_path)

    result = build_handout(
        "电磁场", tmp_path / "output", courses_dir=tmp_path / "courses",
    )

    assert result.missing_inputs == ()
    assert result.template.title_suffix == "考前三天冲刺讲义"
    manuscript = result.manuscript_path.read_text(encoding="utf-8")
    expected = [
        "使用说明", "考前三天学习规划", "考试地图", "零基础补给站", "一页知识骨架",
        "核心考点卡", "公式工具箱", "题型识别地图", "高频题型精讲", "镜像法",
        "分离变量法", "易错点诊断室", "最小训练集", "考前速记", "综合自测与补救路线",
    ]
    positions = [manuscript.index(f"## {title}") for title in expected]
    assert positions == sorted(positions)
    assert manuscript.count("<!-- PAGE_BREAK -->") == 13
    assert "来源：00-使用说明.md" in manuscript


def test_build_handout_reports_only_missing_required_sources(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    missing_path = tmp_path / "output" / "电磁场" / "md" / "06-公式工具箱.md"
    missing_path.unlink()

    result = build_handout("电磁场", tmp_path / "output", courses_dir=tmp_path / "courses")

    assert result.missing_inputs == ("06-公式工具箱.md",)
    assert "缺失输入" in result.manuscript_path.read_text(encoding="utf-8")


def test_course_template_can_replace_default_directory(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    course = tmp_path / "courses" / "电磁场"
    course.mkdir(parents=True)
    (course / "handout.yaml").write_text(
        "title_suffix: 公式专项\nsections:\n  - id: formulas\n    title: 只看公式\n    source: 06-公式工具箱.md\n",
        encoding="utf-8",
    )

    result = build_handout("电磁场", tmp_path / "output", courses_dir=tmp_path / "courses")

    manuscript = result.manuscript_path.read_text(encoding="utf-8")
    assert result.template.title_suffix == "公式专项"
    assert "## 只看公式" in manuscript
    assert "## 考试地图" not in manuscript


def test_build_handout_rejects_course_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="课程名"):
        build_handout("..\\outside", tmp_path / "output", courses_dir=tmp_path / "courses")
