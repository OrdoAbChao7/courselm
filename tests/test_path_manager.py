from __future__ import annotations

from pathlib import Path

from modules.path_manager import build_runtime_env, resolve_app_dir


def test_source_app_dir_uses_source_project_root(tmp_path: Path) -> None:
    source_file = tmp_path / "modules" / "path_manager.py"

    assert resolve_app_dir(source_file=source_file) == tmp_path


def test_runtime_env_preserves_project_login_location(tmp_path: Path) -> None:
    env = build_runtime_env(tmp_path, {"EXISTING": "1"})

    assert env["EXISTING"] == "1"
    assert env["NOTEBOOKLM_HOME"] == str(tmp_path / "user_data")
    assert (tmp_path / "user_data").is_dir()
