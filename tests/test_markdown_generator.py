from pathlib import Path

import yaml

from modules.config import AppConfig
from modules.markdown_generator import clean_markdown, collect_docs, generate_all, render_doc
from modules.prompt_runner import CourseOutline, ChapterPlan, PipelineResult, PromptOutcome
from modules.prompts import load_prompts


def cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(paths={"courses_dir": tmp_path / "courses", "output_dir": tmp_path / "output", "logs_dir": tmp_path / "logs"}, obsidian={"vault_path":""}, notebooklm={"upload_wait_timeout":60,"source_limit_warn":50}, network={"proxy":"none"}, prompt_runner={"retry":1,"max_question_types":12}, markdown={"tags":["复习"]}, file_types=[".pdf"])


def result() -> PipelineResult:
    return PipelineResult(
        notebook_id="nb",
        outline=CourseOutline(course_name="数学分析", chapters=[ChapterPlan(index=1, title="函数", topics=["连续性"]), ChapterPlan(index=2, title="极限", topics=["数列极限"])]),
        outline_outcome=PromptOutcome(key="course_outline", title="课程结构分析", success=True, raw_file="outline.json"),
        introduction_outcome=PromptOutcome(key="introduction", title="绪论", success=True, raw_file="introduction.md"),
        chapter_outcomes=[PromptOutcome(key="chapter_01", title="函数", success=True, raw_file="chapters/01-函数.md"), PromptOutcome(key="chapter_02", title="极限", success=True, raw_file="chapters/02-极限.md")],
        appendix_outcomes=[PromptOutcome(key="formula_appendix", title="附录一 重要公式汇总", success=True, raw_file="appendices/formula_appendix.md"), PromptOutcome(key="question_index", title="附录二 典型题型索引", success=True, raw_file="appendices/question_index.md"), PromptOutcome(key="final_review", title="附录三 考前复习提要", success=True, raw_file="appendices/final_review.md")],
    )


def test_clean_markdown_converts_math_and_preserves_code() -> None:
    text = "定义 \\(x\\)\n\n```text\n\\(literal\\)\n```"
    out = clean_markdown(text)
    assert "$x$" in out and "\\(literal\\)" in out


def test_render_doc_has_safe_front_matter() -> None:
    out = render_doc("正文 \\(x\\)", "数学分析", "绪论", ["大学课程"])
    meta = yaml.safe_load(out.split("---\n", 2)[1])
    assert meta["course"] == "数学分析" and "$x$" in out


def test_collect_docs_has_required_v2_order() -> None:
    book = load_prompts(Path(__file__).parents[1] / "config" / "prompts.yaml")
    docs = collect_docs(book, result())
    assert [doc.dest_rel for doc in docs] == ["00-绪论.md", "chapters/01-函数.md", "chapters/02-极限.md", "appendix/01-重要公式汇总.md", "appendix/02-典型题型索引.md", "appendix/03-考前复习提要.md"]


def test_generate_all_writes_v2_tree(tmp_path: Path) -> None:
    book = load_prompts(Path(__file__).parents[1] / "config" / "prompts.yaml")
    raw = tmp_path / "output" / "数学分析" / "raw" / "v2"
    for rel in ["introduction.md", "chapters/01-函数.md", "chapters/02-极限.md", "appendices/formula_appendix.md", "appendices/question_index.md", "appendices/final_review.md"]:
        path = raw / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("内容 \\(x\\)", encoding="utf-8")
    written = generate_all(cfg(tmp_path), book, "数学分析", result())
    assert len(written) == 6
    assert (tmp_path / "output" / "数学分析" / "md" / "chapters" / "01-函数.md").is_file()
