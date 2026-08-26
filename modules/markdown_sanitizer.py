"""NotebookLM 输出到 Obsidian Markdown 的统一清洗器。"""

from __future__ import annotations

import html
import re
import unicodedata

from loguru import logger

_FENCE = chr(96) * 3
_CODE_BLOCK = re.compile(
    rf"({re.escape(_FENCE)}.*?{re.escape(_FENCE)}|~~~.*?~~~)", re.DOTALL
)
_DISPLAY_MATH = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_INLINE_MATH = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_HTML_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_PARAGRAPH = re.compile(r"</?p(?:\s[^>]*)?>", re.IGNORECASE)
_MULTI_BLANK = re.compile(r"\n{3,}")
_INVISIBLE = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d"), None)

# 只恢复明确像“下标”的转换残留：E*0、E*{xm}、\vec{S}*{av}。
# 不匹配 a*b，因此不会把普通乘法无条件改成下标。
_STAR_SUBSCRIPT = re.compile(
    r"(?P<base>(?:\\[A-Za-z]+(?:\{[^{}\n]*\})?|[A-Za-z](?:\{[^{}\n]*\})?))"
    r"\*(?P<sub>\{[^{}\n]*\}|[0-9]+)"
)


def _unescaped_dollar(text: str, start: int, double: bool) -> int | None:
    """查找未被奇数个反斜杠转义的数学结束符。"""
    marker = "$$" if double else "$"
    pos = start
    while True:
        pos = text.find(marker, pos)
        if pos < 0:
            return None
        backslashes = 0
        cursor = pos - 1
        while cursor >= 0 and text[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return pos
        pos += len(marker)


def _normalize_latex(body: str) -> str:
    body = body.replace(r"\_", "_")
    body = re.sub(r"\\\\\s*$", "", body)
    return _STAR_SUBSCRIPT.sub(r"\g<base>_\g<sub>", body)


def _normalize_math_regions(text: str) -> str:
    """只对行内和块级美元定界的数学区域执行 LaTeX 清洗。"""
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        dollar = text.find("$", cursor)
        if dollar < 0:
            output.append(text[cursor:])
            break
        output.append(text[cursor:dollar])
        double = text.startswith("$$", dollar)
        width = 2 if double else 1
        end = _unescaped_dollar(text, dollar + width, double)
        if end is None:
            output.append(text[dollar:])
            break
        output.append(
            text[dollar:dollar + width]
            + _normalize_latex(text[dollar + width:end])
            + text[end:end + width]
        )
        cursor = end + width
    return "".join(output)


def _convert_math_delimiters(text: str) -> str:
    text = _DISPLAY_MATH.sub(lambda m: "$$" + m.group(1).strip() + "$$", text)
    return _INLINE_MATH.sub(lambda m: "$" + m.group(1).strip() + "$", text)


def _clean_html_residue(text: str) -> str:
    text = _HTML_BREAK.sub("\n", text)
    text = _HTML_PARAGRAPH.sub("\n", text)
    return re.sub(r"\n[ \t]+(?=\$)", "\n", text)


def _warn_suspicious(text: str) -> None:
    patterns = (r"&#x", r"&nbsp;?", r"\\_", r"\\\*{", r"\\\$")
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
        logger.warning(
            "Markdown sanitizer warning: possible malformed LaTeX detected"
        )


def sanitize_markdown(text: str) -> str:
    """把 NotebookLM 回答清洗成可直接写入 Obsidian 的 Markdown。"""
    text = unicodedata.normalize("NFC", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = text.translate(_INVISIBLE).replace("\r\n", "\n").replace("\r", "\n")

    parts: list[str] = []
    for index, segment in enumerate(_CODE_BLOCK.split(text)):
        if not segment:
            continue
        if index % 2 == 1:
            parts.append(segment)
            continue
        segment = _clean_html_residue(segment)
        segment = _convert_math_delimiters(segment)
        segment = _normalize_math_regions(segment)
        parts.append(segment)

    cleaned = _MULTI_BLANK.sub("\n\n", "".join(parts)).strip()
    _warn_suspicious(cleaned)
    return cleaned
