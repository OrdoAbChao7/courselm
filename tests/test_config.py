"""config 加载层单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from modules.config import ConfigurationError, load_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VALID_CONFIG = """
paths:
  courses_dir: ./courses
  output_dir: ./output
  logs_dir: ./logs
obsidian:
  vault_path: 'D:/Obsidian/Vault'
  course_folder: 课程
notebooklm:
  upload_wait_timeout: 300
  source_limit_warn: 50
prompt_runner:
  retry: 1
  max_question_types: 12
file_types: [.pdf, .pptx]
markdown:
  tags: [大学课程, 复习]
"""


def write_config(tmp_path: Path, text: str) -> Path:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(exist_ok=True)
    p = cfg_dir / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class TestLoadConfig:
    def test_valid_config_relative_paths_resolved(self, tmp_path: Path) -> None:
        p = write_config(tmp_path, VALID_CONFIG)
        cfg = load_config(p)

        assert cfg.paths.courses_dir == (tmp_path / "courses").resolve()
        assert cfg.obsidian.vault_root == Path("D:/Obsidian/Vault")
        assert cfg.file_types == [".pdf", ".pptx"]

    def test_real_project_config_loads(self) -> None:
        """真实 config/config.yaml 必须始终可加载（用户改坏配置时本测试报警）。"""
        cfg = load_config(PROJECT_ROOT / "config" / "config.yaml")
        assert cfg.prompt_runner.max_question_types >= 1
        assert len(cfg.file_types) >= 5

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="不存在"):
            load_config(tmp_path / "nope" / "config.yaml")

    def test_yaml_syntax_error(self, tmp_path: Path) -> None:
        p = write_config(tmp_path, "paths: [unclosed")
        with pytest.raises(ConfigurationError, match="YAML"):
            load_config(p)

    def test_validation_error_timeout(self, tmp_path: Path) -> None:
        bad = yaml.safe_load(VALID_CONFIG)
        bad["notebooklm"]["upload_wait_timeout"] = -1
        p = write_config(tmp_path, yaml.safe_dump(bad, allow_unicode=True))
        with pytest.raises(ConfigurationError, match="校验失败"):
            load_config(p)

    def test_validation_error_file_types(self, tmp_path: Path) -> None:
        bad = yaml.safe_load(VALID_CONFIG)
        bad["file_types"] = ["PDF"]  # 缺少前导点且大写
        p = write_config(tmp_path, yaml.safe_dump(bad, allow_unicode=True))
        with pytest.raises(ConfigurationError, match="扩展名"):
            load_config(p)

    def test_empty_file_types(self, tmp_path: Path) -> None:
        bad = yaml.safe_load(VALID_CONFIG)
        bad["file_types"] = []
        p = write_config(tmp_path, yaml.safe_dump(bad, allow_unicode=True))
        with pytest.raises(ConfigurationError):
            load_config(p)

    def test_vault_path_may_be_empty_but_require_vault_raises(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(VALID_CONFIG)
        raw["obsidian"]["vault_path"] = ""
        p = write_config(tmp_path, yaml.safe_dump(raw, allow_unicode=True))
        cfg = load_config(p)  # 加载本身允许为空（scan/login 可用）

        with pytest.raises(ConfigurationError, match="vault_path"):
            cfg.require_vault()
