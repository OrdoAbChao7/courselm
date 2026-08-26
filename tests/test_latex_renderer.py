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
    path = write_latex_document("# 复习\n\n内容", tmp_path / "main.tex", "电磁场")

    text = path.read_text(encoding="utf-8")
    assert "\\documentclass" in text
    assert "ctexart" in text
    assert "\\begin{document}" in text
    assert "\\title{电磁场期末复习讲义}" in text
    assert "\\section{复习}" in text


def test_render_markdown_converts_table_to_tabular(tmp_path: Path) -> None:
    rendered = render_markdown_to_latex("| 题型 | 频率 |\n| --- | --- |\n| 镜像法 | 高 |")

    assert "\\begin{tabular}" in rendered
    assert "镜像法" in rendered
    assert "\\hline" in rendered


def test_render_markdown_uses_inline_math_inside_tables() -> None:
    rendered = render_markdown_to_latex("| 公式 |\n| --- |\n| $$E=mc^2$$ |")

    assert "\\(E=mc^2\\)" in rendered
    assert "\\[E=mc^2\\]" not in rendered


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
