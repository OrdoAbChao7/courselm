"""Locate real worked examples in generated chapters for reader-facing indexes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_CHAPTER = re.compile(r"^#\s+(第\d+章\s+.+?)\s*$")
_TYPE = re.compile(r"^##\s+(题型(?:[一二三四五六七八九十]+|\d+)\s*[：:].+?)\s*$")
_EXAMPLE = re.compile(r"^###\s+(标准例题(?:\s*[：:].*)?)\s*$")


@dataclass(frozen=True)
class ExampleEntry:
    chapter: str
    question_type: str
    example_heading: str
    filename: str
    anchor: str

    @property
    def label(self) -> str:
        return f"{self.chapter} · {self.question_type}"


def index_chapter(content: str, filename: str, first_number: int = 1, *, annotate: bool = False) -> tuple[str, list[ExampleEntry]]:
    """Collect standard examples; optionally insert PDF anchor comments before them."""
    lines = content.splitlines()
    chapter = Path(filename).stem
    question_type = ""
    entries: list[ExampleEntry] = []
    output: list[str] = []
    for line in lines:
        if match := _CHAPTER.match(line):
            chapter = match.group(1)
        elif match := _TYPE.match(line):
            question_type = match.group(1)
        elif match := _EXAMPLE.match(line):
            if question_type:
                anchor = f"example-{first_number + len(entries)}"
                entries.append(ExampleEntry(chapter, question_type, match.group(1), filename, anchor))
                if annotate:
                    output.append(f"<!-- EXAMPLE_ID: {anchor} -->")
        output.append(line)
    return "\n".join(output), entries


def pdf_question_index(entries: list[ExampleEntry]) -> str:
    return "\n".join(
        ["按章节查找标准例题：", ""]
        + [f"- [{entry.label}](#{entry.anchor})" for entry in entries]
    )


def obsidian_question_index(entries: list[ExampleEntry]) -> str:
    return "\n".join(
        ["# 典型题型索引", "", "按章节查找标准例题：", ""]
        + [
            f"- [[{Path(entry.filename).stem}#{entry.example_heading}|{entry.label}]]"
            for entry in entries
        ]
    )
