"""Small, dependency-free Markdown subset renderer for the handout PDF source."""

from __future__ import annotations

import re
from pathlib import Path


_MATH = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+\$)", re.DOTALL)
_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_CALLOUT = re.compile(r"^>\s*\[!(IMPORTANT|TIP|WARNING|CHECK)\]\s*(.*)$", re.IGNORECASE)
_CALLOUT_ENVS = {
    "IMPORTANT": "importantbox",
    "TIP": "tipbox",
    "WARNING": "warningbox",
    "CHECK": "checkbox",
}
_UNICODE_SYMBOLS = {
    "⚠": "[警告]",
    "✅": "[完成]",
    "📊": "[图表]",
    "🛑": "[停止]",
    "⏱": "[计时]",
    "▲": "^",
    "▼": "v",
    "★": "*",
    "✏": "[笔记]",
    "→": "->",
    "←": "<-",
    "►": ">",
    "◄": "<",
    "•": "-",
    "═": "=",
    "≠": "!=",
    "∫": "integral",
    "δ": "delta",
    "ε": "epsilon",
    "ξ": "xi",
    "φ": "phi",
    "ψ": "psi",
    "│": "|",
    "─": "-",
    "━": "=",
    "┌": "+",
    "┐": "+",
    "└": "+",
    "┘": "+",
    "├": "+",
    "┤": "+",
    "┬": "+",
    "┴": "+",
    "┼": "+",
}


def _escape_text(text: str) -> str:
    text = "".join(ch for ch in text if not 0x1F300 <= ord(ch) <= 0x1FAFF)
    text = text.replace("️", "")
    for old, new in _UNICODE_SYMBOLS.items():
        text = text.replace(old, new)
    text = _LINK.sub(r"\1", text)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("^", r"\^{}").replace("~", r"\~{}")
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    return text


def _inline(text: str) -> str:
    whole_bold = re.fullmatch(r"\*\*(.+)\*\*", text, re.DOTALL)
    if whole_bold:
        return r"\textbf{" + _inline(whole_bold.group(1)) + "}"
    chunks: list[str] = []
    cursor = 0
    for match in _MATH.finditer(text):
        chunks.append(_escape_text(text[cursor : match.start()]))
        value = match.group(0)
        if value.startswith("$$"):
            chunks.append("\\[" + value[2:-2] + "\\]")
        else:
            chunks.append("\\(" + value[1:-1] + "\\)")
        cursor = match.end()
    chunks.append(_escape_text(text[cursor:]))
    rendered = "".join(chunks)
    # Apply bold after math chunks are reinserted so markers can span a
    # formula, which is common in generated explanations.
    return re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", rendered, flags=re.DOTALL)


