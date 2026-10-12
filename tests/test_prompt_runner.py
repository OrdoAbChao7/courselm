from pathlib import Path

import pytest

from modules.config import AppConfig
from modules.file_manager import CourseFile, CourseManifest
from modules.notebooklm import UploadReport
from modules.prompt_runner import ChapterFormatError, OutlineParseError, PipelineResult, parse_course_outline, run_pipeline, validate_chapter_markdown
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
        if "你正在生成第" in question:
            import re
            chapter_number = re.search(r"你正在生成第(\d+)章", question).group(1)
            return (
                f"# 第{chapter_number}章 示例\n\n"
                f"## 考情速览\n"
                f"| 考点 / 题型 | 重要程度 | 预计分值 | 常见题型 |\n"
                f"| :--- | :--- | :--- | :--- |\n"
                f"| 1. 基础题型 | 必考 | 10分 | 大题 |\n\n"
                f"提分策略：掌握基础题型即可稳拿高分。\n\n"
                f"## 题型一：基础题\n"
                f"### 核心考点与速记口诀\n"
                f"- **速记口诀**：先看条件再代公式。\n"
                f"### 标准例题：基础题\n"
                f"题目。[必要补充]\n"
                f"### 跟着做\n"
                f"1. 第一步，因为条件成立。\n"
                f"### 避坑提醒\n"
                f"1. 识别题型。\n"
                f"### 自己试\n"
                f"练习。提示：先看条件。\n"
                f"#### 解答\n"
                f"第一步。\n"
                f"## 课时过关练习\n"
                f"练习。提示：回看题型一。\n"
                f"#### 解答\n"
                f"过关解答。"
            )
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
    result = run(run_pipeline(cfg, book, "数学分析", manifest, svc))

    assert result.outline_outcome and not result.outline_outcome.from_cache
    assert svc.uploaded_names == []
    assert (state.parent / "raw" / "v3" / "outline.json").is_file()


def test_pipeline_only_requests_core_content(tmp_path: Path) -> None:
    cfg, manifest, svc = make_cfg(tmp_path), make_manifest(tmp_path), FakeService()
    book = load_prompts(Path(__file__).parents[1] / "config" / "prompts.yaml")
    result = run(run_pipeline(cfg, book, "数学分析", manifest, svc))
    assert [o.title for o in result.chapter_outcomes] == ["函数", "极限"]
    assert len(svc.ask_calls) == 4


def test_chapter_validation_rejects_method_before_example() -> None:
    invalid = "# 第1章 函数\n## 本章路线\n路线。\n## 题型一：基础题\n### 先知道什么\n概念。\n### 从题归纳\n方法。\n### 标准例题：基础题\n题目。[必要补充]\n### 跟着做\n1. 解答。\n### 自己试\n提示：... 解答：...\n## 章末过关\n练习。"
    with pytest.raises(ChapterFormatError, match="顺序"):
        validate_chapter_markdown(invalid, 1)


def test_chapter_validation_rejects_missing_practice_solution() -> None:
    invalid = "# 第1章 函数\n## 本章路线\n路线。\n## 题型一：基础题\n### 先知道什么\n概念。\n### 标准例题：基础题\n题目。[必要补充]\n### 跟着做\n1. 解答。\n### 从题归纳\n方法。\n### 自己试\n练习。\n## 章末过关\n练习。"
    with pytest.raises(ChapterFormatError, match="提示.*解答"):
        validate_chapter_markdown(invalid, 1)


def test_chapter_validation_requires_separate_practice_solution() -> None:
    invalid = "# 第1章 函数\n## 本章路线\n路线。\n## 题型一：基础题\n### 先知道什么\n概念。\n### 标准例题：基础题\n题目。[必要补充]\n### 跟着做\n1. 解答。\n### 从题归纳\n方法。\n### 自己试\n练习。提示：先看条件。解答：第一步。\n## 章末过关\n练习。"
    with pytest.raises(ChapterFormatError, match="独立的解答标题"):
        validate_chapter_markdown(invalid, 1)


def test_chapter_validation_rejects_old_separate_knowledge_block() -> None:
    invalid = "# 第1章 函数\n## 核心知识\n定义。\n## 本章路线\n路线。\n## 题型一：基础题\n### 先知道什么\n概念。\n### 标准例题：基础题\n题目。[必要补充]\n### 跟着做\n1. 解答。\n### 从题归纳\n方法。\n### 自己试\n练习。提示：先看条件。\n#### 解答\n第一步。\n## 章末过关\n练习。"
    with pytest.raises(ChapterFormatError, match="二级标题"):
        validate_chapter_markdown(invalid, 1)


def test_chapter_validation_requires_example_source_label() -> None:
    invalid = "# 第1章 函数\n## 本章路线\n路线。\n## 题型一：基础题\n### 先知道什么\n概念。\n### 标准例题：基础题\n题目。\n### 跟着做\n1. 解答。\n### 从题归纳\n方法。\n### 自己试\n练习。提示：先看条件。\n#### 解答\n第一步。\n## 章末过关\n练习。"
    with pytest.raises(ChapterFormatError, match="来源标记"):
        validate_chapter_markdown(invalid, 1)


def test_chapter_validation_rejects_question_type_after_chapter_check() -> None:
    valid = "# 第1章 函数\n## 本章路线\n路线。\n## 题型一：基础题\n### 先知道什么\n概念。\n### 标准例题：基础题\n题目。[必要补充]\n### 跟着做\n1. 解答。\n### 从题归纳\n方法。\n### 自己试\n练习。提示：先看条件。\n#### 解答\n第一步。\n## 章末过关\n练习。"
    with pytest.raises(ChapterFormatError, match="顺序"):
        validate_chapter_markdown(valid + "\n## 题型二：额外题型\n", 1)


def test_chapter_validation_rejects_speculative_exam_priority() -> None:
    valid = "# 第1章 函数\n## 本章路线\n路线。\n## 题型一：基础题\n### 先知道什么\n概念。\n### 标准例题：基础题\n题目。[必要补充]\n### 跟着做\n1. 解答。\n### 从题归纳\n方法。\n### 自己试\n练习。提示：先看条件。\n#### 解答\n第一步。\n## 章末过关\n练习。"
    with pytest.raises(ChapterFormatError, match="未经证实"):
        validate_chapter_markdown(valid.replace("路线。", "这是基础得分盘 [推测]。"), 1)


def test_chapter_validation_accepts_authentic_cram_course_format() -> None:
    cram = """# 第1章 极限与连续

## 考情速览
| 考点 / 题型 | 重要程度 | 预计分值 | 常见题型 |
| :--- | :--- | :--- | :--- |
| 1. 函数与极限 | 必考 | 6~10分 | 选择、计算 |

提分策略：掌握洛必达与等价代换口诀，直接秒杀前两道计算大题。

## 题型一：未定式求极限
### 核心考点与速记口诀
- 公式：$\\lim_{x \\to 0} \\frac{\\sin x}{x} = 1$。
- **速记口诀**：等价代换抓乘除，加减泰勒防陷阱。

### 标准例题：0比0型极限
求极限 $\\lim_{x \\to 0} \\frac{\\tan x - x}{x^3}$。[真题·2023]

### 跟着做
1. 代入为 0/0 型。
2. 洛必达求导得结果 $\\frac{1}{3}$。

### 避坑提醒
加减法切忌直接替换等价无穷小。

### 自己试
练习题。提示：先判断类型。
#### 解答
分步解答与答案。

## 课时过关练习
综合题。提示：利用重要极限。
#### 解答
结果与回看题型一。
"""
    validate_chapter_markdown(cram, 1)

