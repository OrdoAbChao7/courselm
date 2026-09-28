from pathlib import Path

import pytest

from modules.config import AppConfig
from modules.file_manager import CourseFile, CourseManifest
from modules.notebooklm import UploadReport
from modules.prompt_runner import OutlineParseError, PipelineResult, parse_course_outline, run_pipeline
from modules.prompts import load_prompts


def make_cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        paths={"courses_dir": tmp_path / "courses", "output_dir": tmp_path / "output", "logs_dir": tmp_path / "logs"},
        obsidian={"vault_path": "", "course_folder": "课程"},
        notebooklm={"upload_wait_timeout": 60, "source_limit_warn": 50},
        network={"proxy": "none"}, prompt_runner={"retry": 1, "max_question_types": 12},
        markdown={"tags": ["大学课程", "复习"]}, file_types=[".pdf"],
    )


def make_manifest(tmp_path: Path) -> CourseManifest:
    root = tmp_path / "courses" / "数学分析"
    root.mkdir(parents=True)
    path = root / "教材.pdf"
    path.write_bytes(b"pdf")
    return CourseManifest(course_name="数学分析", root=root, files=[CourseFile(path=path, size_bytes=3, category="pdf")], total_size_bytes=3)


class FakeService:
    def __init__(self) -> None:
        self.ask_calls: list[str] = []
        self.uploaded_names: list[str] = []
        self.fail_chapter: int | None = None

    async def get_or_create_notebook(self, name: str) -> str:
        return "nb-1"

    async def upload_sources(self, notebook_id: str, manifest: CourseManifest) -> UploadReport:
        self.uploaded_names.extend(f.path.name for f in manifest.files)
        return UploadReport(uploaded=[f.path.name for f in manifest.files])

    async def ask(self, notebook_id: str, question: str) -> str:
        self.ask_calls.append(question)
        if self.fail_chapter and f"第{self.fail_chapter}章" in question:
            raise RuntimeError("chapter failure")
        if "只输出一个 JSON" in question:
            return '{"course_name":"数学分析","chapters":[{"index":2,"title":"极限","topics":["数列极限"]},{"index":1,"title":"函数","topics":["连续性"]}]}'
        return "# 生成内容\n\n内容。"


def run(coro):
    import asyncio
    return asyncio.run(coro)


def test_outline_parser_handles_fence_duplicates_and_sorts() -> None:
    outline = parse_course_outline('前文\n```json\n{"course_name":"数学分析","chapters":[{"index":2,"title":"极限","topics":["数列极限"]},{"index":1,"title":"函数","topics":["连续性"]},{"index":2,"title":"重复","topics":["无穷小"]}]}\n```')
    assert [(c.index, c.title) for c in outline.chapters] == [(1, "函数"), (2, "极限")]


@pytest.mark.parametrize("payload", ['{"course_name":"数学分析","chapters":[]}', '{"course_name":"数学分析","chapters":[{"index":0,"title":"","topics":[]}]}', "没有 JSON"])
def test_outline_parser_rejects_invalid_payload(payload: str) -> None:
    with pytest.raises(OutlineParseError):
        parse_course_outline(payload)


def test_current_pipeline_is_cached_and_isolates_chapter_failure(tmp_path: Path) -> None:
    cfg, manifest, svc = make_cfg(tmp_path), make_manifest(tmp_path), FakeService()
    book = load_prompts(Path(__file__).parents[1] / "config" / "prompts.yaml")
    svc.fail_chapter = 2
    failed = run(run_pipeline(cfg, book, "数学分析", manifest, svc))
    assert failed.outline and len(failed.outline.chapters) == 2
    assert [o.title for o in failed.chapter_outcomes if not o.success] == ["极限"]
    assert (tmp_path / "output" / "数学分析" / "raw" / "v3" / "outline.json").is_file()
    svc.fail_chapter = None
    svc.ask_calls.clear()
    recovered = run(run_pipeline(cfg, book, "数学分析", manifest, svc))
    assert all(o.success for o in recovered.chapter_outcomes)
    assert sum("第2章" in q for q in svc.ask_calls) == 1


def test_new_generation_reuses_uploaded_sources_but_not_old_answers(tmp_path: Path) -> None:
    cfg, manifest, svc = make_cfg(tmp_path), make_manifest(tmp_path), FakeService()
    state = tmp_path / "output" / "数学分析" / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"generation_schema_version":2,"notebook_id":"nb-1","uploaded_files":["教材.pdf"]}', encoding="utf-8")
    old_raw = state.parent / "raw" / "v2"
    old_raw.mkdir(parents=True)
    (old_raw / "outline.json").write_text("old", encoding="utf-8")

    book = load_prompts(Path(__file__).parents[1] / "config" / "prompts.yaml")
    result = run(run_pipeline(cfg, book, "数学分析", manifest, svc, stage="outline"))

    assert result.outline_outcome and not result.outline_outcome.from_cache
    assert svc.uploaded_names == []
    assert (state.parent / "raw" / "v3" / "outline.json").is_file()


def test_stage_and_single_chapter(tmp_path: Path) -> None:
    cfg, manifest, svc = make_cfg(tmp_path), make_manifest(tmp_path), FakeService()
    book = load_prompts(Path(__file__).parents[1] / "config" / "prompts.yaml")
    result: PipelineResult = run(run_pipeline(cfg, book, "数学分析", manifest, svc, stage="outline"))
    assert result.outline and result.chapter_outcomes == []
    result = run(run_pipeline(cfg, book, "数学分析", manifest, svc, chapter=1))
    assert [o.title for o in result.chapter_outcomes] == ["函数"]
