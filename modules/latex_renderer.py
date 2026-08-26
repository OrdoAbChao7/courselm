"""Small, dependency-free Markdown subset renderer for the handout PDF source."""

from __future__ import annotations

import re
from pathlib import Path


_MATH = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+\$)", re.DOTALL)
_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def _escape_text(text: str) -> str:
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
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    return text


def _inline(text: str) -> str:
    chunks: list[str] = []
    cursor = 0
    for match in _MATH.finditer(text):
        chunks.append(_escape_text(text[cursor : match.start()]))
        value = match.group(0)
        chunks.append(value[2:-2] if value.startswith("$$") else value[1:-1])
        cursor = match.end()
    chunks.append(_escape_text(text[cursor:]))
    return "".join(chunks)


def _table(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        rows.append(" & ".join(_inline(cell) for cell in cells) + r" \\")
    columns = max(1, len(rows[0].split(" & ")) if rows else 1)
    return "\\begin{tabular}{" + "|".join(["l"] * columns) + "}\n\\hline\n" + "\n\\hline\n".join(rows) + "\n\\end{tabular}"


def render_markdown_to_latex(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").splitlines()
    output: list[str] = []
    i = 0
    in_list = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
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
        if stripped.startswith("|") and i + 1 < len(lines) and "|" in lines[i + 1]:
            table_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            output.append(_table(table_lines))
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
        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            command = {1: "section", 2: "subsection", 3: "subsubsection"}[len(heading.group(1))]
            output.append(f"\\{command}{{{_inline(heading.group(2))}}}")
        elif stripped:
            output.append(_inline(stripped))
        else:
            output.append("")
        i += 1
    if in_list:
        output.append("\\end{itemize}")
    return "\n".join(output).strip() + "\n"


def write_latex_document(manuscript: str, destination: Path, title: str) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    body = render_markdown_to_latex(manuscript)
    document = (
        "\\documentclass[UTF8,a4paper,12pt]{ctexart}\n"
        "\\usepackage{amsmath,amssymb,booktabs,geometry}\n"
        "\\geometry{margin=2.2cm}\n"
        "\\setlength{\\parindent}{2em}\n"
        f"\\title{{{_escape_text(title + '期末复习讲义')}}}\n"
        "\\author{}\n\\date{}\n"
        "\\begin{document}\n\\maketitle\n\\tableofcontents\n\\newpage\n"
        f"{body}"
        "\\end{document}\n"
    )
    destination.write_text(document, encoding="utf-8")
    return destination
