"""markdown_generator 单元测试：清洗、渲染、清单、落盘。"""

from __future__ import annotations

from pathlib import Path

import yaml

from modules.config import AppConfig
from modules.markdown_generator import (
    MarkdownDoc,
    clean_markdown,
    collect_docs,
    generate_all,
    render_doc,
)
from modules.prompt_runner import PipelineResult, PromptOutcome
from modules.prompts import DynamicPrompt, FixedPrompt, PromptBook

# ----------------------------------------------------------- 夹具

def make_book() -> PromptBook:
    return PromptBook(
        fixed=[
            FixedPrompt(id="knowledge_structure", title="知识结构",
                        output_file="知识结构.md", template="T"),
            FixedPrompt(id="question_type_summary", title="题型总结",
                        output_file="题型/题型总结.md", template="T"),
            FixedPrompt(id="formula_summary", title="公式总结",
                        output_file="公式总结.md", template="T"),
        ],
        dynamic={
            "question_type_detail": DynamicPrompt(
                title="题型详解", output_subdir="题型",
                template="T {type_name} {type_list}",
            )
        },
    )


def make_result() -> PipelineResult:
    """3 固定全成功 + 3 题型（镜像法失败）。"""
    return PipelineResult(
        notebook_id="nb-1",
        fixed_outcomes=[
            PromptOutcome(key="knowledge_structure", title="知识结构",
                          success=True, raw_file="knowledge_structure.md"),
            PromptOutcome(key="question_type_summary", title="题型总结",
                          success=True, raw_file="question_type_summary.md"),
            PromptOutcome(key="formula_summary", title="公式总结",
                          success=True, raw_file="formula_summary.md"),
        ],
        question_types=["镜像法", "分离变量法", "有限差分"],
        type_outcomes=[
            PromptOutcome(key="题型_镜像法", title="镜像法",
                          success=False, error="boom"),
            PromptOutcome(key="题型_分离变量法", title="分离变量法",
                          success=True, raw_file="题型_分离变量法.md"),
            PromptOutcome(key="题型_有限差分", title="有限差分",
                          success=True, from_cache=True, raw_file="题型_有限差分.md"),
        ],
    )


def make_cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        paths={"courses_dir": tmp_path / "courses", "output_dir": tmp_path / "output",
               "logs_dir": tmp_path / "logs"},
        obsidian={"vault_path": "", "course_folder": "课程"},
        notebooklm={"upload_wait_timeout": 60, "source_limit_warn": 50},
        network={"proxy": "none"},
        prompt_runner={"retry": 1, "max_question_types": 12},
        markdown={"tags": ["大学课程", "复习"]},
        file_types=[".pdf"],
    )


def seed_raw(tmp_path: Path) -> None:
    raw_dir = tmp_path / "output" / "电磁场" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    contents = {
        "knowledge_structure.md": "## 章节结构\n\n第1章 静电场。\n\n\n\n\n第2章 恒定磁场。",
        "question_type_summary.md": "| 序号 | 题型名称 |\n|---|---|\n| 1 | 镜像法 |",
        "formula_summary.md": "高斯定理 \\[\\oint D \\cdot dS = Q\\] 与 \\(E = Q/\\varepsilon\\)。",
        "题型_分离变量法.md": "### 解法\n拉普拉斯方程 \\[\\nabla^2 \\varphi = 0\\]。",
        "题型_有限差分.md": "网格剖分。",
    }
    for name, text in contents.items():
        (raw_dir / name).write_text(text, encoding="utf-8")


# ----------------------------------------------------------- clean_markdown

class TestCleanMarkdown:
    def test_inline_math(self) -> None:
        assert clean_markdown("电场 \\(E = Q/r^2\\) 定义") == "电场 $E = Q/r^2$ 定义"

    def test_display_math(self) -> None:
        assert clean_markdown("定理：\n\\[\\oint E \\cdot dS = Q/\\varepsilon\\]\n证毕") == (
            "定理：\n$$\\oint E \\cdot dS = Q/\\varepsilon$$\n证毕"
        )

    def test_multiline_display_math(self) -> None:
        out = clean_markdown("\\[\nE = mc^2\n\\]")
        assert out == "$$E = mc^2$$"

    def test_existing_delimiters_untouched(self) -> None:
        text = "已有 $x$ 与 $$y$$ 不变"
        assert clean_markdown(text) == text

    def test_code_block_protected(self) -> None:
        text = "前文 \\(a\\)\n\n```python\ncode = \"\\(x\\) 与 \\[y\\]\"\n\n\n\nprint(code)\n```\n后文 \\(b\\)"
        out = clean_markdown(text)
        assert '"\\(x\\) 与 \\[y\\]"' in out      # 代码内保持字面
        assert "$a$" in out and "$b$" in out      # 代码外正常转换
        assert "print(code)\n```" in out          # 代码内空行保留

    def test_tilde_fence_protected(self) -> None:
        text = "~~~\n\\(x\\)\n~~~\n\\(y\\)"
        out = clean_markdown(text)
        assert "\\(x\\)" in out and "$y$" in out

    def test_blank_line_compression(self) -> None:
        assert clean_markdown("A\n\n\n\n\nB") == "A\n\nB"

    def test_invisible_chars_removed(self) -> None:
        assert clean_markdown("零宽\u200b字符\ufeff清理") == "零宽字符清理"

    def test_crlf_normalized(self) -> None:
        assert clean_markdown("A\r\n\r\nB") == "A\n\nB"

    def test_strip_outer(self) -> None:
        assert clean_markdown("\n\n  内容  \n\n") == "内容"


# ----------------------------------------------------------- render_doc

