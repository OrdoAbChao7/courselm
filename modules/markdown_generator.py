"""Markdown 生成模块：raw 回答 → Obsidian 格式文档。

流程位置：
    raw 缓存（output/<课程>/raw/）→ [本模块] → output/<课程>/md/ → [obsidian_sync] → Vault

职责：
- 防御性清洗 NotebookLM 输出（LaTeX 定界符转换、空行压缩、代码块保护）
- 生成 Obsidian Front Matter（course / type / tags / created）
- 按 prompts.yaml 的 output_file / output_subdir 布局写出最终文档
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml
from loguru import logger
from pydantic import BaseModel

from modules.config import AppConfig
from modules.markdown_sanitizer import sanitize_markdown
from modules.prompt_runner import PipelineResult
from modules.prompts import GENERATION_SCHEMA_VERSION, PromptBook
from modules.question_index import index_chapter, obsidian_question_index

# --------------------------------------------------------------- 清洗

def clean_markdown(text: str) -> str:
    """统一委托给 Markdown Sanitizer。"""
    return sanitize_markdown(text)


# --------------------------------------------------------------- Front Matter

def _safe_tag(tag: str) -> str:
    """Obsidian tag 非法字符清洗：仅保留中英文/数字/下划线/连字符。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", tag)
    return cleaned.strip("_") or "未分类"


def render_doc(
    raw_text: str,
    course_name: str,
    doc_type: str,
    tags: list[str],
    extra_meta: dict | None = None,
) -> str:
    """渲染单篇文档：Front Matter + 清洗后的正文。"""
    meta: dict = {
        "course": course_name,
        "type": doc_type,
        "generation_schema_version": GENERATION_SCHEMA_VERSION,
        "tags": [_safe_tag(t) for t in (*tags, doc_type)],
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if extra_meta:
        meta.update(extra_meta)

    front = yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip("\n")
    body = clean_markdown(raw_text)
    return f"---\n{front}\n---\n\n{body}\n"


# --------------------------------------------------------------- 文档清单与落盘

class MarkdownDoc(BaseModel):
    """一篇待生成文档的目标与来源。"""

    dest_rel: str      # 相对 output/<课程>/md/ 的输出路径
    raw_file: str      # raw/ 下缓存文件名
    doc_type: str      # front matter type（取自 prompt title）
    title: str         # 人类可读标题（日志用）
    extra_meta: dict = {}


def collect_docs(book: PromptBook, result: PipelineResult) -> list[MarkdownDoc]:
    """从流水线结果推导绪论与动态章节文档清单。"""
    docs: list[MarkdownDoc] = []
    if result.introduction_outcome and result.introduction_outcome.success:
        docs.append(MarkdownDoc(
            dest_rel=book.global_prompts.introduction.output_file,
            raw_file=result.introduction_outcome.raw_file,
            doc_type=book.global_prompts.introduction.title,
            title=book.global_prompts.introduction.title,
        ))
    for outcome in result.chapter_outcomes:
        if outcome.success:
            docs.append(MarkdownDoc(
                dest_rel=f"chapters/{Path(outcome.raw_file).name}",
                raw_file=outcome.raw_file,
                doc_type=book.dynamic.chapter.title,
                title=outcome.title,
                extra_meta={"chapter": outcome.key.removeprefix("chapter_")},
            ))
    return docs


def generate_all(
    cfg: AppConfig,
    book: PromptBook,
    course_name: str,
    result: PipelineResult,
) -> list[Path]:
    """读取 raw 缓存 → 渲染 → 写入 output/<课程>/md/。返回已写文件列表。"""
    md_dir = cfg.paths.output_dir / course_name / "md"
    raw_dir = cfg.paths.output_dir / course_name / "raw" / f"v{GENERATION_SCHEMA_VERSION}"
    md_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for doc in collect_docs(book, result):
        raw_path = raw_dir / doc.raw_file
        if not doc.raw_file or not raw_path.is_file():
            logger.warning("raw 缓存缺失，跳过文档：{}", doc.raw_file or doc.title)
            continue
        text = render_doc(
            raw_path.read_text(encoding="utf-8"),
            course_name=course_name,
            doc_type=doc.doc_type,
            tags=cfg.markdown.tags,
            extra_meta=doc.extra_meta,
        )
        dest = md_dir / doc.dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        logger.success("生成文档：{}/{}", course_name, doc.dest_rel)
        written.append(dest)

    entries = []
    for doc in collect_docs(book, result):
        if not doc.raw_file.startswith("chapters/"):
            continue
        chapter_path = md_dir / doc.dest_rel
        if chapter_path not in written:
            continue
        _, found = index_chapter(chapter_path.read_text(encoding="utf-8"), chapter_path.name, len(entries) + 1)
        entries.extend(found)
    if entries:
        index_path = md_dir / "appendix" / "02-典型题型索引.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            render_doc(obsidian_question_index(entries), course_name, "典型题型索引", cfg.markdown.tags),
            encoding="utf-8",
        )
        written.append(index_path)

    logger.info("文档生成完成：{}/md/ 共 {} 篇", course_name, len(written))
    return written
