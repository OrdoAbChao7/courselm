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
    "☆": "*",
    "✓": "[对]",
    "✗": "[错]",
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
    "①": "(1)",
    "②": "(2)",
    "③": "(3)",
    "④": "(4)",
    "⑤": "(5)",
    "⑥": "(6)",
    "⑦": "(7)",
    "⑧": "(8)",
    "⑨": "(9)",
    "⑩": "(10)",
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
        "$": r"\$",
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
    math_chunks: list[str] = []
    for idx, match in enumerate(_MATH.finditer(text)):
        chunks.append(_escape_text(text[cursor : match.start()]))
        value = match.group(0)
        if value.startswith("$$"):
            math_chunks.append("\\[" + value[2:-2] + "\\]")
        else:
            math_chunks.append("\\(" + value[1:-1] + "\\)")
        chunks.append(f"@@COURSELMMATH{idx}@@")
        cursor = match.end()
    chunks.append(_escape_text(text[cursor:]))
    rendered = "".join(chunks)
    # Apply bold and italics while math formulas are masked with placeholders,
    # preventing asterisks in formulas (e.g. complex conjugates like c_1^* & c_2^*)
    # from being mangled as markdown italics.
    rendered = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", rendered, flags=re.DOTALL)
    rendered = re.sub(r"\*\((.+?)\)\*", r"\\textit{\1}", rendered, flags=re.DOTALL)
    rendered = re.sub(r"\*\s+(.+?)\s+\*", r"\\textit{\1}", rendered, flags=re.DOTALL)
    rendered = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\\textit{\1}", rendered)
    for idx, math_val in enumerate(math_chunks):
        rendered = rendered.replace(f"@@COURSELMMATH{idx}@@", math_val)
    return re.sub(
        r"\[([^\]]+)\]\(\\#(example-\d+)\)",
        lambda match: rf"\hyperref[{match.group(2)}]{{{match.group(1)}}}",
        rendered,
    )


