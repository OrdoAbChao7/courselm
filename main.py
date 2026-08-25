"""CourseLM Automation Pipeline — CLI 入口。

子命令：
    login    交互式登录 NotebookLM（一次即可）
    scan     扫描课程目录，列出识别到的资料清单
    generate 完整流水线（Step 3 后续里程碑实现）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger

from modules.config import ConfigurationError, load_config
from modules.logging_setup import setup_logging

EXIT_OK = 0
EXIT_USAGE = 1      # 配置/参数错误
EXIT_RUNTIME = 2    # 运行时失败


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="courselm",
        description="课程资料 → NotebookLM → Obsidian 复习文档 自动化流水线",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="登录 NotebookLM（浏览器交互，仅需一次）")

    p_scan = sub.add_parser("scan", help="扫描课程目录，列出资料清单")
    p_scan.add_argument("course", help="课程名（courses/ 下的目录名）")

    p_gen = sub.add_parser("generate", help="完整流水线（开发中）")
    p_gen.add_argument("course", help="课程名")
    p_gen.add_argument("--fresh", action="store_true", help="忽略缓存，强制重跑")
    p_gen.add_argument("--prompts", default=None, help="只执行指定固定 Prompt（逗号分隔 id）")

    return parser


def cmd_scan(args: argparse.Namespace) -> int:
    cfg = load_config()
    from modules.file_manager import scan_course

    try:
        manifest = scan_course(
            cfg.paths.courses_dir,
            args.course,
            cfg.file_types,
            source_limit_warn=cfg.notebooklm.source_limit_warn,
        )
    except Exception as e:  # CourseNotFoundError / NoCourseFilesError
        logger.error("{}", e)
        return EXIT_USAGE

    print(f"\n课程「{args.course}」资料清单：")
    for f in manifest.files:
        print(f"  [{f.category:>5}] {f.size_bytes:>12,} B  {f.path.relative_to(manifest.root)}")
    print(f"\n共 {len(manifest.files)} 个文件，{manifest.total_size_bytes / 1024 / 1024:.1f} MB")
    return EXIT_OK


def cmd_generate(args: argparse.Namespace) -> int:
    logger.error("generate 命令尚未实现（当前进度：M2 已完成 NotebookLM 适配层）")
    return EXIT_USAGE


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = load_config()
        setup_logging(cfg.paths.logs_dir)
    except ConfigurationError as e:
        print(f"配置错误：{e}", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "login":
        from modules.notebooklm import run_login

        return run_login()
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "generate":
        return cmd_generate(args)
    parser.error(f"未知命令：{args.command}")
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
