"""CourseLM 批量讲义重制流水线（支持原始题图提取、智能匹配与讲义重构）。

对 output 目录下所有课程讲义进行系统化重制：
1. 自动关联 courses/ 与 突击课/ 中的真实源资料 PDF；
2. 提取 300 DPI 原始嵌入题图与矢量图元，自动剔除封面装饰图与版权声明；
3. 执行图文多维特征比对与缺图审查；
4. 将匹配题图规范注入 Markdown 章节；
5. 调用 build_handout、write_latex_document 与 XeLaTeX 重新编译最终交付 PDF。
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pypdfium2 as pdfium
from loguru import logger

from modules.config import load_config
from modules.figure_extractor import FigureExtractor
from modules.figure_matcher import FigureMatcher, _calculate_lexical_similarity
from modules.figure_models import (
    BoundingBox,
    CoordinateSystem,
    ExtractionType,
    FigureAsset,
    FigureManifest,
    ReviewStatus,
)
from modules.handout_builder import build_handout
from modules.latex_renderer import write_latex_document
from main import compile_latex

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
COURSES_DIR = ROOT / "courses"
CRAM_DIR = ROOT / "突击课"


# Course to source materials mapping rules
SOURCE_MAPPINGS: Dict[str, List[Path]] = {
    "信号与系统": [
        CRAM_DIR / "电气通信" / "信号与系统【蜂考突击课】.pdf",
        COURSES_DIR / "信号与系统" / "真题" / "往年真题1 信号与系统A 试题及答案【毫厘】.pdf",
    ],
    "通信原理": [
        COURSES_DIR / "通信原理" / "1.1 通信基本概念.pdf",
        COURSES_DIR / "通信原理" / "1.2 通信系统的组成.pdf",
    ],
    "微处理器": [
        COURSES_DIR / "微处理器" / "电子信息技术实验讲义.pdf",
        COURSES_DIR / "微处理器" / "第一章.pdf",
    ],
    "电动力学": [
        CRAM_DIR / "大学物理" / "电磁学【蜂考突击课】.pdf",
        COURSES_DIR / "电动力学" / "2018-2019-2 电磁场与电磁波D 期末试卷.pdf",
    ],
    "物理光学": [
        CRAM_DIR / "大学物理" / "光学【蜂考突击课】.pdf",
    ],
    "固体物理": [
        COURSES_DIR / "固体物理" / "固体物理复习-new.pdf",
        COURSES_DIR / "固体物理" / "第1章第1讲_绪论及晶体常见结构和相关概念.pdf",
    ],
    "量子力学": [
        COURSES_DIR / "量子力学" / "格里菲斯量子力学概论答案 solution manual (david griffiths , 格里菲斯) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
    ],
    "量子力学-授课版": [
        COURSES_DIR / "量子力学-授课版" / "Chapter1.pdf",
        COURSES_DIR / "量子力学-授课版" / "Chapter2.pdf",
    ],
    "高等代数": [
        CRAM_DIR / "大学数学" / "线性代数【蜂考突击课】.pdf",
        COURSES_DIR / "高等代数" / "作业纸-第1章 行列式.pdf",
    ],
    "数学分析": [
        CRAM_DIR / "大学数学" / "高数上【蜂考突击课】.pdf",
        COURSES_DIR / "数学分析" / "2021-2022-1 数学分析1 (A卷) 试题及答案【尽兴】.pdf",
    ],
    "大学生数学竞赛": [
        COURSES_DIR / "大学生数学竞赛" / "大学生数学竞赛教程 .pdf",
        COURSES_DIR / "大学生数学竞赛" / "1、全国大学生数学竞赛【1-17届真题】非数类" / "第11届全国大学生数学竞赛非数学类决赛试卷（2020年） .pdf",
    ],
}


def is_decorative_or_cover_image(asset: FigureAsset, page_w: float, page_h: float) -> bool:
    """Check if an image is a decorative cover illustration or tiny icon."""
    # 1. Page 1 or 2 with large area (cover illustration)
    if asset.page_index <= 2:
        area_ratio = (asset.width * asset.height) / ((page_w * 300 / 72) * (page_h * 300 / 72) + 1e-5)
        if area_ratio > 0.35:
            return True
        if "封面" in asset.caption or "版权" in asset.caption:
            return True
        if "独家编辑" in asset.adjacent_text or "律师声明" in asset.adjacent_text:
            return True

    # 2. Extremely small icon / spacer (< 60 px in either dim)
    if asset.width < 60 or asset.height < 60:
        return True

    # 3. Full-bleed background on any page
    if asset.bbox:
        box_area = (asset.bbox.x1 - asset.bbox.x0) * (asset.bbox.y1 - asset.bbox.y0)
        if box_area > 0.85:
            return True

    return False


def extract_course_figures(course_name: str, course_dir: Path, source_pdfs: List[Path]) -> FigureManifest:
    """Extract figures for a specific course into output/<course>/figures/."""
    figures_dir = course_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = figures_dir / "manifest.json"

    manifest = FigureManifest.load(manifest_path, task_id=f"course_{course_name}", course=course_name)
    extractor = FigureExtractor(target_dpi=300)

    for pdf_path in source_pdfs:
        if not pdf_path.is_file():
            continue
        try:
            doc = pdfium.PdfDocument(pdf_path)
            total_pages = len(doc)
            # Scan reasonable page range for performance (max 30 pages per source)
            pages_to_scan = min(30, total_pages)
            raw_assets = extractor.extract_from_pdf(
                pdf_path,
                figures_dir,
                task_id=f"course_{course_name}",
                rel_source_path=pdf_path.name,
                manifest=manifest,
                max_pages=pages_to_scan,
                extract_vectors=True,
            )

            # Filter out decorative cover images
            for asset in raw_assets:
                p_idx = max(0, min(total_pages - 1, asset.page_index - 1))
                page = doc[p_idx]
                pw, ph = page.get_size()
                if is_decorative_or_cover_image(asset, pw, ph):
                    asset.status = ReviewStatus.REJECTED
                # Passing a size filter never approves academic meaning or a
                # question binding. New extraction candidates remain pending.

        except Exception as e:
            logger.warning(f"Error extracting figures from {pdf_path.name}: {e}")

    manifest.save()
    return manifest


def enhance_markdown_with_figures(course_dir: Path, manifest: FigureManifest) -> int:
    """Inspect explicit bindings; leave source Markdown untouched.

    Actual insertion is performed by build_handout through the same integrity
    policy. Neither keywords nor lexical scores authorize a new binding.
    """
    from modules.figure_integrity import prepare_markdown
    chapters_dir = course_dir / "md" / "chapters"
    report = []
    inserted = 0
    for md_file in sorted(chapters_dir.glob("*.md")):
        result = prepare_markdown(
            md_file.read_text(encoding="utf-8"),
            md_file.relative_to(course_dir / "md").as_posix(), manifest,
            figure_root=course_dir, source_root=COURSES_DIR / course_dir.name)
        inserted += result.inserted
        report.extend(result.omissions)
    figures_dir = course_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "binding-report.json").write_text(
        json.dumps({"eligible": inserted, "omissions": report}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return inserted


def remake_course_handout(course_name: str) -> Dict[str, any]:
    """Remake a single course handout with source figures and recompile PDF."""
    course_dir = OUTPUT_DIR / course_name
    if not course_dir.is_dir():
        return {"course": course_name, "status": "SKIPPED", "reason": "Directory not found"}

    print(f"\n=======================================================")
    print(f"正在重制讲义: 《{course_name}》")
    print(f"=======================================================")

    start_t = time.time()
    source_pdfs = list(SOURCE_MAPPINGS.get(course_name, []))
    # Also include any PDFs in courses/<course_name>
    c_source_dir = COURSES_DIR / course_name
    if c_source_dir.is_dir():
        for p in list(c_source_dir.glob("*.pdf"))[:5]:
            if p not in source_pdfs:
                source_pdfs.append(p)

    valid_sources = [p for p in source_pdfs if p.is_file()]
    print(f"  [1/4] 源资料分析: 找到 {len(valid_sources)} 个可用 PDF 资料")

    # Step 1: Extract figures
    manifest = extract_course_figures(course_name, course_dir, valid_sources)
    confirmed_figs = [f for f in manifest.figures.values() if f.status == ReviewStatus.CONFIRMED]
    print(f"  [2/4] 题图抽取完成: 共抽取 {len(manifest.figures)} 张，历史已标记图片 {len(confirmed_figs)} 张（仍需有效题目绑定）")

    # Step 2: Smart matching & Markdown enhancement
    inserted_count = enhance_markdown_with_figures(course_dir, manifest)
    print(f"  [3/4] 原图绑定检查: {inserted_count} 处绑定可复用，未改写源章节")

    # Step 3: Rebuild handout and compile XeLaTeX
    print(f"  [4/4] 调用 HandoutBuilder 与 XeLaTeX 重新编译讲义...")
    cfg = load_config()
    try:
        build_result = build_handout(
            course_name,
            OUTPUT_DIR,
            courses_dir=COURSES_DIR,
        )
        if build_result.missing_inputs:
            raise ValueError("讲义缺少输入：" + "、".join(build_result.missing_inputs))
        manuscript = build_result.manuscript_path.read_text(encoding="utf-8")
        write_latex_document(
            manuscript,
            build_result.tex_path,
            f"{course_name}{build_result.template.title_suffix}",
            subtitle=build_result.template.subtitle,
            style=build_result.template.latex,
        )

        ok, log = compile_latex(build_result.tex_path)
        if not ok:
            print(f"  [!] 编译遇到警告或错误: {log[:300]}")
            return {
                "course": course_name,
                "status": "FAILED",
                "duration": round(time.time() - start_t, 1),
                "figures_total": len(manifest.figures),
                "figures_confirmed": len(confirmed_figs),
                "figures_inserted": inserted_count,
                "error": log[-500:],
            }

        # Copy to release
        release_dir = course_dir / "release"
        release_dir.mkdir(parents=True, exist_ok=True)
        final_pdf = release_dir / f"{course_name}-期末复习讲义.pdf"
        shutil.copy2(build_result.tex_path.with_suffix(".pdf"), final_pdf)

        doc = pdfium.PdfDocument(final_pdf)
        pdf_pages = len(doc)
        pdf_size_kb = round(final_pdf.stat().st_size / 1024, 1)

        print(f"  [成功] 《{course_name}》讲义重制完成！")
        print(f"         产物: {final_pdf.name} ({pdf_pages} 页, {pdf_size_kb} KB)")

        return {
            "course": course_name,
            "status": "SUCCESS",
            "duration": round(time.time() - start_t, 1),
            "figures_total": len(manifest.figures),
            "figures_confirmed": len(confirmed_figs),
            "figures_inserted": inserted_count,
            "pdf_pages": pdf_pages,
            "pdf_size_kb": pdf_size_kb,
            "pdf_path": str(final_pdf),
        }

    except Exception as e:
        print(f"  [失败] 重制发生异常: {e}")
        return {
            "course": course_name,
            "status": "ERROR",
            "duration": round(time.time() - start_t, 1),
            "error": str(e),
        }


def main():
    target_courses = [
        "信号与系统",
        "通信原理",
        "微处理器",
        "电动力学",
        "物理光学",
        "固体物理",
        "量子力学",
        "量子力学-授课版",
        "高等代数",
        "数学分析",
        "大学生数学竞赛",
    ]

    print("\n" + "=" * 65)
    print("  CourseLM 讲义批量重制系统 · 原始题图集成与讲义重构")
    print("=" * 65)
    print(f"目标课程清单 ({len(target_courses)} 门): {', '.join(target_courses)}\n")

    results = []
    for cname in target_courses:
        res = remake_course_handout(cname)
        results.append(res)

    print("\n" + "=" * 65)
    print("  CourseLM 讲义批量重制完成 · 综合审计报告")
    print("=" * 65)
    print(f"{'课程名称':<14} | {'状态':<6} | {'耗时':<6} | {'图库总数':<8} | {'有效题图':<8} | {'插入题图':<8} | {'讲义页数':<8} | {'PDF大小'}")
    print("-" * 85)

    for r in results:
        status = r.get("status", "UNKNOWN")
        dur = f"{r.get('duration', 0)}s"
        total = r.get("figures_total", "-")
        conf = r.get("figures_confirmed", "-")
        ins = r.get("figures_inserted", "-")
        pages = f"{r.get('pdf_pages', '-')} 页"
        sz = f"{r.get('pdf_size_kb', '-')} KB"
        cname = r["course"]
        print(f"{cname:<12} | {status:<6} | {dur:<6} | {total:<8} | {conf:<8} | {ins:<8} | {pages:<8} | {sz}")

    # Write summary JSON
    report_file = OUTPUT_DIR / "batch_remake_report.json"
    report_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[+] 审计数据已保存至: {report_file}")


if __name__ == "__main__":
    main()
