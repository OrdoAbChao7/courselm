from __future__ import annotations

from pathlib import Path

import pytest

from launcher import LauncherError, build_command, discover_courses, find_project_root


def test_find_project_root_from_dist_directory(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()

    assert find_project_root(dist) == tmp_path


def test_discover_courses_returns_sorted_directories_only(tmp_path: Path) -> None:
    courses = tmp_path / "courses"
    (courses / "电动力学").mkdir(parents=True)
    (courses / "数学").mkdir()
    (courses / "说明.txt").write_text("", encoding="utf-8")

    assert discover_courses(tmp_path) == ["数学", "电动力学"]


def test_build_command_uses_project_venv_python(tmp_path: Path) -> None:
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")

    assert build_command(tmp_path, "generate", "电动力学") == [
        str(python),
        "main.py",
        "generate",
        "电动力学",
    ]


def test_build_command_rejects_missing_python(tmp_path: Path) -> None:
    with pytest.raises(LauncherError, match=r"\.venv"):
        build_command(tmp_path, "login")


def test_launcher_is_declared_as_installed_module() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    assert "py-modules = [\"main\", \"launcher\"]" in text
