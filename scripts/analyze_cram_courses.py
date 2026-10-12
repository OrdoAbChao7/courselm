import sys
import pymupdf
import pathlib

base_dir = pathlib.Path("突击课")
output_path = pathlib.Path("docs/cram_course_feature_analysis.md")
output_path.parent.mkdir(parents=True, exist_ok=True)

# Select a representative cross-section of subjects
subjects = [
    "大学数学/高数上【蜂考突击课】.pdf",
    "大学数学/线性代数【蜂考突击课】.pdf",
    "大学数学/概率论与数理统计【蜂考突击课】.pdf",
    "计算机/C语言【蜂考突击课】.pdf",
    "计算机/操作系统【蜂考突击课】.pdf",
    "计算机/数据结构【蜂考突击课】.pdf",
    "电气通信/电路【蜂考突击课】.pdf",
    "大学物理/电磁学【蜂考突击课】.pdf",
    "经济学/微观经济学【蜂考突击课】.pdf",
]

lines = []
lines.append("# 蜂考突击课讲义特征深度分析报告\n")
lines.append("## 一、样本讲义结构分析\n")

extracted_insights = []

for sub_path in subjects:
    pdf_file = base_dir / sub_path
    if not pdf_file.exists():
        continue
    doc = pymupdf.open(str(pdf_file))
    subject_name = pdf_file.stem
    category = pdf_file.parent.name
    
    lines.append(f"### 【{category}】{subject_name}\n")
    lines.append(f"- **总页数**：{len(doc)} 页")
    
    # TOC
    toc = doc.get_toc()
    lines.append(f"- **目录结构**（前 12 项）：")
    if toc:
        for item in toc[:12]:
            lines.append(f"  - Level {item[0]}: {item[1]} (P{item[2]})")
    else:
        lines.append("  - （无嵌入 PDF 目录）")
    
    # Sample first 3 content pages (skip cover pages)
    sample_texts = []
    for page_idx in range(min(len(doc), 6)):
        t = doc[page_idx].get_text().strip()
        if len(t) > 100:
            sample_texts.append((page_idx + 1, t))
            if len(sample_texts) >= 2:
                break
                
    lines.append("\n**正文切片抽样**：\n")
    for pno, txt in sample_texts:
        lines.append(f"#### 第 {pno} 页内容切片：")
        lines.append("```text")
        # take first 40 lines
        slice_lines = txt.splitlines()[:40]
        lines.append("\n".join(slice_lines))
        lines.append("```\n")

with open(output_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Analysis written to {output_path}")
