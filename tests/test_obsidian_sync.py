"""obsidian_sync 单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.config import AppConfig, ConfigurationError
from modules.obsidian_sync import ObsidianSyncError, sync_course


def make_cfg(tmp_path: Path, vault: str) -> AppConfig:
    return AppConfig(
        paths={"courses_dir": tmp_path / "courses", "output_dir": tmp_path / "output",
               "logs_dir": tmp_path / "logs"},
        obsidian={"vault_path": vault, "course_folder": "课程"},
        notebooklm={"upload_wait_timeout": 60, "source_limit_warn": 50},
        network={"proxy": "none"},
        prompt_runner={"retry": 1, "max_question_types": 12},
        markdown={"tags": ["复习"]},
        file_types=[".pdf"],
    )


def seed_md(tmp_path: Path) -> Path:
    md_dir = tmp_path / "output" / "电磁场" / "md"
    (md_dir / "题型").mkdir(parents=True)
    (md_dir / "知识结构.md").write_text("---\ncourse: 电磁场\n---\n\nA", encoding="utf-8")
    (md_dir / "公式总结.md").write_text("---\ncourse: 电磁场\n---\n\nB", encoding="utf-8")
    (md_dir / "题型" / "题型总结.md").write_text("---\ncourse: 电磁场\n---\n\nC", encoding="utf-8")
    (md_dir / "题型" / "镜像法.md").write_text("---\ncourse: 电磁场\n---\n\nD", encoding="utf-8")
    return md_dir


class TestSyncCourse:
    def test_sync_copies_with_subdirs(self, tmp_path: Path) -> None:
        seed_md(tmp_path)
        vault = tmp_path / "MyVault"
        vault.mkdir()

        written = sync_course(make_cfg(tmp_path, str(vault)), "电磁场")

        course_dir = vault / "课程" / "电磁场"
        assert len(written) == 4
        assert (course_dir / "知识结构.md").is_file()
        assert (course_dir / "题型" / "题型总结.md").is_file()
        assert (course_dir / "题型" / "镜像法.md").is_file()
        content = (course_dir / "知识结构.md").read_text(encoding="utf-8")
        assert content.startswith("---\ncourse: 电磁场")

    def test_vault_not_configured_raises(self, tmp_path: Path) -> None:
        seed_md(tmp_path)
        with pytest.raises(ConfigurationError, match="vault_path"):
            sync_course(make_cfg(tmp_path, ""), "电磁场")

    def test_vault_missing_dir_raises(self, tmp_path: Path) -> None:
        seed_md(tmp_path)
        with pytest.raises(ObsidianSyncError, match="不存在"):
            sync_course(make_cfg(tmp_path, str(tmp_path / "不存在Vault")), "电磁场")

    def test_no_md_dir_returns_empty(self, tmp_path: Path) -> None:
        vault = tmp_path / "MyVault"
        vault.mkdir()
        assert sync_course(make_cfg(tmp_path, str(vault)), "没生成过的课") == []
        # 不应创建课程目录
        assert not (vault / "课程").exists()

    def test_resync_overwrites(self, tmp_path: Path) -> None:
        seed_md(tmp_path)
        vault = tmp_path / "MyVault"
        vault.mkdir()
        sync_course(make_cfg(tmp_path, str(vault)), "电磁场")

        # 更新源后重新同步 → 覆盖
        (tmp_path / "output" / "电磁场" / "md" / "知识结构.md").write_text(
            "---\ncourse: 电磁场\n---\n\n新内容", encoding="utf-8")
        sync_course(make_cfg(tmp_path, str(vault)), "电磁场")
        text = (vault / "课程" / "电磁场" / "知识结构.md").read_text(encoding="utf-8")
        assert text.endswith("新内容")

    def test_custom_course_folder(self, tmp_path: Path) -> None:
        seed_md(tmp_path)
        vault = tmp_path / "MyVault"
        vault.mkdir()
        cfg = make_cfg(tmp_path, str(vault))
        cfg.obsidian.course_folder = "大学课程"
        sync_course(cfg, "电磁场")
        assert (vault / "大学课程" / "电磁场" / "知识结构.md").is_file()

    def test_course_name_path_traversal(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path, str(tmp_path / "vault"))
        with pytest.raises(ObsidianSyncError, match="非法的课程名称"):
            sync_course(cfg, "../secret")
