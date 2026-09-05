"""两阶段 Prompt 编排：阶段一固定 Prompt → 题型解析 → 阶段二动态 Prompt。

职责边界：
- 题型解析（parse_question_types）：纯文本解析，独立可测
- 编排（run_pipeline）：状态管理（state.json）、raw 缓存断点续跑、
  增量上传、失败重试与汇总

状态与缓存（output/<课程>/ 下）：
    state.json   —— notebook_id + 已上传文件相对路径清单（增量上传依据）
    raw/<id>.md  —— 固定 Prompt 回答缓存
    raw/题型_<名>.md —— 题型文件回答缓存
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from modules.config import AppConfig
    from modules.file_manager import CourseManifest
    from modules.notebooklm import NotebookLMService, UploadReport
    from modules.prompts import PromptBook

# --------------------------------------------------------------- 异常

class PromptRunnerError(Exception):
    """编排层错误基类。"""


class QuestionTypeParseError(PromptRunnerError):
    """题型总结中无法解析出题型清单。"""


# --------------------------------------------------------------- 题型名清洗

# Windows 文件名非法字符
_ILLEGAL_FN_CHARS = re.compile(r'[\\/:*?"<>|]')
_MAX_TYPE_NAME_LEN = 40


def sanitize_type_name(name: str) -> str:
    """清洗题型名 → 安全文件名片段：去非法字符与首尾空白，截断长度。"""
    cleaned = _ILLEGAL_FN_CHARS.sub("_", name).strip().strip(".").strip()
    return cleaned[:_MAX_TYPE_NAME_LEN]


# --------------------------------------------------------------- 题型清单解析

_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_NUMBERED = re.compile(r"^\s*(?:\d+[.、)．]|[一二三四五六七八九十]+[、.．])\s*(\S.*)$")
_ORDINAL_CELL = re.compile(r"^[\d一二三四五六七八九十]+$")


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and any(cells)


def _parse_tables(text: str) -> list[list[list[str]]]:
    """提取所有 markdown 表格（含表头），返回每表的行列表。"""
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.splitlines():
        m = _TABLE_ROW.match(line)
        if m:
            current.append(_split_row(m.group(1)))
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _clean_cell(cell: str) -> str:
    """去掉单元格里的粗体/反引号包裹。"""
    return cell.replace("**", "").replace("`", "").strip()


def _extract_from_tables(text: str) -> list[str]:
    """策略①②：约定表格（题型名称列）→ 任意表格（首非序号列）。

    表头判定：markdown 规范中表头后必跟分隔行；无分隔行时无法确认
    表头，全部行视为数据行。
    """
    tables = _parse_tables(text)
    # 策略①：表头含"题型名称"
    for table in tables:
        if not table:
            continue
        header = [_clean_cell(c) for c in table[0]]
        if any("题型名称" in h for h in header):
            idx = next(i for i, h in enumerate(header) if "题型名称" in h)
            names = [
                _clean_cell(row[idx])
                for row in table[1:]
                if len(row) > idx and not _is_separator(row)
            ]
            names = [n for n in names if n]
            if names:
                return names
    # 策略②：任意 ≥2 列表格，取首个非序号列
    for table in tables:
        if len(table) >= 2 and _is_separator(table[1]):
            rows = table[2:]  # 规范表格：跳过表头与分隔行
        else:
            rows = table      # 无分隔行：无法确认表头，全部当数据行
        rows = [r for r in rows if r and not _is_separator(r)]
        if not rows:
            continue
        width = min(len(r) for r in rows)
        if width < 2:
            continue
        idx = 0 if not _ORDINAL_CELL.match(_clean_cell(rows[0][0] or "")) else 1
        if idx >= width:
            continue
        names = [
            _clean_cell(r[idx]) for r in rows
            if len(r) > idx and _clean_cell(r[idx])
        ]
        if names:
            return names
    return []


def _extract_numbered(text: str) -> list[str]:
    """策略③：编号行（1. xxx / 一、xxx），限长且排除含句内标点的句子。"""
    names: list[str] = []
    for line in text.splitlines():
        m = _NUMBERED.match(line)
        if not m:
            continue
        cand = m.group(1).strip().strip("*").strip()
        # 题型名约定 ≤10 字；容忍到 20 字。含句内标点或超长视为正文句子
        if not cand or len(cand) > 20:
            continue
        if any(ch in cand for ch in "，,；;：:。！？!?"):
            continue
        names.append(cand)
    return names


def parse_question_types(text: str, max_types: int) -> list[str]:
    """从题型总结回答中解析题型清单。

    解析分级：① 约定格式的表格 → ② 任意 markdown 表格 → ③ 编号行。
    结果经清洗、去重、截断到 max_types；无法解析抛 QuestionTypeParseError。
    """
    raw: list[str] = []
    for extractor in (_extract_from_tables, _extract_numbered):
        raw = extractor(text)
        if raw:
            break

    cleaned: list[str] = []
    seen: set[str] = set()
    for name in raw:
        n = sanitize_type_name(name)
        if n and n not in seen and not _ORDINAL_CELL.match(n):
            seen.add(n)
            cleaned.append(n)
        if len(cleaned) >= max_types:
            break

    if not cleaned:
        raise QuestionTypeParseError(
            "无法从题型总结中解析出题型清单（未找到可识别的表格或编号列表）。"
            "请用 --prompts question_type_summary 单独重跑该 Prompt 后重试"
        )
    return cleaned


# --------------------------------------------------------------- 状态与结果

class PipelineState(BaseModel):
    """跨运行持久化的流水线状态。"""

    notebook_id: str | None = None
    uploaded_files: list[str] = Field(default_factory=list)  # 相对课程根的 posix 路径


class PromptOutcome(BaseModel):
    """单个 Prompt 的执行结果。"""

    key: str            # 缓存键：固定 id 或 题型_<名>
    title: str
    success: bool
    from_cache: bool = False
    error: str | None = None
    raw_file: str = ""  # 相对 raw/ 的文件名


class PipelineResult(BaseModel):
    notebook_id: str
    fixed_outcomes: list[PromptOutcome] = Field(default_factory=list)
    question_types: list[str] = Field(default_factory=list)
    type_outcomes: list[PromptOutcome] = Field(default_factory=list)

    @property
    def failures(self) -> list[PromptOutcome]:
        return [o for o in (*self.fixed_outcomes, *self.type_outcomes) if not o.success]


# --------------------------------------------------------------- 编排

async def _ask_with_retry(
    svc: NotebookLMService, notebook_id: str, question: str, retry: int,
) -> str:
    """带重试的提问：网络类失败重试，认证类失败直接上抛（中断流水线）。"""
    from modules.notebooklm import NotebookLMAuthError

    last_err: Exception | None = None
    for attempt in range(retry + 1):
        try:
            return await svc.ask(notebook_id, question)
        except NotebookLMAuthError:
            raise
        except Exception as e:
            last_err = e
            if attempt < retry:
                logger.warning("提问失败（{}），重试 {}/{}", e, attempt + 1, retry)
    raise last_err  # type: ignore[misc]


async def run_pipeline(
    cfg: AppConfig,
    book: PromptBook,
    course_name: str,
    manifest: CourseManifest,
    svc: NotebookLMService,
    only_fixed: list[str] | None = None,
    fresh: bool = False,
) -> PipelineResult:
    """执行完整两阶段流水线。

    only_fixed：仅执行指定 id 的固定 Prompt（调试模式，跳过阶段二）。
    fresh：清空 raw 缓存与上传状态，重跑（Notebook 仍按标题复用）。
    """
    from modules.prompts import render_dynamic, render_fixed

    if not course_name or "/" in course_name or "\\" in course_name or course_name in (".", ".."):
        raise PromptRunnerError(f"非法的课程名称：{course_name}")

    out_dir = cfg.paths.output_dir / course_name
    raw_dir = out_dir / "raw"
    state_path = out_dir / "state.json"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if fresh:
        logger.info("--fresh：清空缓存与状态，重新执行")
        for p in raw_dir.glob("*.md"):
            p.unlink()
        state = PipelineState()
    else:
        state = _load_state(state_path)

    # --- Notebook 复用/新建（按标题；state 仅作记录） ---
    notebook_id = await svc.get_or_create_notebook(course_name)
    state.notebook_id = notebook_id
    _save_state(state_path, state)

    # --- 增量上传：仅上传未上传过的文件 ---
    rel_files = [f.path.relative_to(manifest.root).as_posix() for f in manifest.files]
    pending = [f for f, rel in zip(manifest.files, rel_files) if rel not in set(state.uploaded_files)]
    if pending:
        logger.info("需上传资料 {} 个（复用已上传 {} 个）", len(pending), len(rel_files) - len(pending))
        partial_manifest = manifest.model_copy(
            update={"files": pending, "total_size_bytes": sum(f.size_bytes for f in pending)}
        )
        report: UploadReport = await svc.upload_sources(notebook_id, partial_manifest)
        done_rels = {
            rel for rel, f in zip(rel_files, manifest.files)
            if f.path.name in set(report.uploaded)
        }
        state.uploaded_files.extend(sorted(done_rels))
        _save_state(state_path, state)
    else:
        logger.info("全部 {} 个资料此前已上传，跳过上传", len(rel_files))

    # --- 阶段一：固定 Prompt ---
    result = PipelineResult(notebook_id=notebook_id)
    summary_answer: str | None = None
    for p in book.fixed:
        if only_fixed is not None and p.id not in only_fixed:
            continue
        outcome = await _run_fixed_prompt(
            raw_dir, svc, notebook_id, p, cfg.prompt_runner.max_question_types,
            cfg.prompt_runner.retry, fresh,
        )
        result.fixed_outcomes.append(outcome)
        if p.id == "question_type_summary" and outcome.success:
            summary_answer = (raw_dir / f"{p.id}.md").read_text(encoding="utf-8")
        if not outcome.success:
            logger.error("固定 Prompt「{}」执行失败：{}", p.title, outcome.error)

    if only_fixed is not None:
        logger.info("调试模式（--prompts）：跳过阶段二")
        return result

    # --- 题型解析 ---
    if summary_answer is None:
        raise PromptRunnerError(
            "题型总结 Prompt 未成功执行，无法进入阶段二；"
            "请先重跑：--prompts question_type_summary"
        )
    try:
        types = parse_question_types(summary_answer, cfg.prompt_runner.max_question_types)
    except QuestionTypeParseError:
        raise
    result.question_types = types
    logger.info("解析出 {} 类题型：{}", len(types), "、".join(types))

    # --- 阶段二：题型详解 ---
    type_list_str = "、".join(types)
    detail = book.question_type_detail
    for t in types:
        key = f"题型_{t}"
        raw_file = raw_dir / f"{key}.md"
        if raw_file.exists() and not fresh:
            logger.info("缓存命中，跳过：{}", key)
            result.type_outcomes.append(
                PromptOutcome(key=key, title=t, success=True, from_cache=True, raw_file=f"{key}.md")
            )
            continue
        question = render_dynamic(detail, type_name=t, type_list=type_list_str)
        try:
            answer = await _ask_with_retry(svc, notebook_id, question, cfg.prompt_runner.retry)
            raw_file.write_text(answer, encoding="utf-8")
            logger.success("题型详解完成：{}", t)
            result.type_outcomes.append(
                PromptOutcome(key=key, title=t, success=True, raw_file=f"{key}.md")
            )
        except Exception as e:
            logger.error("题型「{}」执行失败：{}", t, e)
            result.type_outcomes.append(
                PromptOutcome(key=key, title=t, success=False, error=str(e))
            )

    return result


async def _run_fixed_prompt(
    raw_dir: Path,
    svc: NotebookLMService,
    notebook_id: str,
    prompt,  # FixedPrompt
    max_types: int,
    retry: int,
    fresh: bool,
) -> PromptOutcome:
    from modules.prompts import render_fixed

    raw_file = raw_dir / f"{prompt.id}.md"
    if raw_file.exists() and not fresh:
        logger.info("缓存命中，跳过：{}", prompt.id)
        return PromptOutcome(
            key=prompt.id, title=prompt.title, success=True,
            from_cache=True, raw_file=f"{prompt.id}.md",
        )
    question = render_fixed(prompt, max_types=max_types)
    try:
        answer = await _ask_with_retry(svc, notebook_id, question, retry)
        raw_file.write_text(answer, encoding="utf-8")
        logger.success("固定 Prompt 完成：{}", prompt.title)
        return PromptOutcome(key=prompt.id, title=prompt.title, success=True, raw_file=f"{prompt.id}.md")
    except Exception as e:
        return PromptOutcome(key=prompt.id, title=prompt.title, success=False, error=str(e))


def _load_state(path: Path) -> PipelineState:
    if path.is_file():
        try:
            return PipelineState.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("state.json 解析失败，视为无状态：{}", e)
    return PipelineState()


def _save_state(path: Path, state: PipelineState) -> None:
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