class TestRenderDoc:
    def test_front_matter_fields(self) -> None:
        out = render_doc("正文", course_name="电磁场", doc_type="题型总结",
                         tags=["大学课程", "复习"])
        assert out.startswith("---\n")
        fm_text = out.split("---\n", 2)[1]
        meta = yaml.safe_load(fm_text)
        assert meta["course"] == "电磁场"
        assert meta["type"] == "题型总结"
        assert meta["tags"] == ["大学课程", "复习", "题型总结"]
        assert "created" in meta
        assert out.endswith("---\n\n正文\n")

    def test_extra_meta_merged(self) -> None:
        out = render_doc("正文", course_name="电磁场", doc_type="题型详解",
                         tags=["复习"], extra_meta={"type_name": "镜像法"})
        meta = yaml.safe_load(out.split("---\n", 2)[1])
        assert meta["type_name"] == "镜像法"

    def test_unsafe_tag_cleaned(self) -> None:
        out = render_doc("x", course_name="C", doc_type="A/B C",
                         tags=["带 空格"])
        meta = yaml.safe_load(out.split("---\n", 2)[1])
        assert " " not in "".join(meta["tags"])
        assert "/" not in "".join(meta["tags"])

    def test_body_cleaned(self) -> None:
        out = render_doc("公式 \\(x\\) 结尾", course_name="C", doc_type="T", tags=["t"])
        assert "$x$" in out and "\\(" not in out


# ----------------------------------------------------------- collect / generate

class TestCollectDocs:
    def test_fixed_and_dynamic_skips_failures(self) -> None:
        docs = collect_docs(make_book(), make_result())
        # 3 固定 + 2 题型（镜像法失败被跳过）
        assert [d.dest_rel for d in docs] == [
            "知识结构.md", "题型/题型总结.md", "公式总结.md",
            "题型/分离变量法.md", "题型/有限差分.md",
        ]
        detail = next(d for d in docs if d.title == "分离变量法")
        assert detail.doc_type == "题型详解"
        assert detail.extra_meta == {"type_name": "分离变量法"}

    def test_all_fixed_failed(self) -> None:
        result = PipelineResult(notebook_id="nb", fixed_outcomes=[
            PromptOutcome(key="knowledge_structure", title="知识结构",
                          success=False, error="x"),
        ])
        assert collect_docs(make_book(), result) == []


class TestGenerateAll:
    def test_complex_notebooklm_markdown_is_sanitized_before_write(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        raw_dir = tmp_path / "output" / "电动力学" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_text = (
            "波阻抗为：&#x20;$\\eta = \\frac{E\\_0}{120\\pi\\sqrt{\\epsilon\\_r\\mu\\_r}}$\n\n"
            "$$\nE\\_0 = E\\_{xm}\\hat{e}\\_x\n\\vec{S}\\_{av}\n$$\n\n"
            "**注意：** 中文说明与 [[Maxwell方程]]。"
        )
        (raw_dir / "formula_summary.md").write_text(raw_text, encoding="utf-8")

        result = PipelineResult(
            notebook_id="nb",
            fixed_outcomes=[
                PromptOutcome(
                    key="formula_summary",
                    title="公式总结",
                    success=True,
                    raw_file="formula_summary.md",
                )
            ],
        )
        written = generate_all(cfg, make_book(), "电动力学", result)
        output = written[0].read_text(encoding="utf-8")

        assert "&#x20;" not in output
        assert r"\epsilon_r" in output
        assert r"\mu_r" in output
        assert r"E_0" in output
        assert r"E_{xm}" in output
        assert r"\vec{S}_{av}" in output
        assert r"\hat{e}_x" in output
        assert "[[Maxwell方程]]" in output
        assert "**注意：**" in output

    def test_writes_files_and_layout(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        seed_raw(tmp_path)

        written = generate_all(cfg, make_book(), "电磁场", make_result())

        md_dir = tmp_path / "output" / "电磁场" / "md"
        assert len(written) == 5
        assert (md_dir / "知识结构.md").is_file()
        assert (md_dir / "题型" / "题型总结.md").is_file()
        assert (md_dir / "题型" / "分离变量法.md").is_file()
        # 失败的题型无文件
        assert not (md_dir / "题型" / "镜像法.md").exists()

        # 内容：front matter + 清洗后的正文
        text = (md_dir / "公式总结.md").read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "$$" in text and "$" in text          # 公式已转换
        assert "\\[" not in text and "\\(" not in text

        # 题型文档含 type_name
        text = (md_dir / "题型" / "分离变量法.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---\n", 2)[1])
        assert meta["type_name"] == "分离变量法"
        assert meta["course"] == "电磁场"

    def test_missing_raw_skipped_with_warning(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        seed_raw(tmp_path)
        # 删掉一个 raw 缓存（raw 文件名 = prompt id）
        (tmp_path / "output" / "电磁场" / "raw" / "formula_summary.md").unlink()

        written = generate_all(cfg, make_book(), "电磁场", make_result())
        assert len(written) == 4

    def test_regenerate_overwrites(self, tmp_path: Path) -> None:
        cfg = make_cfg(tmp_path)
        seed_raw(tmp_path)
        generate_all(cfg, make_book(), "电磁场", make_result())
        # 修改 raw 后重新生成 → 覆盖（raw 文件名 = prompt id）
        (tmp_path / "output" / "电磁场" / "raw" / "knowledge_structure.md").write_text(
            "新内容", encoding="utf-8")
        generate_all(cfg, make_book(), "电磁场", make_result())
        text = (tmp_path / "output" / "电磁场" / "md" / "知识结构.md").read_text(encoding="utf-8")
        assert text.endswith("新内容\n")
