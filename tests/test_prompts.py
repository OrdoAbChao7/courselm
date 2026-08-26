"""prompts 配置加载层单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.prompts import (
    PromptConfigError,
    PromptBook,
    load_prompts,
    render_dynamic,
    render_fixed,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_DEFAULT_OUTPUTS = {
    "study_guide": "00-使用说明.md",
    "three_day_plan": "01-考前三天学习规划.md",
    "exam_map": "02-考试地图.md",
    "prerequisite_rescue": "03-零基础补给站.md",
    "knowledge_structure": "04-一页知识骨架.md",
    "core_exam_points": "05-核心考点卡.md",
    "formula_summary": "06-公式工具箱.md",
    "question_type_summary": "07-题型识别地图.md",
    "mistake_diagnostics": "09-易错点诊断室.md",
    "minimal_training": "10-最小训练集.md",
    "final_cram_sheet": "11-考前速记.md",
    "comprehensive_self_test": "12-综合自测与补救路线.md",
}

VALID = """
fixed:
  - id: knowledge_structure
    title: 知识结构
    output_file: 知识结构.md
    template: 请生成知识结构，公式 $E=mc^2$，内链 [[概念]]。
  - id: question_type_summary
    title: 题型总结
    output_file: 题型/题型总结.md
    template: |
      总结题型，不超过 {max_types} 类。
      末尾输出表格：| 序号 | 题型名称 |
  - id: formula_summary
    title: 公式总结
    output_file: 公式总结.md
    template: 整理全部公式。
dynamic:
  question_type_detail:
    title: 题型详解
    output_subdir: 题型
    template: |
      全部题型：{type_list}。
      请针对「{type_name}」生成详解。
"""


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "prompts.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class TestLoadPrompts:
    def test_valid_config(self, tmp_path: Path) -> None:
        book = load_prompts(write(tmp_path, VALID))
        assert [p.id for p in book.fixed] == [
            "knowledge_structure", "question_type_summary", "formula_summary",
        ]
        assert book.question_type_detail.output_subdir == "题型"

    def test_real_project_config_loads(self) -> None:
        """真实 config/prompts.yaml 必须始终可加载（守护测试）。"""
        book = load_prompts(PROJECT_ROOT / "config" / "prompts.yaml")
        assert {p.id: p.output_file for p in book.fixed} == EXPECTED_DEFAULT_OUTPUTS
        assert book.question_type_detail.output_subdir == "08-高频题型精讲"

    def test_default_prompts_encode_three_day_teaching_contract(self) -> None:
        book = load_prompts(PROJECT_ROOT / "config" / "prompts.yaml")

        plan = render_fixed(book.fixed_by_id("three_day_plan"), max_types=12)
        points = render_fixed(book.fixed_by_id("core_exam_points"), max_types=12)
        mistakes = render_fixed(book.fixed_by_id("mistake_diagnostics"), max_types=12)
        detail = render_dynamic(
            book.question_type_detail, type_name="镜像法", type_list="镜像法、分离变量法",
        )

        assert all(label in plan for label in ("第一天", "第二天", "第三天", "完成标准"))
        assert all(label in points for label in ("一句话理解", "适用条件", "30 秒自测"))
        assert all(label in mistakes for label in ("错误原因", "检查方法", "回看章节"))
        assert all(label in detail for label in ("识别信号", "标准解题流程", "遮住答案"))

    def test_default_path_is_resolved_from_application_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "prompts.yaml").write_text(VALID, encoding="utf-8")
        monkeypatch.setattr("modules.prompts.app_dir", lambda: tmp_path)

        book = load_prompts()

        assert book.question_type_detail.output_subdir == "题型"

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(PromptConfigError, match="不存在"):
            load_prompts(tmp_path / "nope.yaml")

    def test_missing_required_id(self, tmp_path: Path) -> None:
        bad = VALID.replace("  - id: formula_summary", "  - id: something_else")
        with pytest.raises(PromptConfigError, match="formula_summary"):
            load_prompts(write(tmp_path, bad))

    def test_duplicate_ids(self, tmp_path: Path) -> None:
        bad = VALID.replace("  - id: formula_summary", "  - id: knowledge_structure")
        with pytest.raises(PromptConfigError, match="重复"):
            load_prompts(write(tmp_path, bad))

    def test_missing_max_types_placeholder(self, tmp_path: Path) -> None:
        bad = VALID.replace("不超过 {max_types} 类", "不超过 12 类")
        with pytest.raises(PromptConfigError, match=r"\{max_types\}"):
            load_prompts(write(tmp_path, bad))

    def test_fixed_using_dynamic_placeholder(self, tmp_path: Path) -> None:
        bad = VALID.replace("整理全部公式。", "针对 {type_name} 整理。")
        with pytest.raises(PromptConfigError, match="动态占位符"):
            load_prompts(write(tmp_path, bad))

    def test_dynamic_missing_type_list(self, tmp_path: Path) -> None:
        bad = VALID.replace("全部题型：{type_list}。", "见上文。")
        with pytest.raises(PromptConfigError, match=r"\{type_list\}"):
            load_prompts(write(tmp_path, bad))

    def test_dynamic_missing_entirely(self, tmp_path: Path) -> None:
        bad = VALID.split("dynamic:")[0]
        with pytest.raises(PromptConfigError, match="dynamic"):
            load_prompts(write(tmp_path, bad))


class TestRender:
    def test_render_fixed_summary_injects_max_types(self, tmp_path: Path) -> None:
        book = load_prompts(write(tmp_path, VALID))
        p = book.fixed_by_id("question_type_summary")
        assert "不超过 12 类" in render_fixed(p, max_types=12)

    def test_render_fixed_others_untouched(self, tmp_path: Path) -> None:
        book = load_prompts(write(tmp_path, VALID))
        p = book.fixed_by_id("knowledge_structure")
        rendered = render_fixed(p, max_types=12)
        assert rendered.startswith(p.template)
        assert "Markdown 与公式输出规范" in rendered

    def test_render_dynamic(self, tmp_path: Path) -> None:
        book = load_prompts(write(tmp_path, VALID))
        out = render_dynamic(
            book.question_type_detail, type_name="镜像法", type_list="镜像法、分离变量法",
        )
        assert "「镜像法」" in out
        assert "镜像法、分离变量法" in out

    def test_render_includes_common_markdown_output_rules(self, tmp_path: Path) -> None:
        book = load_prompts(write(tmp_path, VALID))
        fixed = render_fixed(book.fixed_by_id("formula_summary"), max_types=12)
        dynamic = render_dynamic(
            book.question_type_detail, type_name="镜像法", type_list="镜像法",
        )

        assert "行内公式使用 $...$" in fixed
        assert "禁止输出 HTML Entity" in fixed
        assert "数学下标必须使用 _" in dynamic
        assert "[!IMPORTANT]" in fixed
        assert "基础薄弱" in dynamic


class TestPromptBookHelpers:
    def test_fixed_by_id_hit_and_miss(self, tmp_path: Path) -> None:
        book: PromptBook = load_prompts(write(tmp_path, VALID))
        assert book.fixed_by_id("formula_summary") is not None
        assert book.fixed_by_id("nope") is None
