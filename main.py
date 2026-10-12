"""CourseLM：登录、生成讲义、离线导出 PDF。"""

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
from modules.handout_template import HandoutTemplateError
from modules.logging_setup import setup_logging
from modules.path_manager import build_runtime_env

EXIT_OK = 0
EXIT_USAGE = 1      # 配置/参数错误
EXIT_RUNTIME = 2    # 运行时失败


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="courselm",
        description="课程资料 → NotebookLM → Markdown / PDF 复习讲义",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="登录 NotebookLM（浏览器交互，仅需一次）")

    p_gen = sub.add_parser("generate", help="生成课程结构驱动的期末复习讲义资料")
    p_gen.add_argument("course", help="课程名")
    p_gen.add_argument("--fresh", action="store_true", help="忽略缓存，强制重跑")
    p_gen.add_argument("--no-pdf", action="store_true", help="只生成 Markdown 和 LaTeX 源码，不编译 PDF")

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


def _export_pdf(cfg, course: str, result) -> int:
    if result.missing_inputs:
        logger.error("讲义输入不完整：{}", "、".join(result.missing_inputs))
        return EXIT_RUNTIME
    ok, log = compile_latex(result.tex_path)
    if not ok:
        result.tex_path.with_suffix(".log").write_text(log, encoding="utf-8")
        logger.error("LaTeX 编译失败：{}", log)
        return EXIT_RUNTIME
    release_dir = cfg.paths.output_dir / course / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    target = release_dir / f"{course}-期末复习讲义.pdf"
    shutil.copy2(result.tex_path.with_suffix(".pdf"), target)
    print(f"PDF 已导出：{target}")
    return EXIT_OK


def cmd_export_handout(args: argparse.Namespace) -> int:
    cfg = load_config()
    result = _build_handout_files(cfg, args.course)
    return _export_pdf(cfg, args.course, result)


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

    from modules.handout_template import HandoutTemplateError, load_handout_template

    try:
        load_handout_template(args.course, cfg.paths.courses_dir)
    except HandoutTemplateError as e:
        logger.error("讲义模板配置错误：{}", e)
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
                    fresh=args.fresh,
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
    status = EXIT_RUNTIME if result.failures else EXIT_OK
    # 失败阶段仍保存成功章节，但不能发布不完整的 PDF。
    if not result.failures:
        handout = _build_handout_files(cfg, args.course)
        print(f"讲义初稿已生成：{handout.manuscript_path}")
        print(f"LaTeX 源码已生成：{handout.tex_path}")
        if handout.missing_inputs:
            logger.error("讲义输入不完整：{}", "、".join(handout.missing_inputs))
            status = EXIT_RUNTIME
        elif not args.no_pdf:
            if shutil.which("xelatex"):
                status = _export_pdf(cfg, args.course, handout)
            else:
                print("未找到 xelatex，已保留 Markdown 和 LaTeX 源码。安装后运行 courselm export-handout " + args.course)

    synced = []
    if cfg.obsidian.vault_path.strip() and written:
        try:
            synced = sync_course(cfg, args.course, files=written)
        except (ObsidianSyncError, OSError) as e:
            logger.error("本地文档已保留，Obsidian 同步失败：{}", e)
            status = EXIT_RUNTIME

    # ---- 汇总 ----
    all_outcomes = result.all_outcomes
    ok = [o for o in all_outcomes if o.success]
    cached = [o for o in ok if o.from_cache]

    print(f"\n{'=' * 56}")
    print(f"课程「{args.course}」处理结果")
    print(f"  课程结构：识别 {len(result.outline.chapters) if result.outline else 0} 章")
    print(f"  绪论    ：{'完成' if result.introduction_outcome and result.introduction_outcome.success else '未完成'}")
    print(f"  章节    ：{sum(o.success for o in result.chapter_outcomes)}/{len(result.chapter_outcomes)} 完成")
    print(f"  缓存命中：{len(cached)}")
    print(f"  生成文档: {len(written)} 篇 → {cfg.paths.output_dir / args.course / 'md'}")
    print(f"  同步 Vault: {len(synced)} 篇")
    if result.failures:
        print(f"\n  失败明细:")
        for o in result.failures:
            print(f"    - {o.title}: {o.error}")
        print(f"\n  修复后重新运行同一命令即可续跑（缓存自动跳过已成功部分）")
    print(f"{'=' * 56}")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # 复用项目内的登录态。
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

    try:
        if args.command == "login":
            from modules.notebooklm import run_login
            return run_login(cfg.notebooklm.browser)
        if args.command == "generate":
            return cmd_generate(args)
        return cmd_export_handout(args)
    except (ConfigurationError, ValueError, HandoutTemplateError) as exc:
        logger.error("{}", exc)
        return EXIT_USAGE
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("处理失败：{}", exc)
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