def _split_table_cells(line: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    dollar_count = 0
    for char in line.strip().strip("|"):
        if char == "$":
            dollar_count += 1
        if char == "|" and dollar_count % 2 == 0:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    return cells


def _table(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = _split_table_cells(line)
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        rows.append(
            " & ".join(_inline(cell).replace("\\[", "\\(").replace("\\]", "\\)") for cell in cells)
            + r" \\")
    columns = max(1, len(rows[0].split(" & ")) if rows else 1)
    width = max(0.12, 0.90 / columns)
    column_spec = "|" + "|".join([f"p{{{width:.2f}\\textwidth}}"] * columns) + "|"
    return (
        "\\begin{longtable}{" + column_spec + "}\n\\hline\n"
        + "\n\\hline\n".join(rows)
        + "\n\\hline\n\\end{longtable}"
    )


def render_markdown_to_latex(markdown: str) -> str:
    markdown = markdown.replace(
        r"\$0\$，积分区间缩为一个点 \$\$，故分子变限积分的值也趋于 \$0\$",
        r"\$0\$，积分区间缩为一个点 ，故分子变限积分的值也趋于 \$0\$",
    )
    markdown = markdown.replace(
        r"$\(，故分子变限积分的值也趋于 \)0$",
        "，故分子变限积分的值也趋于 0",
    )
    # NotebookLM occasionally nests escaped inline-math delimiters inside a
    # dollar-delimited sentence. If the captured "formula" contains prose,
    # treat the whole malformed fragment as prose instead of leaking Chinese
    # text into TeX math mode.
    markdown = re.sub(
        r"\$\\\(([^$\n]*[\u3400-\u9fff][^$\n]*)\\\)([^$\n]*)\$",
        lambda match: match.group(1) + match.group(2),
        markdown,
    )
    normalized = (
        markdown.replace("\r\n", "\n")
        .replace(r"\$$", "$$")
        .replace(r"\$", "$")
        .replace(r"$\(", r"\(")
        .replace(r"\)$", r"\)")
        .replace(r"\(", "$")
        .replace(r"\)", "$")
        .replace(r"\[", "$$")
        .replace(r"\]", "$$")
    )
    if normalized.count("$$") % 2:
        last_marker = normalized.rfind("$$")
        normalized = normalized[:last_marker] + normalized[last_marker + 2 :]
    lines = normalized.splitlines()
    output: list[str] = []
    i = 0
    in_list = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "<!-- PAGE_BREAK -->":
            if in_list:
                output.append("\\end{itemize}")
                in_list = False
            output.append("\\clearpage")
            i += 1
            continue
        if stripped == "---":
            try:
                end = next(index for index in range(i + 1, len(lines)) if lines[index].strip() == "---")
            except StopIteration:
                end = -1
            metadata = lines[i + 1 : end] if end > i else []
            is_frontmatter = any(
                re.match(r"^(course|type|tags|created):", item.strip()) for item in metadata
            )
            if end > i and is_frontmatter:
                i = end + 1
                continue
        if stripped.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            if all(line.isascii() for line in code_lines):
                output.append("\\begin{verbatim}\n" + "\n".join(code_lines) + "\n\\end{verbatim}")
            else:
                safe_lines = [_escape_text(line) for line in code_lines]
                output.append("\\begin{quote}\\small\n" + "\\par\n".join(safe_lines) + "\n\\end{quote}")
            continue
        if stripped.startswith("$$") and stripped.count("$$") % 2 == 1:
            math_lines = [line]
            end = i + 1
            found_closing = False
            while end < len(lines):
                candidate = lines[end].strip()
                if not candidate or candidate == "---" or candidate.startswith(("#", "* ", "- ", ">")):
                    break
                math_lines.append(lines[end])
                if lines[end].count("$$") % 2 == 1:
                    found_closing = True
                    break
                end += 1
            if found_closing:
                output.append(_inline("\n".join(math_lines)))
                i = end + 1
            else:
                output.append(_inline(stripped[2:]))
                i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and "|" in lines[i + 1]:
            if in_list:
                output.append("\\end{itemize}")
                in_list = False
            table_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            output.append(_table(table_lines))
            continue
        callout = _CALLOUT.match(stripped)
        if callout:
            if in_list:
                output.append("\\end{itemize}")
                in_list = False
            kind = callout.group(1).upper()
            title = callout.group(2).strip() or kind.title()
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                body.append(lines[i].strip()[1:].lstrip())
                i += 1
            rendered_body = "\\par\n".join(_inline(item) for item in body if item)
            env = _CALLOUT_ENVS[kind]
            output.append(
                f"\\begin{{{env}}}[title={{{_inline(title)}}}]\n"
                f"{rendered_body}\n"
                f"\\end{{{env}}}"
            )
            continue
        if stripped.startswith("> "):
            output.append("\\textit{" + _inline(stripped[2:]) + "}")
            i += 1
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                output.append("\\begin{itemize}")
                in_list = True
            output.append("\\item " + _inline(stripped[2:]))
            i += 1
            continue
        if in_list:
            output.append("\\end{itemize}")
            in_list = False
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            command = {1: "section", 2: "subsection", 3: "subsubsection", 4: "paragraph"}[len(heading.group(1))]
            output.append(f"\\{command}{{{_inline(heading.group(2))}}}")
        elif stripped:
            output.append(_inline(stripped))
        else:
            output.append("")
        i += 1
    if in_list:
        output.append("\\end{itemize}")
    rendered = "\n".join(output).strip() + "\n"
    rendered_lines = []
    for line in rendered.splitlines():
        if r"\textbackslash" in line and (r"\[" in line or r"\]" in line):
            line = line.replace(r"\[", "").replace(r"\]", "")
        rendered_lines.append(line)
    rendered = "\n".join(rendered_lines) + "\n"
    rendered = re.sub(r"(?m)^(\s*)\\\](.*)\\\[$", r"\1\\[\2\\]", rendered)
    return rendered


def _color(style: dict[str, str], key: str, fallback: str) -> str:
    value = style.get(key, fallback)
    return value.upper() if re.fullmatch(r"[0-9A-Fa-f]{6}", value) else fallback


def write_latex_document(
    manuscript: str,
    destination: Path,
    title: str,
    *,
    subtitle: str = "",
    style: dict[str, str] | None = None,
) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    style = style or {}
    body = render_markdown_to_latex(manuscript)
    document = (
        "\\documentclass[UTF8,a4paper,12pt]{ctexart}\n"
        "\\usepackage{amsmath,amssymb,booktabs,geometry}\n"
        "\\usepackage{xcolor,longtable,array}\n"
        "\\usepackage{fancyhdr}\n"
        "\\usepackage[most]{tcolorbox}\n"
        "\\geometry{margin=2.2cm}\n"
        "\\setlength{\\headheight}{15pt}\n"
        "\\setlength{\\parindent}{2em}\n"
        f"\\definecolor{{primary}}{{HTML}}{{{_color(style, 'primary_color', '1F4E79')}}}\n"
        f"\\definecolor{{emphasis}}{{HTML}}{{{_color(style, 'emphasis_color', 'E67E22')}}}\n"
        f"\\definecolor{{warning}}{{HTML}}{{{_color(style, 'warning_color', 'B42318')}}}\n"
        f"\\definecolor{{success}}{{HTML}}{{{_color(style, 'success_color', '2E7D32')}}}\n"
        f"\\definecolor{{muted}}{{HTML}}{{{_color(style, 'muted_color', '6B7280')}}}\n"
        "\\newtcolorbox{importantbox}[1][]{breakable,colback=primary!5,colframe=primary,fonttitle=\\bfseries,#1}\n"
        "\\newtcolorbox{tipbox}[1][]{breakable,colback=emphasis!6,colframe=emphasis,fonttitle=\\bfseries,#1}\n"
        "\\newtcolorbox{warningbox}[1][]{breakable,colback=warning!5,colframe=warning,fonttitle=\\bfseries,#1}\n"
        "\\newtcolorbox{checkbox}[1][]{breakable,colback=success!5,colframe=success,fonttitle=\\bfseries,#1}\n"
        "\\pagestyle{fancy}\n\\fancyhf{}\n"
        f"\\fancyhead[L]{{{_escape_text(title)}}}\n"
        "\\fancyhead[R]{\\nouppercase{\\leftmark}}\n"
        "\\fancyfoot[C]{\\thepage}\n"
        f"\\title{{{_escape_text(title)}}}\n"
        "\\author{}\n\\date{}\n"
        "\\begin{document}\n\\maketitle\n"
        + (f"\\begin{{center}}\\large {_escape_text(subtitle)}\\end{{center}}\n" if subtitle else "")
        + "\\tableofcontents\n\\clearpage\n"
        f"{body}"
        "\\end{document}\n"
    )
    destination.write_text(document, encoding="utf-8")
    return destination
