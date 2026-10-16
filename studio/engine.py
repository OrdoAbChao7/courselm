"""Small, tested adapters to CourseLM's existing pipeline."""
from __future__ import annotations

import re
from pathlib import Path
from studio.workspace import is_link

MODES = {
    "sprint": {"name": "考前冲刺", "subtitle": "考前三天 · 核心考点与得分步骤", "instruction": "\n\n【本次生成模式：考前冲刺】优先突出最关键的定义、考试可用公式、题型识别信号、快速解题步骤及易错陷阱。控制重复解释，保留必要推导并明确前提。对无法从资料确认的考试重点标注待确认，不编造考试范围。"},
    "comprehensive": {"name": "完整精讲", "subtitle": "概念理解 · 推导过程 · 典型应用", "instruction": "\n\n【本次生成模式：完整精讲】重视从直观认识到严格定义的逻辑链，逐步推导关键公式，给出适用条件与反例，典型题展示完整思考过程。保持与上传资料一致，不凭空补充考试范围。"},
    "practice": {"name": "题型突破", "subtitle": "题型辨认 · 解题套路 · 错因分析", "instruction": "\n\n【本次生成模式：题型突破】每章重点围绕题型识别、常见解法、分步示范和典型变式组织内容。先提供最小必要的概念解释，再突出题目中的识别信号与失分原因。无法核验来源的题目应明确标记改编或补充。"},
}
STYLES = {
    "academic": {"name": "学术经典", "latex": {"layout": "academic", "primary_color": "1F4E79", "emphasis_color": "BA6B23", "warning_color": "A63434", "success_color": "287A58", "muted_color": "64748B"}},
    "modern": {"name": "现代蓝调", "latex": {"layout": "modern", "primary_color": "4F46E5", "emphasis_color": "0891B2", "warning_color": "D64747", "success_color": "059669", "muted_color": "64748B"}},
    "warm": {"name": "暖色书卷", "latex": {"layout": "modern", "primary_color": "8B5E3C", "emphasis_color": "C77D42", "warning_color": "B73E3E", "success_color": "48845B", "muted_color": "74685E"}},
    "minimal": {"name": "黑白极简", "latex": {"layout": "academic", "primary_color": "222222", "emphasis_color": "444444", "warning_color": "555555", "success_color": "333333", "muted_color": "777777"}},
}
ALLOWED_EXTENSIONS = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_FILES = 200
MAX_TOTAL_BYTES = 400 * 1024 * 1024


def safe_slug(course: str) -> str:
    value = re.sub(r"[^\w\u3400-\u9fff-]+", "-", course.strip(), flags=re.U).strip("-_ ")[:38]
    if not value:
        raise ValueError("请填写课程名称")
    return value


def inventory(path: str | Path) -> dict:
    """Accept a local folder or a single file. Never follow symlinks."""
    original = Path(path).expanduser().absolute()
    if not str(path).strip():
        raise ValueError("请填写资料路径")
    if any(is_link(p) for p in (original, *original.parents)):
        raise ValueError("不允许使用符号链接或目录联接")
    root = original.resolve()
    if not root.exists():
        raise ValueError("资料路径不存在，请选择真实文件夹")
    if root.is_symlink():
        raise ValueError("不允许使用符号链接")
    if root.is_file():
        candidates = [root]
        base = root.parent
    elif root.is_dir():
        candidates = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS)
        base = root
    else:
        raise ValueError("资料路径不是普通文件或文件夹")
    if not candidates:
        raise ValueError("没有找到支持的课件或文档")
    if len(candidates) > MAX_FILES:
        raise ValueError(f"文件数量超过 {MAX_FILES} 个，请分批处理")
    files, size = [], 0
    for p in candidates:
        if any(is_link(item) for item in (p, *p.parents)):
            raise ValueError("来源目录中存在符号链接，请移除后重试")
        if p.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        file_size = p.stat().st_size
        with p.open('rb') as source:
            source.read(1)  # Fail before creating a job when a source is unreadable.
        size += file_size
        if size > MAX_TOTAL_BYTES:
            raise ValueError("文件总量超过 400 MB，请先拆分资料")
        files.append({"relative": p.relative_to(base).as_posix(), "size": file_size, "source": str(p)})
    if not files:
        raise ValueError("所选文件不属于受支持的类型")
    return {"root": str(root), "base": str(base), "count": len(files), "total_bytes": size, "files": files}


def apply_mode(book, mode: str):
    """Actual content change, not a cosmetic mode switch; preserves model schema."""
    if mode not in MODES:
        raise ValueError("未知的讲义模式")
    note = MODES[mode]["instruction"]
    chapter = book.dynamic.chapter.model_copy(update={"template": book.dynamic.chapter.template + note})
    intro = book.global_prompts.introduction.model_copy(update={"template": book.global_prompts.introduction.template + note})
    global_updates = {"introduction": intro}
    if hasattr(book, 'appendices'):
        global_updates['appendices'] = [p.model_copy(update={"template": p.template + note}) for p in book.appendices]
    return book.model_copy(update={
        "dynamic": book.dynamic.model_copy(update={"chapter": chapter}),
        "global_prompts": book.global_prompts.model_copy(update=global_updates),
    })


def make_style_config(mode: str, style: str, title: str, subtitle: str, accent: str | None = None) -> dict:
    if mode not in MODES or style not in STYLES:
        raise ValueError("模式或风格不受支持")
    latex = STYLES[style]["latex"].copy()
    if accent:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", accent):
            raise ValueError("强调色必须是六位十六进制颜色")
        latex["primary_color"] = accent[1:].upper()
    if len(title) > 80 or len(subtitle) > 180:
        raise ValueError("讲义标题或副标题过长")
    return {"title_suffix": title.strip() or (MODES[mode]["name"] + "复习讲义"),
            "subtitle": subtitle.strip() or MODES[mode]["subtitle"], "latex": latex}
