from __future__ import annotations

from pathlib import Path

from modules.path_manager import build_runtime_env, resolve_app_dir


def test_source_app_dir_uses_source_project_root(tmp_path: Path) -> None:
    source_file = tmp_path / "modules" / "path_manager.py"

    assert resolve_app_dir(False, source_file=source_file) == tmp_path


def test_frozen_app_dir_uses_executable_directory(tmp_path: Path) -> None:
    executable = tmp_path / "dist" / "CourseLM.exe"

    assert resolve_app_dir(True, executable=executable) == tmp_path / "dist"


def test_runtime_env_uses_portable_user_data(tmp_path: Path) -> None:
    env = build_runtime_env(tmp_path, {"EXISTING": "1"})

    assert env["EXISTING"] == "1"
    assert env["NOTEBOOKLM_HOME"] == str(tmp_path / "user_data")
    assert (tmp_path / "user_data").is_dir()
