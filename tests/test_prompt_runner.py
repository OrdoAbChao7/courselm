"""prompt_runner 单元测试：题型解析 + 两阶段编排（FakeService，不触网）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.config import AppConfig
from modules.file_manager import CourseFile, CourseManifest
from modules.notebooklm import NotebookLMOperationError, UploadReport
from modules.prompt_runner import (
    PipelineResult,
    PromptRunnerError,
    QuestionTypeParseError,
    parse_question_types,
    run_pipeline,
    sanitize_type_name,
)
from modules.prompts import DynamicPrompt, FixedPrompt, PromptBook

# ----------------------------------------------------------- 测试夹具

SUMMARY_TABLE = """
## 常考题型汇总

| 序号 | 题型名称 | 高频解法 |
| ---- | -------- | -------- |
| 1    | 镜像法   | 对称性分析 |
| 2    | 分离变量法 | 边界条件匹配 |
| 3    | 有限差分 | 网格剖分 |
"""


def make_book() -> PromptBook:
    return PromptBook(
        fixed=[
            FixedPrompt(id="knowledge_structure", title="知识结构",
                        output_file="知识结构.md", template="生成知识结构"),
            FixedPrompt(id="question_type_summary", title="题型总结",
                        output_file="题型/题型总结.md",
                        template="总结题型，不超过{max_types}类，末尾输出表格"),
            FixedPrompt(id="formula_summary", title="公式总结",
                        output_file="公式总结.md", template="整理公式"),
        ],
        dynamic={
            "question_type_detail": DynamicPrompt(
                title="题型详解", output_subdir="题型",
                template="全部题型：{type_list}。详解「{type_name}」",
            )
        },
    )


def make_cfg(tmp_path: Path, retry: int = 1, max_types: int = 12) -> AppConfig:
    return AppConfig(
        paths={"courses_dir": tmp_path / "courses", "output_dir": tmp_path / "output",
               "logs_dir": tmp_path / "logs"},
        obsidian={"vault_path": "", "course_folder": "课程"},
        notebooklm={"upload_wait_timeout": 60, "source_limit_warn": 50},
        network={"proxy": "none"},
        prompt_runner={"retry": retry, "max_question_types": max_types},
        markdown={"tags": ["大学课程", "复习"]},
        file_types=[".pdf"],
    )


def make_manifest(tmp_path: Path, names: list[str]) -> CourseManifest:
    root = tmp_path / "courses" / "电磁场"
    root.mkdir(parents=True, exist_ok=True)
    files = []
    for n in names:
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 10)
        files.append(CourseFile(path=p, size_bytes=10, category="pdf"))
    return CourseManifest(course_name="电磁场", root=root, files=files, total_size_bytes=10 * len(files))


class FakeService:
    """实现 NotebookLMService 编排所需接口的假服务。"""

    def __init__(self) -> None:
        self.notebook_id = "nb-1"
        self.ask_calls: list[str] = []
        self.uploaded_names: list[str] = []
        self.fail_patterns: list[str] = []  # 命中即抛网络类错误

    async def get_or_create_notebook(self, name: str) -> str:
        return self.notebook_id

    async def upload_sources(self, notebook_id: str, manifest: CourseManifest) -> UploadReport:
        names = [f.path.name for f in manifest.files]
        self.uploaded_names.extend(names)
        return UploadReport(uploaded=names)

    async def ask(self, notebook_id: str, question: str) -> str:
        self.ask_calls.append(question)
        if any(p in question for p in self.fail_patterns):
            raise NotebookLMOperationError("fake network boom")
        if "总结题型" in question:
            return SUMMARY_TABLE
        return f"## 关于「{question[:16]}」的回答\n\n详细内容。"


def run(coro):
    import asyncio

    return asyncio.run(coro)


# ----------------------------------------------------------- 题型解析

class TestSanitizeTypeName:
    def test_illegal_chars_replaced(self) -> None:
        assert sanitize_type_name('静电场:边值*问题"A"') == "静电场_边值_问题_A_"

    def test_strip_and_truncate(self) -> None:
        assert sanitize_type_name("  镜像法  ") == "镜像法"
        assert len(sanitize_type_name("超" * 100)) == 40

    def test_empty(self) -> None:
        assert sanitize_type_name("  ...  ") == ""


class TestParseQuestionTypes:
    def test_canonical_table(self) -> None:
        types = parse_question_types(SUMMARY_TABLE, max_types=12)
        assert types == ["镜像法", "分离变量法", "有限差分"]

    def test_generic_table_fallback(self) -> None:
        text = "| 1 | 电位函数计算 |\n| 2 | 电容求解 |\n| 3 | 电感求解 |"
        assert parse_question_types(text, max_types=12) == [
            "电位函数计算", "电容求解", "电感求解",
        ]

    def test_generic_table_without_ordinal_column(self) -> None:
        text = "| 镜像法 |\n| 分离变量法 |"  # 单列表格不匹配策略②（需≥2列）
        with pytest.raises(QuestionTypeParseError):
            parse_question_types(text, max_types=12)

    def test_numbered_fallback(self) -> None:
        text = "常考题型：\n一、镜像法\n二、分离变量法\n三、有限差分"
        assert parse_question_types(text, max_types=12) == [
            "镜像法", "分离变量法", "有限差分",
        ]

    def test_numbered_skips_sentences(self) -> None:
        text = "1. 这是一个很长的完整句子不应该被当作题型名称捕获"
        with pytest.raises(QuestionTypeParseError):
            parse_question_types(text, max_types=12)

    def test_dedupe_and_cap(self) -> None:
        text = "| 序号 | 题型名称 |\n|---|---|\n" + "\n".join(
            f"| {i} | 题型{i} |" for i in range(1, 21)
        ) + "\n| 21 | 题型1 |"  # 重复
        types = parse_question_types(text, max_types=5)
        assert types == ["题型1", "题型2", "题型3", "题型4", "题型5"]

    def test_bold_cells_cleaned(self) -> None:
        text = "| 序号 | 题型名称 |\n|---|---|\n| 1 | **镜像法** |\n| 2 | `分离变量法` |"
        assert parse_question_types(text, max_types=12) == ["镜像法", "分离变量法"]

    def test_unparseable_raises(self) -> None:
        with pytest.raises(QuestionTypeParseError, match="--prompts"):
            parse_question_types("完全没有结构的内容。", max_types=12)


# ----------------------------------------------------------- 编排

class TestRunPipeline:
    def test_full_run(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        svc = FakeService()
        manifest = make_manifest(tmp_path, ["教材.pdf"])

        result = run(run_pipeline(cfg, make_book(), "电磁场", manifest, svc))

        assert isinstance(result, PipelineResult)
        assert result.notebook_id == "nb-1"
        assert [o.key for o in result.fixed_outcomes] == [
            "knowledge_structure", "question_type_summary", "formula_summary",
        ]
        assert all(o.success and not o.from_cache for o in result.fixed_outcomes)
        assert result.question_types == ["镜像法", "分离变量法", "有限差分"]
        assert len(result.type_outcomes) == 3
        assert all(o.success for o in result.type_outcomes)
        assert result.failures == []
        # 3 固定 + 3 题型 = 6 次提问
        assert len(svc.ask_calls) == 6
        # raw 缓存文件落盘
        raw_dir = tmp_path / "output" / "电磁场" / "raw"
        assert (raw_dir / "knowledge_structure.md").is_file()
        assert (raw_dir / "题型_镜像法.md").is_file()

    def test_second_run_all_cache_hit_no_upload(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        svc = FakeService()
        manifest = make_manifest(tmp_path, ["教材.pdf"])
        run(run_pipeline(cfg, make_book(), "电磁场", manifest, svc))

        svc.ask_calls.clear()
        svc.uploaded_names.clear()
        result = run(run_pipeline(cfg, make_book(), "电磁场", manifest, svc))

        assert len(svc.ask_calls) == 0          # 全部缓存命中
        assert svc.uploaded_names == []          # 增量上传：无新文件
        assert all(o.from_cache for o in result.fixed_outcomes)
        assert all(o.from_cache for o in result.type_outcomes)
        assert len(result.type_outcomes) == 3

    def test_incremental_upload(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        svc = FakeService()
        run(run_pipeline(cfg, make_book(), "电磁场", make_manifest(tmp_path, ["教材.pdf"]), svc))

        svc.uploaded_names.clear()
        # 新增一份试卷再跑：只上传新文件
        run(run_pipeline(cfg, make_book(), "电磁场", make_manifest(tmp_path, ["教材.pdf", "试卷.pdf"]), svc))
        assert svc.uploaded_names == ["试卷.pdf"]

    def test_only_fixed_filter_skips_stage2(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        svc = FakeService()
        manifest = make_manifest(tmp_path, ["教材.pdf"])

        result = run(run_pipeline(
            cfg, make_book(), "电磁场", manifest, svc, only_fixed=["formula_summary"],
        ))

        assert [o.key for o in result.fixed_outcomes] == ["formula_summary"]
        assert result.type_outcomes == []
        assert result.question_types == []
        assert len(svc.ask_calls) == 1

    def test_fresh_ignores_cache(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        svc = FakeService()
        manifest = make_manifest(tmp_path, ["教材.pdf"])
        run(run_pipeline(cfg, make_book(), "电磁场", manifest, svc))

        svc.ask_calls.clear()
        svc.uploaded_names.clear()
        result = run(run_pipeline(cfg, make_book(), "电磁场", manifest, svc, fresh=True))

        assert len(svc.ask_calls) == 6  # 重新提问
        assert svc.uploaded_names == ["教材.pdf"]  # 重新上传
        assert all(not o.from_cache for o in result.fixed_outcomes)

    def test_retry_recovers_from_transient_error(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path, retry=2)
        svc = FakeService()
        # 第一次 ask（知识结构）抛错一次后恢复：通过 fail_once 队列模拟
        calls = {"n": 0}
        orig_ask = svc.ask

        async def flaky_ask(notebook_id, question):
            calls["n"] += 1
            if calls["n"] == 1:
                raise NotebookLMOperationError("transient")
            return await orig_ask(notebook_id, question)

        svc.ask = flaky_ask  # type: ignore[method-assign]
        manifest = make_manifest(tmp_path, ["教材.pdf"])

        result = run(run_pipeline(cfg, make_book(), "电磁场", manifest, svc))

        assert all(o.success for o in result.fixed_outcomes)

    def test_type_failure_does_not_abort_pipeline(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        svc = FakeService()
        svc.fail_patterns = ["详解「镜像法」"]  # 仅第一个题型失败
        manifest = make_manifest(tmp_path, ["教材.pdf"])

        result = run(run_pipeline(cfg, make_book(), "电磁场", manifest, svc))

        assert [o.title for o in result.failures] == ["镜像法"]
        assert [o.title for o in result.type_outcomes if o.success] == ["分离变量法", "有限差分"]

    def test_summary_missing_raises(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        svc = FakeService()
        svc.fail_patterns = ["总结题型"]  # 题型总结失败
        manifest = make_manifest(tmp_path, ["教材.pdf"])

        with pytest.raises(PromptRunnerError, match="question_type_summary"):
            run(run_pipeline(cfg, make_book(), "电磁场", manifest, svc))

    def test_state_json_persisted(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        svc = FakeService()
        manifest = make_manifest(tmp_path, ["教材.pdf"])
        run(run_pipeline(cfg, make_book(), "电磁场", manifest, svc))

        state_file = tmp_path / "output" / "电磁场" / "state.json"
        assert state_file.is_file()
        content = state_file.read_text(encoding="utf-8")
        assert "nb-1" in content
        assert "教材.pdf" in content

    @pytest.mark.anyio
    async def test_course_name_path_traversal(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        book = make_book()
        manifest = CourseManifest(
            course_name="电磁场",
            root=cfg.paths.courses_dir / "电磁场",
            files=[],
            total_size_bytes=0,
        )
        svc = FakeService()
        with pytest.raises(PromptRunnerError, match="非法的课程名称"):
            await run_pipeline(cfg, book, "../secret", manifest, svc)