def _split_table_cells(line: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    dollar_count = 0
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    escaped = False
    for char in text:
        if char == "$" and not escaped:
            dollar_count += 1
        if char == "|" and dollar_count % 2 == 0 and not escaped:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    cells.append("".join(current).strip())
    return cells


def _is_table_separator(line: str) -> bool:
    cells = _split_table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", cell.replace(" ", "")) for cell in cells)


def _normalize_table_row(line: str, columns: int) -> list[str]:
    cells = _split_table_cells(line)
    if len(cells) < columns:
        cells.extend([""] * (columns - len(cells)))
    elif len(cells) > columns:
        cells = cells[: columns - 1] + [" | ".join(cells[columns - 1 :])]
    return cells


def _collect_table_lines(lines: list[str], start: int) -> tuple[list[str], int]:
    """Collect a table whose generated Markdown rows may contain hard wraps."""
    table_lines = [lines[start], lines[start + 1]]
    columns = len(_split_table_cells(lines[start]))
    current: str | None = None
    index = start + 2

    while index < len(lines):
        candidate = lines[index]
        stripped = candidate.strip()
        if not stripped:
            break
        if current is None:
            if not stripped.startswith("|"):
                break
            current = candidate
        elif len(_split_table_cells(current)) >= columns:
            table_lines.append(current)
            if not stripped.startswith("|"):
                break
            current = candidate
        else:
            current += " " + stripped
        if current is not None and len(_split_table_cells(current)) >= columns:
            table_lines.append(current)
            current = None
        index += 1

    if current is not None:
        table_lines.append(current)
    return table_lines, index


def _table(lines: list[str]) -> str:
    if not lines:
        return ""
    columns = max(1, len(_split_table_cells(lines[0])))
    body_lines = lines[2:] if len(lines) > 1 and _is_table_separator(lines[1]) else lines[1:]
    if columns >= 4:
        headers = _normalize_table_row(lines[0], columns)
        entries: list[str] = []
        for line in body_lines:
            if not line.strip():
                continue
            cells = _normalize_table_row(line, columns)
            details = [rf"\noindent\textbf{{{_inline(headers[i])}}}: {_inline(cells[i])}\par" for i in range(1, columns) if cells[i]]
            entries.append(
                "\\Needspace{5\\baselineskip}\n"
                + rf"\noindent\textbf{{{_inline(cells[0])}}}\par" + "\n"
                + "\n".join(details) + "\n\\medskip"
            )
        return "\n".join(entries)

    def row(cells: list[str]) -> str:
        return (
            " & ".join(_inline(cell).replace("\\[", "\\(").replace("\\]", "\\)") for cell in cells)
            + r" \\")

    header_row = row(_normalize_table_row(lines[0], columns))
    body_rows = [row(_normalize_table_row(line, columns)) for line in body_lines if line.strip()]
    width = max(0.12, 0.94 / columns)
    column = r">{\raggedright\arraybackslash}p{" + f"{width:.2f}" + r"\textwidth}"
    column_spec = "@{}" + column * columns + "@{}"
    repeated_header = (
        "\\toprule\n" + header_row + "\n\\midrule\n\\endhead\n"
        "\\toprule\n" + header_row + "\n\\midrule\n\\endfirsthead\n"
    )
    return (
        "\\begingroup\\small\\setlength{\\tabcolsep}{3pt}"
        "\\renewcommand{\\arraystretch}{1.18}\\sloppy\n"
        "\\begin{longtable}{" + column_spec + "}\n"
        + repeated_header
        + ("\n" + "\n".join(body_rows) if body_rows else "")
        + "\n\\bottomrule\n\\end{longtable}\\endgroup"
    )


def _pdf_bookmark_title(title: str) -> str:
    clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", title)
    clean = re.sub(r"\*([^*]+)\*", r"\1", clean)
    clean = clean.replace("~", "～")

    def _math_to_text(m: re.Match) -> str:
        s = m.group(1)
        subs = {
            r"\delta": "δ",
            r"\Delta": "Δ",
            r"\hbar": "ħ",
            r"\sigma": "σ",
            r"\pi": "π",
            r"\mu": "μ",
            r"\omega": "ω",
            r"\xi": "ξ",
            r"\epsilon": "ε",
            r"\lambda": "λ",
            r"\psi": "ψ",
            r"\phi": "φ",
            r"\to": "->",
            r"\pm": "±",
            r"\mp": "∓",
            r"\infty": "∞",
            r"^2": "²",
            r"^3": "³",
            r"^4": "⁴",
        }
        for k, v in subs.items():
            s = s.replace(k, v)
        s = re.sub(r"\\(?:hat|mathbf|vec|text|mathrm|bm)\{([^}]+)\}", r"\1", s)
        s = re.sub(r"\\[a-zA-Z]+", "", s)
        s = s.replace("{", "").replace("}", "").replace("_", "").replace("^", "")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    clean = re.sub(r"\$([^$\n]+)\$", _math_to_text, clean)
    return clean.strip()


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
    # NotebookLM sometimes appends Chinese prose directly to a TeX operator,
    # e.g. ``\max分母``. Split it into a valid operator and text atom.
    normalized = re.sub(
        r"\\(max|min|sup|inf|lim)([\u3400-\u9fff]+)",
        r"\\\1\\text{\2}",
        normalized,
    )
    # Protect math macros like \mu inside \text{...} from crashing LaTeX text mode
    normalized = re.sub(
        r"\\text\{\s*(\\[a-zA-Z]+)\s*([a-zA-Z]*)\}",
        r"\1\\text{\2}",
        normalized,
    )
    if normalized.count("$$") % 2:
        last_marker = normalized.rfind("$$")
        normalized = normalized[:last_marker] + normalized[last_marker + 2 :]
    lines = normalized.splitlines()
    # The same parser that admits figures defines which lines actually contain
    # images. A literal inside code, comments or math can never become graphics
    # merely because the legacy line renderer strips indentation or fence marks.
    from modules.figure_integrity import image_references, _parser
    parsed_image_lines = {ref.line - 1 for ref in image_references(normalized)}
    parsed_code_blocks = {token.map[0]: token for token in _parser().parse(normalized)
                          if token.type in {'fence', 'code_block'} and token.map}
    output: list[str] = []
    i = 0
    in_list: str | None = None
    pending_anchor: str | None = None
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped and in_list:
            next_index = i + 1
            while next_index < len(lines) and not lines[next_index].strip():
                next_index += 1
            next_line = lines[next_index].strip() if next_index < len(lines) else ""
            same_list = (
                bool(re.match(r"^\d+[.)]\s+", next_line))
                if in_list == "enumerate"
                else next_line.startswith(("- ", "* "))
            )
            is_math_or_indent = (
                next_line.startswith("$$")
                or (next_index < len(lines) and lines[next_index].startswith(("  ", "\t")))
            )
            has_future_item = False
            if in_list == "enumerate":
                for look in range(next_index, len(lines)):
                    look_str = lines[look].strip()
                    if not look_str:
                        continue
                    if look_str.startswith(("#", "|", "> [!", "---", "```", "<!-- PAGE_BREAK -->")):
                        break
                    if re.match(r"^\d+[.)]\s+", look_str):
                        has_future_item = True
                        break
            if same_list or is_math_or_indent or has_future_item:
                i += 1
                continue
        if stripped in {"<details>", "</details>"}:
            i += 1
            continue
        summary = re.fullmatch(r"<summary>(.*?)</summary>", stripped, re.IGNORECASE)
        if summary:
            output.append(r"\textbf{" + _inline(summary.group(1)) + "}")
            i += 1
            continue
        if stripped == "<!-- PAGE_BREAK -->":
            if in_list:
                output.append(f"\\end{{{in_list}}}")
                in_list = None
            output.append("\\clearpage")
            i += 1
            continue
        anchor = re.fullmatch(r"<!-- EXAMPLE_ID: (example-\d+) -->", stripped)
        if anchor:
            pending_anchor = anchor.group(1)
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
        if i in parsed_code_blocks:
            code_token = parsed_code_blocks[i]
            code_lines = code_token.content.splitlines()
            i = code_token.map[1]
            if all(line.isascii() for line in code_lines):
                output.append("\\begin{verbatim}\n" + "\n".join(code_lines) + "\n\\end{verbatim}")
            else:
                safe_lines = [_escape_text(line) for line in code_lines]
                output.append("\\begin{quote}\\small\n" + "\\par\n".join(safe_lines) + "\n\\end{quote}")
            continue
        if stripped.startswith("$$"):
            if stripped.count("$$") % 2 == 1:
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
            else:
                output.append(_inline(stripped))
                i += 1
                continue
        img_match = re.fullmatch(r"!\[(.*?)\]\((.*?)\)", stripped)
        if img_match and i in parsed_image_lines:
            if in_list:
                output.append(f"\\end{{{in_list}}}")
                in_list = None
            caption_raw = img_match.group(1).strip()
            img_target = img_match.group(2).strip()
            clean_target = img_target.replace("\\", "/").strip('"\'')
            parts = [p.strip() for p in caption_raw.split("|") if p.strip()]
            caption_text = parts[0] if parts else ""
            width_spec = "0.75\\linewidth"
            align_spec = "centering"
            raw_options = []
            for part in parts[1:]:
                for opt in re.split(r"[,;]", part):
                    if opt.strip():
                        raw_options.append(opt.strip())
            for opt in raw_options:
                opt_lower = opt.lower()
                if opt_lower.startswith("width="):
                    val = opt[6:].strip()
                    if val.endswith("%"):
                        try:
                            pct = float(val[:-1]) / 100.0
                            width_spec = f"{pct:.2f}\\linewidth"
                        except ValueError:
                            pass
                    elif any(unit in val for unit in ("linewidth", "textwidth", "cm", "pt", "in", "mm")):
                        width_spec = val
                    elif val.isdigit():
                        width_spec = f"{val}pt"
                elif opt_lower in {"left", "raggedright"} or opt_lower.startswith("align=left"):
                    align_spec = "raggedright"
                elif opt_lower in {"center", "centering"} or opt_lower.startswith("align=center"):
                    align_spec = "centering"
                elif opt_lower in {"right", "raggedleft"} or opt_lower.startswith("align=right"):
                    align_spec = "raggedleft"

            fig_block = [
                "\\begin{figure}[H]",
                f"\\{align_spec}",
                f"\\includegraphics[width={width_spec},height=0.45\\textheight,keepaspectratio]{{{clean_target}}}",
            ]
            if caption_text:
                fig_block.append(f"\\caption{{{_inline(caption_text)}}}")
            fig_block.append("\\end{figure}")
            output.append("\n".join(fig_block))
            i += 1
            continue
        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        ):
            if in_list:
                output.append(f"\\end{{{in_list}}}")
                in_list = None
            table_lines, i = _collect_table_lines(lines, i)
            output.append(_table(table_lines))
            continue
        callout = _CALLOUT.match(stripped)
        if callout:
            if in_list:
                output.append(f"\\end{{{in_list}}}")
                in_list = None
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
        numbered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        list_kind = "enumerate" if numbered else "itemize" if stripped.startswith(("- ", "* ")) else None
        if list_kind:
            if in_list and in_list != list_kind:
                output.append(f"\\end{{{in_list}}}")
                in_list = None
            if in_list is None:
                output.append(f"\\begin{{{list_kind}}}")
                in_list = list_kind
            output.append("\\item " + _inline(numbered.group(1) if numbered else stripped[2:]))
            i += 1
            continue
        if in_list:
            is_continuation = False
            if line.startswith(("  ", "\t")):
                is_continuation = True
            elif in_list == "enumerate":
                for look in range(i + 1, len(lines)):
                    look_str = lines[look].strip()
                    if not look_str:
                        continue
                    if look_str.startswith(("#", "|", "> [!", "---", "```", "<!-- PAGE_BREAK -->")):
                        break
                    if re.match(r"^\d+[.)]\s+", look_str):
                        is_continuation = True
                        break
            if is_continuation:
                output.append(_inline(stripped))
                i += 1
                continue
            output.append(f"\\end{{{in_list}}}")
            in_list = None
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            command = {1: "section", 2: "subsection", 3: "subsubsection", 4: "paragraph"}[level]
            if level == 4 and title in {"解答", "答案与解析", "详细解答"}:
                output.append("\\Needspace{4\\baselineskip}")
                output.append("\\par\\medskip\\noindent\\rule{\\linewidth}{0.3pt}\\par\\smallskip")
                output.append(f"\\noindent\\textbf{{{_inline(title)}}}\\par")
                i += 1
                continue
            clean_title = title.strip()
            if level == 2 and (clean_title in {"本章路线", "章末过关", "考情速览", "课时过关练习", "课时练习"} or any(clean_title.startswith(prefix) for prefix in ("考情速览", "课时过关练习", "课时过关", "章末过关", "本章路线"))):
                command += "*"
            if level == 1:
                output.append("\\Needspace{8\\baselineskip}")
            if level in {2, 3}:
                output.append("\\Needspace{7\\baselineskip}" if any(kw in title for kw in ("标准例题", "典型例题")) else "\\Needspace{4\\baselineskip}")
            if pending_anchor:
                output.append(r"\phantomsection\label{" + pending_anchor + "}")
                pending_anchor = None
            if ("$" in title or "~" in title) and not command.endswith("*"):
                pdf_title = _pdf_bookmark_title(title)
                output.append(f"\\{command}{{\\texorpdfstring{{{_inline(title)}}}{{{pdf_title}}}}}")
            else:
                output.append(f"\\{command}{{{_inline(title)}}}")
        elif stripped:
            output.append(_inline(stripped))
        else:
            output.append("")
        i += 1
    if in_list:
        output.append(f"\\end{{{in_list}}}")
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
    academic = style.get("layout") == "academic"
    body = render_markdown_to_latex(manuscript)
    box_options = (
        "breakable,colback=white,colframe=black!35,boxrule=0.3pt,"
        "fonttitle=\\bfseries"
        if academic
        else "breakable,colback=primary!5,colframe=primary,fonttitle=\\bfseries"
    )
    document = (
        "\\documentclass[UTF8,a4paper,12pt]{ctexart}\n"
        "\\usepackage{amsmath,amssymb,booktabs,geometry}\n"
        "\\usepackage{esint,extarrows}\n"
        "\\usepackage{xcolor,longtable,array}\n"
        "\\usepackage{graphicx,float}\n"
        "\\usepackage[font=small,labelfont=bf,labelsep=space]{caption}\n"
        "\\usepackage{fancyhdr}\n"
        "\\usepackage[most]{tcolorbox}\n"
        "\\usepackage{needspace}\n"
        "\\usepackage[hidelinks,unicode]{hyperref}\n"
        "\\geometry{margin=2.2cm}\n"
        "\\setlength{\\headheight}{15pt}\n"
        "\\setlength{\\parindent}{2em}\n"
        "\\setlength{\\parskip}{0.55em}\n"
        "\\linespread{1.25}\n"
        "\\setlength{\\emergencystretch}{2em}\n"
        "\\raggedbottom\n"
        "\\setcounter{tocdepth}{2}\n"
        "\\setcounter{secnumdepth}{0}\n"
        f"\\definecolor{{primary}}{{HTML}}{{{_color(style, 'primary_color', '1F4E79')}}}\n"
        f"\\definecolor{{emphasis}}{{HTML}}{{{_color(style, 'emphasis_color', 'E67E22')}}}\n"
        f"\\definecolor{{warning}}{{HTML}}{{{_color(style, 'warning_color', 'B42318')}}}\n"
        f"\\definecolor{{success}}{{HTML}}{{{_color(style, 'success_color', '2E7D32')}}}\n"
        f"\\definecolor{{muted}}{{HTML}}{{{_color(style, 'muted_color', '6B7280')}}}\n"
        "\\ctexset{section={format=\\Large\\bfseries\\color{primary}},subsection={format=\\large\\bfseries\\color{primary}},subsubsection={format=\\normalsize\\bfseries\\color{primary}}}\n"
        f"\\newtcolorbox{{importantbox}}[1][]{{{box_options},#1}}\n"
        f"\\newtcolorbox{{tipbox}}[1][]{{{box_options},#1}}\n"
        f"\\newtcolorbox{{warningbox}}[1][]{{{box_options},#1}}\n"
        f"\\newtcolorbox{{checkbox}}[1][]{{{box_options},#1}}\n"
        "\\pagestyle{fancy}\n\\fancyhf{}\n"
        "\\renewcommand{\\sectionmark}[1]{\\markboth{#1}{}}\n"
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
