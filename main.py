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
import re
import shutil
import subprocess
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

    p_gen = sub.add_parser("generate", help="生成课程结构驱动的期末复习讲义资料")
    p_gen.add_argument("course", help="课程名")
    p_gen.add_argument("--fresh", action="store_true", help="忽略缓存，强制重跑")
    p_gen.add_argument("--stage", choices=["outline", "introduction", "appendices"], default=None,
                       help="只运行指定阶段；章节可用 --chapter 单独运行")
    p_gen.add_argument("--chapter", type=int, default=None, help="只生成指定章节（从 1 开始）")

    p_handout = sub.add_parser("build-handout", help="从 Obsidian Markdown 生成讲义初稿和 LaTeX 源码")
    p_handout.add_argument("course", help="课程名")

    p_export = sub.add_parser("export-handout", help="编译讲义 LaTeX 并导出 PDF")
    p_export.add_argument("course", help="课程名")

    return parser


def compile_latex(tex_path: Path) -> tuple[bool, str]:
    """Compile a TeX document twice so the table of contents is resolved."""

    executable = shutil.which("xelatex")
    if not executable:
        return False, "未找到 xelatex，请安装 TeX Live 或 MiKTeX 并将其加入 PATH"
    pdf_path = tex_path.with_suffix(".pdf")
    # Never treat an old artifact as the result of a failed compilation.
    pdf_path.unlink(missing_ok=True)
    outputs: list[str] = []
    for _ in range(2):
        completed = subprocess.run(
            [executable, "-interaction=nonstopmode", tex_path.name],
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        outputs.append((completed.stdout or "") + (completed.stderr or ""))
        if completed.returncode != 0:
            # MiKTeX may return 1 for update-check/overfull-box diagnostics
            # even after writing a usable PDF. Accept only when the PDF
            # exists and the transcript contains no fatal TeX marker.
            diagnostic = outputs[-1]
            fatal = re.search(r"(?m)^!|Emergency stop|Fatal error", diagnostic)
            if not pdf_path_if_exists(tex_path) or fatal:
                return False, diagnostic[-4000:]
    if not pdf_path.is_file():
        return False, "xelatex 返回成功，但没有生成 PDF 文件"
    return True, "\n".join(outputs)[-4000:]


def pdf_path_if_exists(tex_path: Path) -> Path | None:
    """Return the generated PDF path only when it is already present."""
    path = tex_path.with_suffix(".pdf")
    return path if path.is_file() else None


def _build_handout_files(cfg, course: str):
    from modules.handout_builder import build_handout
    from modules.latex_renderer import write_latex_document

    result = build_handout(
        course,
        cfg.paths.output_dir,
        courses_dir=cfg.paths.courses_dir,
    )
    manuscript = result.manuscript_path.read_text(encoding="utf-8")
    write_latex_document(
        manuscript,
        result.tex_path,
        f"{course}{result.template.title_suffix}",
        subtitle=result.template.subtitle,
        style=result.template.latex,
    )
    return result


def cmd_build_handout(args: argparse.Namespace) -> int:
    cfg = load_config()
    try:
        result = _build_handout_files(cfg, args.course)
    except (OSError, ValueError) as e:
        logger.error("讲义生成失败：{}", e)
        return EXIT_USAGE
    print(f"讲义初稿已生成：{result.manuscript_path}")
    print(f"LaTeX 源码已生成：{result.tex_path}")
    if result.missing_inputs:
        print(f"缺失输入：{', '.join(result.missing_inputs)}")
        return EXIT_RUNTIME
    return EXIT_OK


def cmd_export_handout(args: argparse.Namespace) -> int:
    cfg = load_config()
    try:
        result = _build_handout_files(cfg, args.course)
    except (OSError, ValueError) as e:
        logger.error("讲义生成失败：{}", e)
        return EXIT_USAGE
    ok, log = compile_latex(result.tex_path)
    if not ok:
        result.tex_path.with_suffix(".log").write_text(log, encoding="utf-8")
        logger.error("LaTeX 编译失败：{}", log)
        return EXIT_RUNTIME
    release_dir = cfg.paths.output_dir / args.course / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = result.tex_path.with_suffix(".pdf")
    target = release_dir / f"{args.course}-期末复习讲义.pdf"
    shutil.copy2(pdf_path, target)
    print(f"PDF 已导出：{target}")
    return EXIT_OK


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
                    stage=args.stage, chapter=args.chapter, fresh=args.fresh,
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
    all_outcomes = result.all_outcomes
    ok = [o for o in all_outcomes if o.success]
    cached = [o for o in ok if o.from_cache]

    print(f"\n{'=' * 56}")
    print(f"课程「{args.course}」处理完成")
    print(f"  课程结构：识别 {len(result.outline.chapters) if result.outline else 0} 章")
    print(f"  绪论    ：{'完成' if result.introduction_outcome and result.introduction_outcome.success else '未完成'}")
    print(f"  章节    ：{sum(o.success for o in result.chapter_outcomes)}/{len(result.chapter_outcomes)} 完成")
    print(f"  附录    ：{sum(o.success for o in result.appendix_outcomes)}/3 完成")
    print(f"  缓存命中：{len(cached)}")
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
    if args.command == "build-handout":
        return cmd_build_handout(args)
    if args.command == "export-handout":
        return cmd_export_handout(args)
    parser.error(f"未知命令：{args.command}")
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
