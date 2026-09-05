"""Obsidian 同步模块：output/<课程>/md/ → Vault/<course_folder>/<课程>/。

策略：
- 直接覆盖同名文件（Obsidian 自带文件版本历史，无需增量比对）
- 保持子目录结构（题型/ 等目录原样复制）
- 前置校验 vault 路径存在性——绝不自动创建 Vault 根目录
  （防止 vault_path 配置写错位置时凭空建出目录树）
"""

from __future__ import annotations

import shutil
from pathlib import Path

from loguru import logger

from modules.config import AppConfig


class ObsidianSyncError(Exception):
    """Vault 同步失败。"""


def sync_course(cfg: AppConfig, course_name: str) -> list[Path]:
    """把课程成品文档同步到 Obsidian Vault，返回已写文件列表。

    Raises:
        ObsidianSyncError: vault_path 未配置或指向不存在的目录。
    """
    if not course_name or "/" in course_name or "\\" in course_name or course_name in (".", ".."):
        raise ObsidianSyncError(f"非法的课程名称：{course_name}")

    vault = cfg.require_vault()
    if not vault.is_dir():
        raise ObsidianSyncError(
            f"Obsidian Vault 目录不存在：{vault}\n"
            "请检查 config.yaml 中 obsidian.vault_path 是否指向你的 Vault 根目录"
        )

    src_dir = cfg.paths.output_dir / course_name / "md"
    if not src_dir.is_dir():
        logger.warning("成品文档目录不存在（先生成再同步）：{}", src_dir)
        return []

    dst_dir = vault / cfg.obsidian.course_folder / course_name
    dst_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for src in sorted(src_dir.rglob("*.md")):
        dest = dst_dir / src.relative_to(src_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)  # copy2 保留修改时间（Obsidian 排序友好）
        written.append(dest)

    logger.info("Obsidian 同步完成：{} 篇 → {}", len(written), dst_dir)
    return written
