"""file_manager 单元测试。

用临时目录构造课程资料结构，验证扫描、分类、忽略规则与错误路径。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.file_manager import (
    CourseFile,
    CourseNotFoundError,
    NoCourseFilesError,
    scan_course,
)

DEFAULT_TYPES = [".pdf", ".ppt", ".pptx", ".doc", ".docx", ".jpg", ".jpeg", ".png"]


def make_course(root: Path, name: str = "电磁场") -> Path:
    course_dir = root / "courses" / name
    course_dir.mkdir(parents=True)
    return course_dir


def put(course: Path, rel: str, size: int = 1) -> None:
    """在课程目录下写入一个文件，自动创建父目录。"""
    target = course / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * size)


class TestScanRecognition:
    """识别与分类。"""

    def test_categories_and_recursive(self, tmp_path: Path) -> None:
        course = make_course(tmp_path)
        put(course, "教材.pdf", 10)
        put(course, "PPT/第1讲.pptx", 20)
        put(course, "作业.docx", 5)
        put(course, "img/deep/图1.png", 1)

        manifest = scan_course(tmp_path / "courses", "电磁场", DEFAULT_TYPES)

        # 排序按相对路径 posix 字典序：PPT/… < img/… < 作业.docx < 教材.pdf
        assert [f.path.name for f in manifest.files] == ["第1讲.pptx", "图1.png", "作业.docx", "教材.pdf"]
        by_name = {f.path.name: f for f in manifest.files}
        assert by_name["教材.pdf"].category == "pdf"
        assert by_name["第1讲.pptx"].category == "ppt"
        assert by_name["作业.docx"].category == "doc"
        assert by_name["图1.png"].category == "image"
        assert manifest.total_size_bytes == 36
        assert manifest.course_name == "电磁场"

    def test_extension_case_insensitive(self, tmp_path: Path) -> None:
        course = make_course(tmp_path, "English")
        (course / "TEXTBOOK.PDF").write_bytes(b"xx")

        manifest = scan_course(tmp_path / "courses", "English", DEFAULT_TYPES)

        assert len(manifest.files) == 1
        assert manifest.files[0].category == "pdf"

    def test_unlisted_extension_ignored(self, tmp_path: Path) -> None:
        course = make_course(tmp_path)
        (course / "笔记.txt").write_text("x")  # 不在 file_types 中
        (course / "教材.pdf").write_bytes(b"x")

        manifest = scan_course(tmp_path / "courses", "电磁场", DEFAULT_TYPES)

        assert [f.path.name for f in manifest.files] == ["教材.pdf"]

    def test_custom_type_falls_into_other(self, tmp_path: Path) -> None:
        course = make_course(tmp_path)
        (course / "补充.txt").write_text("x")

        manifest = scan_course(tmp_path / "courses", "电磁场", DEFAULT_TYPES + [".txt"])

        assert manifest.files[0].category == "other"


class TestScanIgnore:
    """噪音文件忽略规则。"""

    def test_office_lock_and_hidden_files(self, tmp_path: Path) -> None:
        course = make_course(tmp_path)
        put(course, "教材.pdf")
        put(course, "~$教材.pdf")  # Office 锁定文件
        put(course, ".hidden.pdf")  # 隐藏文件
        put(course, ".git/inner.pdf")  # 隐藏目录

        manifest = scan_course(tmp_path / "courses", "电磁场", DEFAULT_TYPES)

        assert [f.path.name for f in manifest.files] == ["教材.pdf"]

    def test_directory_itself_not_listed(self, tmp_path: Path) -> None:
        course = make_course(tmp_path)
        (course / "PPT").mkdir()
        (course / "PPT" / "a.ppt").write_bytes(b"x")

        manifest = scan_course(tmp_path / "courses", "电磁场", DEFAULT_TYPES)

        assert all(f.path.is_file() for f in manifest.files)


class TestScanErrors:
    """错误路径。"""

    def test_course_not_found(self, tmp_path: Path) -> None:
        (tmp_path / "courses").mkdir()
        with pytest.raises(CourseNotFoundError, match="不存在"):
            scan_course(tmp_path / "courses", "量子力学", DEFAULT_TYPES)

    def test_no_matching_files(self, tmp_path: Path) -> None:
        course = make_course(tmp_path)
        (course / "笔记.txt").write_text("x")  # 存在但类型不匹配
        with pytest.raises(NoCourseFilesError, match="电磁场"):
            scan_course(tmp_path / "courses", "电磁场", DEFAULT_TYPES)

    def test_empty_course_dir(self, tmp_path: Path) -> None:
        make_course(tmp_path)
        with pytest.raises(NoCourseFilesError):
            scan_course(tmp_path / "courses", "电磁场", DEFAULT_TYPES)


class TestManifestModel:
    """数据模型本身的行为。"""

    def test_course_file_model_fields(self, tmp_path: Path) -> None:
        course = make_course(tmp_path)
        p = course / "教材.pdf"
        p.write_bytes(b"12345")

        f = CourseFile(path=p, size_bytes=5, category="pdf")

        assert f.path == p
        assert f.size_bytes == 5
        assert f.category == "pdf"

    def test_manifest_sorted_stable(self, tmp_path: Path) -> None:
        course = make_course(tmp_path)
        # 故意按乱序创建，扫描结果仍应按相对路径排序
        for name in ["b.pdf", "a.pdf", "PPT/z.pptx", "c.pdf"]:
            target = course / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")

        m1 = scan_course(tmp_path / "courses", "电磁场", DEFAULT_TYPES)
        m2 = scan_course(tmp_path / "courses", "电磁场", DEFAULT_TYPES)

        assert [f.path.name for f in m1.files] == [f.path.name for f in m2.files]
        rels = [str(f.path.relative_to(course).as_posix()) for f in m1.files]
        assert rels == sorted(rels)

    def test_course_name_path_traversal(self, tmp_path: Path) -> None:
        """测试防止通过 course_name 进行目录穿越。"""
        with pytest.raises(CourseNotFoundError, match="非法的课程名称"):
            scan_course(tmp_path, "../secret", [".pdf"])
        with pytest.raises(CourseNotFoundError, match="非法的课程名称"):
            scan_course(tmp_path, "a/b", [".pdf"])
        with pytest.raises(CourseNotFoundError, match="非法的课程名称"):
            scan_course(tmp_path, "C:\\Windows", [".pdf"])
