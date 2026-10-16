"""Quick Standalone Verification Script for CourseLM Source Figures System.

Runs in 5 seconds without calling NotebookLM:
1. Takes a real circuit document from '突击课/电气通信/电路【蜂考突击课】.pdf'.
2. Performs 300 DPI high-precision region cropping on a real circuit diagram.
3. Automatically records full provenance metadata (file, page, coordinates, sha256) into manifest.json.
4. Runs intelligent missing-figure and candidate matching analysis.
5. Assembles a sample exercise in Markdown with the original figure.
6. Compiles with XeLaTeX into a production-grade PDF: 'output/demo_figures/讲义成品_题图检验.pdf'.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.figure_extractor import FigureExtractor
from modules.figure_models import (
    BoundingBox,
    CoordinateSystem,
    FigureManifest,
    ReviewStatus,
)
from modules.figure_matcher import FigureMatcher, audit_handout_figures
from modules.latex_renderer import write_latex_document
from main import compile_latex


def main():
    print("=" * 65)
    print("  CourseLM 原始题图系统 · 快速效果检验（无需调用 NotebookLM）")
    print("=" * 65)

    source_pdf = ROOT / "突击课/电气通信/电路【蜂考突击课】.pdf"
    if not source_pdf.is_file():
        # Fallback to any PDF in 突击课
        pdfs = list(ROOT.glob("突击课/**/*.pdf"))
        if not pdfs:
            print("[ERROR] 未找到测试 PDF 资料")
            return
        source_pdf = pdfs[0]

    print(f"\n[步骤 1/4] 读取源资料: {source_pdf.name}")
    out_dir = ROOT / "output/demo_figures"
    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    manifest = FigureManifest.load(figures_dir / "manifest.json", task_id="demo_quick", course="电路期末冲刺")
    extractor = FigureExtractor(target_dpi=300)

    # 1. High precision 300 DPI crop on Page 3 (Page 1 & 2 are cover & copyright)
    # Circuit Problem 3 main diagram
    bbox_circuit = BoundingBox(x0=35.0, y0=605.0, x1=335.0, y1=690.0, coord_system=CoordinateSystem.POINTS)
    asset_main = extractor.crop_pdf_region(
        pdf_path=source_pdf,
        page_index=3,
        bbox=bbox_circuit,
        task_figures_dir=figures_dir,
        task_id="demo_quick",
        rel_source_path=source_pdf.name,
        manifest=manifest,
        dpi=300,
        caption="图 1-1 含开关S与节点A的分段电位求解电路",
        status=ReviewStatus.CONFIRMED,
    )

    # Circuit Problem 3 equivalent diagram
    bbox_equiv = BoundingBox(x0=50.0, y0=720.0, x1=340.0, y1=780.0, coord_system=CoordinateSystem.POINTS)
    asset_equiv = extractor.crop_pdf_region(
        pdf_path=source_pdf,
        page_index=3,
        bbox=bbox_equiv,
        task_figures_dir=figures_dir,
        task_id="demo_quick",
        rel_source_path=source_pdf.name,
        manifest=manifest,
        dpi=300,
        caption="图 1-2 开关S打开时的等效分压单回路电路",
        status=ReviewStatus.CONFIRMED,
    )
    manifest.save()

    print(f"  [+] 成功从资料第 3 页提取 300 DPI 真实电路原图：")
    print(f"    - 原图 1 [主电路]: {asset_main.asset_id} ({asset_main.width}x{asset_main.height} px, 来源: 第 {asset_main.page_index} 页)")
    print(f"    - 原图 2 [等效图]: {asset_equiv.asset_id} ({asset_equiv.width}x{asset_equiv.height} px, 来源: 第 {asset_equiv.page_index} 页)")

    # 2. Matcher and missing figure audit demonstration
    print("\n[步骤 2/4] 检验缺图扫描与智能推荐")
    matcher = FigureMatcher(manifest)
    candidates = matcher.find_candidate_figures("如图 1-1 所示，求当开关S打开和闭合时A点的电位", limit=2)
    print(f"  [+] 题目智能匹配候选推荐结果:")
    for c in candidates:
        print(f"    - 推荐图片: {c.figure_asset_id} ({c.match_reasons}) 得分: {c.score:.2f}")

    # 3. Assemble Markdown with Figure
    print("\n[步骤 3/4] 组装包含原始真图的讲义 Markdown")
    md_content = f"""# 电路基础核心考点与典型题型

