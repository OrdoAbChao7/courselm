"""A separate process for every run; calls existing CourseLM Python modules directly."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

from studio.engine import MODES, inventory, apply_mode, make_style_config


def atomic_json(path: Path, value: dict):
    from studio.workspace import write_json
    write_json(path, value)


class Progress:
    def __init__(self, job: Path):
        self.job = job
        self.state_file = job / "status.json"
        self.state = json.loads(self.state_file.read_text(encoding="utf-8"))

    def update(self, stage: str, percent: int, *, status: str = "running", detail: str = "", artifacts: dict | None = None):
        old_stage = self.state.get("stage")
        percent = max(int(self.state.get("percent", 0)), min(100, percent))
        self.state.update(status=status, stage=stage, percent=percent, detail=detail, updated_at=datetime.now().isoformat(timespec="seconds"))
        if artifacts is not None:
            self.state["artifacts"] = artifacts
        atomic_json(self.state_file, self.state)
        if status == 'failed':
            self.state['failed_stage'] = old_stage
            atomic_json(self.state_file, self.state)
        if old_stage != stage or detail:
            event = {"time": datetime.now().strftime("%H:%M:%S"), "stage": stage, "message": detail or stage}
            with (self.job / "events.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(event, ensure_ascii=False) + "\n")


async def observe_pipeline(raw_dir: Path, progress: Progress, finished: asyncio.Event):
    last = -1
    while not finished.is_set():
        outline_path = raw_dir / "outline.json"
        outline_count = 0
        chapter_count = 0
        if outline_path.exists():
            try:
                outline_count = len(json.loads(outline_path.read_text(encoding="utf-8")).get("chapters", []))
            except (OSError, ValueError):
                pass
        intro = int((raw_dir / "introduction.md").exists())
        chapters = len(list((raw_dir / "chapters").glob("*.md")))
        appendices = len(list((raw_dir / "appendices").glob("*.md")))
        total = 1 + 1 + max(1, outline_count)
        complete = int(outline_path.exists()) + intro + chapters + appendices
        percent = min(82, 18 + round(64 * complete / total))
        if complete != last:
            progress.state.update(chapters_done=chapters, chapters_total=outline_count)
            if intro:
                stage = f"逐章节生成（{chapters}/{outline_count}）"
            elif outline_count:
                stage = "绪论生成"
            else:
                stage = "NotebookLM 连接、上传与课程大纲生成"
            progress.update(stage, percent)
            last = complete
        try:
            await asyncio.wait_for(finished.wait(), timeout=0.8)
        except asyncio.TimeoutError:
            pass


async def run(job: Path, progress: Progress, *, resume=False):
    from modules.config import load_config
    from modules.file_manager import scan_course
    from modules.notebooklm import NotebookLMService
    from modules.prompts import load_prompts
    from modules.prompt_runner import run_pipeline
    from modules.markdown_generator import generate_all
    from modules.network import setup_proxy
    from modules.path_manager import build_runtime_env
    from studio.workspace import Workspace, confined
    from modules.prompts import GENERATION_SCHEMA_VERSION

    config = json.loads((job / "request.json").read_text(encoding="utf-8"))
    course_id = config["course_id"]
    progress.update("检查输入资料", 3, detail="扫描资料文件，准备工作目录")
    root = job.parents[2]
    manifest_input = inventory(root / 'courses' / course_id if resume else config["source_path"])
    cfg = load_config()
    workspace = Workspace(job.parents[2], job.name)
    workspace.check_tree()
    cfg.paths.courses_dir = workspace.root / 'courses'
    cfg.paths.output_dir = workspace.root / 'output'
    course_dir = cfg.paths.courses_dir / course_id
    if course_dir.exists() and not resume:
        raise RuntimeError("检测到重复的任务目录，拒绝覆盖")
    course_dir.mkdir(parents=True, exist_ok=resume)
    base = Path(manifest_input["base"])
    for item in ([] if resume else manifest_input["files"]):
        source = Path(item["source"])
        if not source.is_file() or source.is_symlink() or source.stat().st_size != item["size"]:
            raise RuntimeError("来源文件在扫描后发生变化，请重新创建任务")
        target = confined(course_dir, course_dir / item["relative"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    style = make_style_config(config["mode"], config["style"], config["title"], config["subtitle"], config.get("accent"))
    (course_dir / "handout.yaml").write_text(yaml.safe_dump(style, allow_unicode=True, sort_keys=False), encoding="utf-8")
    manifest = scan_course(cfg.paths.courses_dir, course_id, cfg.file_types, source_limit_warn=cfg.notebooklm.source_limit_warn)
    progress.update("准备生成任务", 12, detail=f"{manifest_input['count']} 份资料已导入隔离目录；讲义模式：{MODES[config['mode']]['name']}")

    try:
        progress.update("建立原始题图素材库", 14, detail="自动扫描并解析资料中的电路/物理/函数等原图素材...")
        workspace.scan_figures(check_idle=False)
    except Exception as exc:
        progress.update('原图候选扫描未完成', 14,
                        detail=f'本轮不自动选图；未绑定图片将在构建时省略。原因：{exc}')

    book = apply_mode(load_prompts(), config["mode"])
    os.environ.update(build_runtime_env())
    setup_proxy(cfg.network.proxy)
    progress.update("连接 NotebookLM 与上传资料", 18, detail="开始真实模型调用；首次运行请确保已登录 NotebookLM")
    raw_dir = cfg.paths.output_dir / course_id / "raw" / f"v{GENERATION_SCHEMA_VERSION}"
    watcher_done = asyncio.Event()
    watcher = asyncio.create_task(observe_pipeline(raw_dir, progress, watcher_done))
    try:
        async with NotebookLMService(upload_wait_timeout=cfg.notebooklm.upload_wait_timeout) as service:
            result = await run_pipeline(cfg, book, course_id, manifest, service, fresh=not resume,
                on_progress=lambda stage, detail: progress.update(stage, progress.state.get('percent', 18), detail=detail))
    finally:
        watcher_done.set()
        await watcher
    # Preserve successful drafts on partial failures and preserve edits on resume.
    progress.state.update(chapters_done=sum(o.success for o in result.chapter_outcomes),
                          chapters_total=len(result.outline.chapters) if result.outline else 0)
    preserved = {p: p.read_bytes() for p in (workspace.output / 'md').rglob('*.md')}
    try:
        written = generate_all(cfg, book, course_id, result)
    finally:
        from studio.workspace import atomic_write
        for path, content in preserved.items():
            atomic_write(path, content)
    if result.failures:
        errors = "; ".join(f"{o.title}: {o.error}" for o in result.failures)
        raise RuntimeError(f"模型生成未全部成功：{errors}")
    if not result.outline or not result.chapter_outcomes:
        raise RuntimeError("模型没有成功生成完整章节，拒绝发布不完整讲义")
    progress.update("整理 Markdown", 84, detail="课程内容生成完成，开始格式清洗与组装")
    if not written:
        raise RuntimeError("没有生成可用的 Markdown 文档")
    progress.update("附录题型索引与 Markdown 组装", 89, detail="题型索引从实际章节提取；不额外调用 AI 生成附录")
    workspace.update(generation_complete=True)
    workspace.build()
    return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--action", choices=['generate', 'resume', 'build'], default='generate')
    args = parser.parse_args()
    job = args.job.resolve()
    progress = Progress(job)
    try:
        if args.action == 'build':
            from studio.workspace import Workspace
            Workspace(job.parents[2], job.name).build()
        else:
            asyncio.run(run(job, progress, resume=args.action == 'resume'))
    except Exception as exc:
        if args.action != 'build':
            progress = Progress(job)
            progress.update("生成失败", progress.state.get("percent", 0), status="failed", detail=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
