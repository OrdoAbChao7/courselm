"""课程资料扫描：courses/<课程名>/ → 结构化清单。

- 递归扫描，按配置扩展名识别文件，归类 pdf/ppt/doc/image/other
- 忽略 Office 锁定文件（~$ 开头）与隐藏文件/目录（. 开头）
- 清单按相对路径排序，多次扫描结果稳定
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import BaseModel

FileCategory = Literal["pdf", "ppt", "doc", "image", "other"]

# 扩展名 → 类别；配置中出现映射外的扩展名归 other
_EXT_CATEGORY: dict[str, FileCategory] = {
    ".pdf": "pdf",
    ".ppt": "ppt",
    ".pptx": "ppt",
    ".doc": "doc",
    ".docx": "doc",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
    ".gif": "image",
}


class FileManagerError(Exception):
    """文件管理模块错误基类。"""


class CourseNotFoundError(FileManagerError):
    """课程目录不存在。"""


class NoCourseFilesError(FileManagerError):
    """课程目录存在，但没有任何匹配类型的文件。"""


class CourseFile(BaseModel):
    path: Path
    size_bytes: int
    category: FileCategory


class CourseManifest(BaseModel):
    """一次课程扫描的完整结果。"""

    course_name: str
    root: Path
    files: list[CourseFile]
    source_limit_warn: int | None = None
    total_size_bytes: int = 0

    def __repr__(self) -> str:  # 方便日志与调试输出
        cats: dict[str, int] = {}
        for f in self.files:
            cats[f.category] = cats.get(f.category, 0) + 1
        stats = ", ".join(f"{c}={n}" for c, n in sorted(cats.items()))
        return f"<CourseManifest {self.course_name!r}: {len(self.files)} 个文件 ({stats}), 共 {self.total_size_bytes} 字节>"


def _is_noise(path: Path, root: Path) -> bool:
    """Office 锁定文件与隐藏文件/目录不作为课程资料。

    需检查相对路径的每个组成部分（含父目录），如 .git/inner.pdf。
    """
    for part in path.relative_to(root).parts:
        if part.startswith("~$") or part.startswith("."):
            return True
    return False


def scan_course(
    courses_dir: Path,
    course_name: str,
    file_types: list[str],
    source_limit_warn: int | None = None,
) -> CourseManifest:
    """扫描 courses_dir/<course_name>/，返回资料清单。

    抛出：
        CourseNotFoundError —— 课程目录不存在
        NoCourseFilesError  —— 没有匹配类型的文件
    """
    courses_dir = Path(courses_dir)
    course_dir = courses_dir / course_name
    if not course_dir.is_dir():
        raise CourseNotFoundError(f"课程目录不存在：{course_dir}")

    wanted = {ext.lower() for ext in file_types}
    collected: list[CourseFile] = []
    for path in sorted(course_dir.rglob("*")):
        if _is_noise(path, course_dir):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in wanted:
            continue
        collected.append(
            CourseFile(
                path=path.resolve(),
                size_bytes=path.stat().st_size,
                category=_EXT_CATEGORY.get(path.suffix.lower(), "other"),
            )
        )

    if not collected:
        raise NoCourseFilesError(
            f"课程目录中没有可识别的资料文件（支持类型：{', '.join(sorted(wanted))}）：{course_dir}"
        )

    # 按相对路径排序，保证清单稳定
    collected.sort(key=lambda f: f.path.relative_to(course_dir).as_posix())
    manifest = CourseManifest(
        course_name=course_name,
        root=course_dir.resolve(),
        files=collected,
        source_limit_warn=source_limit_warn,
        total_size_bytes=sum(f.size_bytes for f in collected),
    )

    cats: dict[str, int] = {}
    for f in collected:
        cats[f.category] = cats.get(f.category, 0) + 1
    stats = ", ".join(f"{c}={n}" for c, n in sorted(cats.items()))
    logger.info("扫描完成：{} 共 {} 个文件（{}），{:.1f} MB",
                course_name, len(collected), stats, manifest.total_size_bytes / 1024 / 1024)
    if source_limit_warn is not None and len(collected) > source_limit_warn:
        logger.warning(
            "资料数 {} 超过告警阈值 {}（NotebookLM 免费版单 Notebook 上限 50），"
            "多余文件可能无法上传",
            len(collected),
            source_limit_warn,
        )
    return manifest


if __name__ == "__main__":  # 手动验证入口：python -m modules.file_manager <课程名>
    import sys

    from modules.config import load_config

    try:
        cfg = load_config()
        m = scan_course(
            cfg.paths.courses_dir,
            sys.argv[1],
            cfg.file_types,
            source_limit_warn=cfg.notebooklm.source_limit_warn,
        )
        print(m)
        for f in m.files:
            print(f"  [{f.category:>5}] {f.size_bytes:>10,} B  {f.path.name}")
    except FileManagerError as e:
        print(f"错误：{e}")
        sys.exit(1)