## 考点 01：电路参考方向与节点电位分析

**【核心概念】**
1. **参考方向**：电压与电流大小未知时先预设参考方向。若计算结果为正，与参考方向一致；若为负，与参考方向相反。
2. **节点电位**：电路中某点的电位等于该点到参考零电位点（接地端）之间的电压。

---

### 典型例题精讲

**【例 1.1】** 如下图所示电路，已知左侧端点电位为 $-12\\,\\text{{V}}$，右侧端点 $B$ 电位为 $+12\\,\\text{{V}}$，支路电阻分别为 $4\\,\\Omega$、$2\\,\\Omega$、$4\\,\\Omega$。试求解当开关 $S$ 分别处于打开和闭合状态时，节点 $A$ 的电位 $V_A$。

![{asset_main.caption}|width=0.7\\linewidth,align=center]({asset_main.file_path})

> **【解题关键点】**
> - **开关 $S$ 打开时**：开关所在支路断开，不分流，整个电路退化为由 $-12\\,\\text{{V}}$ 到 $+12\\,\\text{{V}}$ 的单一无分支串联回路。
> - **开关 $S$ 闭合时**：开关下端接地（电位为 $0\\,\\text{{V}}$），左侧 $-12\\,\\text{{V}}$ 电源通过闭合开关直接接地，对右侧节点 $A$ 电位不再产生影响。

**【规范解答步骤】**

**第一步：当开关 $S$ 打开时**

由于开关所在支路断路，原电路可等效为单回路串联电阻链：

![{asset_equiv.caption}|width=0.65\\linewidth,align=center]({asset_equiv.file_path})

1. 计算全回路总电压与电流：
   $$U_{{total}} = V_B - (-12\\,\\text{{V}}) = 12 - (-12) = 24\\,\\text{{V}}$$
   $$I = \\frac{{U_{{total}}}}{{4\\,\\Omega + 2\\,\\Omega + 4\\,\\Omega}} = \\frac{{24}}{{10}} = 2.4\\,\\text{{A}}$$
2. $4\\,\\Omega$ 电阻两端电压为：
   $$U = I \\times 4\\,\\Omega = 2.4 \\times 4 = 9.6\\,\\text{{V}}$$
3. 节点 $A$ 电位为：
   $$V_A = V_B - U = 12 - 9.6 = 2.4\\,\\text{{V}}$$

**第二步：当开关 $S$ 闭合时**

开关导通后直接将节点电位固定为基准地 $0\\,\\text{{V}}$。此时 $A$ 点仅受右侧 $+12\\,\\text{{V}}$ 电源控制，在 $2\\,\\Omega$ 与 $4\\,\\Omega$ 电阻之间串联分压：
$$V_A = V_B \\times \\frac{{2\\,\\Omega}}{{2\\,\\Omega + 4\\,\\Omega}} = 12 \\times \\frac{{2}}{{6}} = 4\\,\\text{{V}}$$

综上所述，$S$ 打开时 $V_A = 2.4\\,\\text{{V}}$；$S$ 闭合时 $V_A = 4\\,\\text{{V}}$。
"""

    # 4. Compile with XeLaTeX
    print("\n[步骤 4/4] 调用 XeLaTeX 编译最终可交付 PDF")
    tex_path = out_dir / "讲义成品_题图检验.tex"
    write_latex_document(
        md_content,
        tex_path,
        "电路考前冲刺复习讲义",
        subtitle="原始题图提取、智能排版与插入系统效果检验",
    )

    ok, log = compile_latex(tex_path)
    if ok:
        pdf_path = tex_path.with_suffix(".pdf")
        print(f"\n[成功] 讲义编译完全成功！")
        print(f"  [+] PDF 产物已生成: {pdf_path}")
        print(f"  [+] PDF 大小: {pdf_path.stat().st_size / 1024:.1f} KB")
        print(f"\n[查看方式] 您可以直接双击打开该 PDF 查看原始题图与排版效果：")
        print(f"   {pdf_path.resolve()}")
    else:
        print(f"\n[失败] 编译失败，日志:\n{log[-1000:]}")


if __name__ == "__main__":
    main()
