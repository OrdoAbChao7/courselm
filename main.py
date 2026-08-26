"""CourseLM Automation Pipeline — CLI 入口。

子命令：
    login    交互式登录 NotebookLM（一次即可）
    scan     扫描课程目录，列出识别到的资料清单
    generate 完整流水线（Step 3 后续里程碑实现）
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from loguru import logger

from modules.config import ConfigurationError, load_config
from modules.browser_check import chrome_available
from modules.logging_setup import setup_logging
from modules.path_manager import build_runtime_env

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
    cfg = load_config()

    # ---- 前置快速失败（触网之前完成全部本地校验） ----
    from modules.file_manager import CourseNotFoundError, NoCourseFilesError, scan_course
    from modules.prompts import PromptConfigError, load_prompts

    try:
        manifest = scan_course(
            cfg.paths.courses_dir,
            args.course,
            cfg.file_types,
            source_limit_warn=cfg.notebooklm.source_limit_warn,
        )
    except (CourseNotFoundError, NoCourseFilesError) as e:
        logger.error("{}", e)
        return EXIT_USAGE

    try:
        book = load_prompts()
    except PromptConfigError as e:
        logger.error("Prompt 配置错误：{}", e)
        return EXIT_USAGE

    try:
        cfg.require_vault()  # 提前校验，避免流水线跑完才发现没配
    except ConfigurationError as e:
        logger.error("{}", e)
        return EXIT_USAGE

    only_fixed: list[str] | None = None
    if args.prompts:
        only_fixed = [s.strip() for s in args.prompts.split(",") if s.strip()]
        known = {p.id for p in book.fixed}
        unknown = [pid for pid in only_fixed if pid not in known]
        if unknown:
            logger.error("未知的 Prompt id：{}（可选：{}）", unknown, sorted(known))
            return EXIT_USAGE

    # ---- 流水线 ----
    from modules.notebooklm import (
        NotebookLMAuthError,
        NotebookLMOperationError,
        NotebookLMService,
    )
    from modules.prompt_runner import PromptRunnerError, run_pipeline

    try:
        async def _pipeline():
            async with NotebookLMService(
                upload_wait_timeout=cfg.notebooklm.upload_wait_timeout,
            ) as svc:
                return await run_pipeline(
                    cfg, book, args.course, manifest, svc,
                    only_fixed=only_fixed, fresh=args.fresh,
                )

        result = asyncio.run(_pipeline())
    except NotebookLMAuthError as e:
        logger.error("{}", e)
        return EXIT_RUNTIME
    except (NotebookLMOperationError, PromptRunnerError) as e:
        logger.error("流水线失败：{}", e)
        return EXIT_RUNTIME

    # ---- 生成文档 + 同步 ----
    from modules.markdown_generator import generate_all
    from modules.obsidian_sync import ObsidianSyncError, sync_course

    written = generate_all(cfg, book, args.course, result)
    try:
        synced = sync_course(cfg, args.course)
    except ObsidianSyncError as e:
        logger.error("{}", e)
        return EXIT_RUNTIME

    # ---- 汇总 ----
    all_outcomes = (*result.fixed_outcomes, *result.type_outcomes)
    ok = [o for o in all_outcomes if o.success]
    cached = [o for o in ok if o.from_cache]

    print(f"\n{'=' * 56}")
    print(f"课程「{args.course}」处理完成")
    print(f"  Prompt  : {len(ok)}/{len(all_outcomes)} 成功（{len(cached)} 个缓存命中）")
    print(f"  题型    : {len(result.question_types)} 类" if result.question_types else "  题型    : 未解析（调试模式或总结失败）")
    print(f"  生成文档: {len(written)} 篇 → {cfg.paths.output_dir / args.course / 'md'}")
    print(f"  同步 Vault: {len(synced)} 篇")
    if result.failures:
        print(f"\n  失败明细:")
        for o in result.failures:
            print(f"    - {o.title}: {o.error}")
        print(f"\n  修复后重新运行同一命令即可续跑（缓存自动跳过已成功部分）")
    print(f"{'=' * 56}")
    return EXIT_OK if not result.failures else EXIT_RUNTIME


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # 必须在 NotebookLM 客户端初始化或登录子进程之前隔离 Portable 数据目录。
    os.environ.update(build_runtime_env())

    try:
        cfg = load_config()
        setup_logging(cfg.paths.logs_dir)
    except ConfigurationError as e:
        print(f"配置错误：{e}", file=sys.stderr)
        return EXIT_USAGE

    # 代理同步必须在任何网络操作（含 login 子进程）之前完成：
    # httpx 只读环境变量，不读 Windows 系统代理
    from modules.network import setup_proxy

    setup_proxy(cfg.network.proxy)

    if args.command in {"login", "generate"} and cfg.notebooklm.browser == "chrome":
        if not chrome_available():
            logger.error(
                "未检测到 Google Chrome。\n"
                "CourseLM 轻量版需要使用电脑上已安装的 Google Chrome "
                "访问 NotebookLM。\n"
                "请安装 Google Chrome 后重新启动 CourseLM。"
            )
            return EXIT_RUNTIME

    if args.command == "login":
        from modules.notebooklm import run_login

        return run_login(cfg.notebooklm.browser)
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "generate":
        return cmd_generate(args)
    parser.error(f"未知命令：{args.command}")
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
