from __future__ import annotations

from io import StringIO

from loguru import logger

from modules.markdown_sanitizer import sanitize_markdown


def test_decodes_numeric_and_named_html_entities() -> None:
    assert sanitize_markdown("Hello&#x20;World &#x5FAA;&#x8FD9; &nbsp; &#12345;") == (
        "Hello World 循这   〹"
    )


def test_unescapes_latex_subscripts_only_inside_inline_math() -> None:
    text = r"普通 \_ 保留，公式：$\epsilon\_r=\mu\_r$"

    assert sanitize_markdown(text) == r"普通 \_ 保留，公式：$\epsilon_r=\mu_r$"


def test_unescapes_grouped_subscripts_in_display_math() -> None:
    text = r"$$\nv\_p = \frac{c}{\sqrt{\mu\_r\epsilon\_r}}\n$$".replace(r"\n", "\n")

    expected = r"$$\nv_p = \frac{c}{\sqrt{\mu_r\epsilon_r}}\n$$".replace(r"\n", "\n")
    assert sanitize_markdown(text) == expected


def test_preserves_markdown_and_code_fences() -> None:
    fence = chr(96) * 3
    text = f"**高频考点**\n\n*重要说明*\n\n[[Maxwell方程]]\n\nfile_name_test\n\n# 一级标题\n\n{fence}text\n$E\\_0$\n{fence}"

    assert sanitize_markdown(text) == text


def test_cleans_html_residue_and_extra_math_linebreak() -> None:
    text = r"<p>波阻抗：</p>&#x20;$\eta = \frac{\eta\_0}{\sqrt{\epsilon\_r}}\\$<br>结束"

    expected = r"波阻抗：\n$\eta = \frac{\eta_0}{\sqrt{\epsilon_r}}$\n结束".replace(r"\n", "\n")
    assert sanitize_markdown(text) == expected


def test_recovers_conservative_star_subscripts_inside_math() -> None:
    text = r"$E*0 + E*{xm} + \vec{S}*{av} + \frac{E*0}{120\pi}$"

    assert sanitize_markdown(text) == r"$E_0 + E_{xm} + \vec{S}_{av} + \frac{E_0}{120\pi}$"


def test_does_not_replace_ordinary_markdown_stars_or_ambiguous_math() -> None:
    text = r"*斜体* **粗体** 与 $a*b$"

    assert sanitize_markdown(text) == text


def test_warns_when_suspicious_patterns_remain() -> None:
    stream = StringIO()
    sink_id = logger.add(stream, level="WARNING")
    try:
        output = sanitize_markdown(r"可疑：\_、\*{x}、&#xZZ;")
    finally:
        logger.remove(sink_id)

    assert output
    assert "possible malformed LaTeX" in stream.getvalue()
