from pathlib import Path

from modules.latex_renderer import render_markdown_to_latex, write_latex_document


def test_render_markdown_preserves_math_and_removes_obsidian_syntax() -> None:
    source = """# 核心知识

重点是 **高斯定律**，见 [[公式总结]]。

$$\\nabla \\cdot \\mathbf{E}=\\frac{\\rho}{\\varepsilon_0}$$

- 先判断对称性
- 再选择高斯面
"""

    rendered = render_markdown_to_latex(source)

    assert "\\section{核心知识}" in rendered
    assert "\\textbf{高斯定律}" in rendered
    assert "公式总结" in rendered
    assert "[[" not in rendered
    assert "\\nabla \\cdot" in rendered
    assert "\\begin{itemize}" in rendered


def test_write_latex_document_uses_chinese_document_template(tmp_path: Path) -> None:
    path = write_latex_document(
        "# 复习\n\n内容",
        tmp_path / "main.tex",
        "电磁场考前三天冲刺讲义",
        subtitle="面向基础薄弱学生",
        style={"primary_color": "123456", "warning_color": "AA0000"},
    )

    text = path.read_text(encoding="utf-8")
    assert "\\documentclass" in text
    assert "ctexart" in text
    assert "\\begin{document}" in text
    assert "\\title{电磁场考前三天冲刺讲义}" in text
    assert "面向基础薄弱学生" in text
    assert "\\definecolor{primary}{HTML}{123456}" in text
    assert "\\definecolor{warning}{HTML}{AA0000}" in text
    assert "\\usepackage{fancyhdr}" in text
    assert "\\setlength{\\headheight}{15pt}" in text
    assert "\\fancyfoot[C]{\\thepage}" in text
    assert "\\section{复习}" in text


def test_write_latex_document_supports_academic_layout(tmp_path: Path) -> None:
    path = write_latex_document(
        "# 复习\n\n正文",
        tmp_path / "academic.tex",
        "数学分析讲义",
        style={"layout": "academic"},
    )

    text = path.read_text(encoding="utf-8")
    assert "\\setlength{\\parskip}{0.35em}" in text
    assert "colback=white" in text
    assert "colframe=black!35" in text


def test_render_markdown_converts_table_to_longtable(tmp_path: Path) -> None:
    rendered = render_markdown_to_latex("| 题型 | 频率 |\n| --- | --- |\n| 镜像法 | 高 |")

    assert "\\begin{longtable}" in rendered
    assert "镜像法" in rendered
    assert "\\hline" in rendered


def test_render_markdown_uses_inline_math_inside_tables() -> None:
    rendered = render_markdown_to_latex("| 公式 |\n| --- |\n| $$E=mc^2$$ |")

    assert "\\(E=mc^2\\)" in rendered
    assert "\\[E=mc^2\\]" not in rendered


def test_render_markdown_keeps_pipes_inside_math_table_cells() -> None:
    rendered = render_markdown_to_latex("| 题目 | 结论 |\n| --- | --- |\n| $|x-1|$ | 分段计算 |")

    assert "|x-1|" in rendered
    assert rendered.count(" & ") == 2


def test_render_markdown_drops_frontmatter_and_renders_callouts() -> None:
    source = "---\ncourse: 电磁场\ntags:\n- 复习\n---\n\n> 来源：知识结构.md\n\n正文"

    rendered = render_markdown_to_latex(source)

    assert "course:" not in rendered
    assert "来源：知识结构.md" in rendered
    assert "\\textit{来源：知识结构.md}" in rendered


def test_render_markdown_normalizes_escaped_math_delimiters() -> None:
    rendered = render_markdown_to_latex(r"行内 \$E=mc^2\$，块公式：\$$\nabla^2 u=0\$$")

    assert "\\(E=mc^2\\)" in rendered
    assert "\\[\\nabla^2 u=0\\]" in rendered
    assert r"\textbackslash{}" not in rendered


def test_render_markdown_handles_multiline_display_math() -> None:
    source = "\\$$\\vec{E} =\n\\begin{cases}\n\\frac{1}{r^2}, & r > 0\n\\end{cases}\\$$"

    rendered = render_markdown_to_latex(source)

    assert "\\[\\vec{E} =" in rendered
    assert "\\begin{cases}" in rendered
    assert r"\textbackslash{}" not in rendered


def test_render_markdown_wraps_fenced_code_as_verbatim() -> None:
    rendered = render_markdown_to_latex("```\n[1] ---> [2]\n```")

    assert "\\begin{verbatim}" in rendered
    assert "[1] ---> [2]" in rendered
    assert "\\end{verbatim}" in rendered


def test_render_markdown_makes_unicode_diagrams_latex_safe() -> None:
    source = """```text
[考前路径] ── 重点复习
⚠️ 不要漏写条件
```"""

    rendered = render_markdown_to_latex(source)

    assert "\\begin{quote}" in rendered
    assert "考前路径" in rendered
    assert "⚠️" not in rendered
    assert "──" not in rendered


def test_render_markdown_downgrades_unclosed_display_math() -> None:
    rendered = render_markdown_to_latex("结果为 $$x+1，后面仍是中文说明。")

    assert "$$" not in rendered
    assert "中文说明" in rendered


def test_render_markdown_escapes_special_heading_symbols() -> None:
    rendered = render_markdown_to_latex("# __(1^_infty__)型极限 📅")

    assert "\\^{}" in rendered
    assert "📅" not in rendered


def test_render_markdown_converts_page_break_marker() -> None:
    rendered = render_markdown_to_latex("上一章\n\n<!-- PAGE_BREAK -->\n\n下一章")

    assert "\\clearpage" in rendered
    assert "PAGE_BREAK" not in rendered


def test_render_markdown_converts_semantic_callouts() -> None:
    source = """> [!IMPORTANT] 必须掌握
> 这是核心结论 $E=mc^2$。

> [!TIP] 解题提示
> 先判断条件。

> [!WARNING] 易错
> 不要漏单位。

> [!CHECK] 30 秒自测
> 你能复述步骤吗？
"""

    rendered = render_markdown_to_latex(source)

    assert "\\begin{importantbox}[title={必须掌握}]" in rendered
    assert "\\begin{tipbox}[title={解题提示}]" in rendered
    assert "\\begin{warningbox}[title={易错}]" in rendered
    assert "\\begin{checkbox}[title={30 秒自测}]" in rendered
    assert "\\(E=mc^2\\)" in rendered


def test_render_markdown_converts_collapsible_answer_markup() -> None:
    rendered = render_markdown_to_latex(
        "<details>\n<summary>点击查看答案</summary>\n\n答案内容\n\n</details>"
    )

    assert "<details>" not in rendered
    assert "<summary>" not in rendered
    assert "\\textbf{点击查看答案}" in rendered
    assert "答案内容" in rendered


def test_render_markdown_converts_parenthesized_italics() -> None:
    rendered = render_markdown_to_latex("*(这是补充说明)*")

    assert "\\textit{这是补充说明}" in rendered


def test_render_markdown_converts_spaced_asterisk_italics() -> None:
    rendered = render_markdown_to_latex("说明：* 为什么这样做 *")

    assert "\\textit{为什么这样做}" in rendered


def test_render_markdown_converts_bare_asterisk_italics() -> None:
    rendered = render_markdown_to_latex("说明：*为什么这样做*")

    assert "\\textit{为什么这样做}" in rendered


def test_render_markdown_repairs_latex_operator_attached_to_chinese() -> None:
    rendered = render_markdown_to_latex(r"$$x_n \le \frac{a_n}{\max分母}$$")

    assert r"\max\text{分母}" in rendered
