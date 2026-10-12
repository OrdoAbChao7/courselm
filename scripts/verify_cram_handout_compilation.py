import sys
from pathlib import Path
import subprocess

from modules.latex_renderer import write_latex_document
from modules.handout_builder import build_handout
from modules.markdown_generator import render_doc

test_dir = Path("output/test_cram_course")
test_dir.mkdir(parents=True, exist_ok=True)
md_dir = test_dir / "md"
chapters_dir = md_dir / "chapters"
chapters_dir.mkdir(parents=True, exist_ok=True)

intro_content = """# 绪论

## 考前突击提分使用指南
本书专为《高等数学（上）》期末考试突击自学者设计，风格全面借鉴经实战检验有效的“蜂考突击课”。

### 一、五步提分闭环
1. **看考情速览**：明确本章考点重要程度与分值占比，决定复习优先级。
2. **背速记口诀**：极简核心公式与解题心法，降低记忆负担。
3. **跟做标准例题**：吃透基础经典题的规范分步解法，掌握考场拿分步骤。
4. **警惕避坑提醒**：避开考场常见扣分陷阱与易混淆概念。
5. **过关练习自测**：独立完成“自己试”与“课时过关练习”，查漏补缺。

### 二、冲刺时间分配建议
- **考前 48 小时**：攻克第 1、2、3 章（极限计算、导数应用、不定积分），拿下 60 分基础盘。
- **考前 24 小时**：针对必考大题题型强化训练，回看错题与速记口诀。
"""

chapter1_content = """# 第1章 极限、连续与间断点

## 考情速览
| 考点 / 题型 | 重要程度 | 预计分值 | 常见题型 |
| :--- | :--- | :--- | :--- |
| 1. 函数定义域与解析式 | ★★ | 0~3分 | 选择、填空 |
| 2. 未定式极限求法 | 必考 | 6~10分 | 选择、填空、大题 |
| 3. 函数连续性与间断点 | 必考 | 3~6分 | 选择、填空、大题 |

提分策略：本章重点是“极限计算”，掌握洛必达法则与等价无穷小口诀，期末卷面必拿 10 分以上。

## 题型一：0比0型未定式极限
### 核心考点与速记口诀
- 常用等价无穷小（当 $x \\to 0$ 时）：
  $$\\sin x \\sim x, \\quad \\tan x \\sim x, \\quad 1 - \\cos x \\sim \\frac{1}{2}x^2, \\quad e^x - 1 \\sim x, \\quad \\ln(1+x) \\sim x$$
- **速记口诀**：**等价代换抓乘除，加减泰勒防陷阱；洛必达先看导数，未定方可用**。
- 适用条件：只有在 $\\frac{0}{0}$ 或 $\\frac{\\infty}{\\infty}$ 型且导数存在时才可用洛必达法则。

### 标准例题
求极限 $\\lim_{x \\to 0} \\frac{\\tan x - \\sin x}{x^3}$。[真题·2023]

### 跟着做
1. **判断极限类型**：代入 $x=0$，分子 $\\tan 0 - \\sin 0 = 0$，分母 $0^3 = 0$，属于典型的 $\\frac{0}{0}$ 型未定式。
2. **提取公因式变形**：
   $$\\tan x - \\sin x = \\tan x (1 - \\cos x)$$
3. **利用等价无穷小代换**：
   当 $x \\to 0$ 时，$\\tan x \\sim x$ 且 $1 - \\cos x \\sim \\frac{1}{2}x^2$。由于此处为因式乘积，可直接整体代换：
   $$\\lim_{x \\to 0} \\frac{\\tan x (1 - \\cos x)}{x^3} = \\lim_{x \\to 0} \\frac{x \\cdot \\frac{1}{2}x^2}{x^3}$$
4. **化简求得结果**：
   $$\\lim_{x \\to 0} \\frac{\\frac{1}{2}x^3}{x^3} = \\frac{1}{2}$$

### 避坑提醒
- **高频扣分点**：在加减法式子中直接替换部分项（例如把 $\\tan x - \\sin x$ 替换为 $x - x = 0$）会导致完全错误的结果！
- **考场经验**：遇到三角函数差式，优先提取因式化为乘积，再用等价无穷小，比直接求导快三倍。

### 自己试
计算极限 $\\lim_{x \\to 0} \\frac{\\sin x - x}{x^3}$。
提示：无法直接因式分解，请使用洛必达法则求导一次，或利用泰勒展开 $\\sin x = x - \\frac{x^3}{6} + o(x^3)$。

#### 解答
1. 代入为 $\\frac{0}{0}$ 型。
2. 分子分母求导：$\\lim_{x \\to 0} \\frac{\\cos x - 1}{3x^2} = \\lim_{x \\to 0} \\frac{-\\frac{1}{2}x^2}{3x^2} = -\\frac{1}{6}$。
易错：注意 $\\cos x - 1 = -(1 - \\cos x) \\sim -\\frac{1}{2}x^2$ 负号切勿遗漏。

## 课时过关练习
1. 求函数 $f(x) = \\frac{x^2 - 1}{x^2 - 3x + 2}$ 的全部间断点并判断类型。
提示：找分母为零的点，分别求左、右极限。

#### 解答
分母分解因式 $(x-1)(x-2)=0$，得可疑间断点 $x=1, x=2$。
- 在 $x=1$ 处：$\\lim_{x \\to 1} \\frac{(x-1)(x+1)}{(x-1)(x-2)} = \\lim_{x \\to 1} \\frac{x+1}{x-2} = -2$，极限存在，故 $x=1$ 为**可去间断点**（第一类）。
- 在 $x=2$ 处：$\\lim_{x \\to 2} \\frac{x+1}{x-2} = \\infty$，极限为无穷大，故 $x=2$ 为**无穷间断点**（第二类）。
做错回看考点三连续性与间断点定义。
"""

(md_dir / "00-绪论.md").write_text(render_doc(intro_content, "高等数学上", "绪论", ["复习"]), encoding="utf-8")
(chapters_dir / "01-极限与连续.md").write_text(render_doc(chapter1_content, "高等数学上", "章节复习内容", ["复习"]), encoding="utf-8")

print("Building handout...")
res = build_handout("test_cram_course", Path("output"), courses_dir=Path("courses"))
print(f"Manuscript built: {res.manuscript_path}")
print(f"LaTeX generated: {res.tex_path}")

print("Rendering LaTeX to document...")
write_latex_document(
    res.manuscript_path.read_text(encoding="utf-8"),
    res.tex_path,
    "高等数学上·期末突击复习讲义",
    subtitle="蜂考突击课风格 · 考情直击 · 口诀速记 · 题型精讲 · 课时过关",
)

print("Compiling with xelatex...")
tex_file = res.tex_path
cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_file.name]
proc = subprocess.run(cmd, cwd=tex_file.parent, capture_output=True, text=True, encoding="utf-8", errors="replace")
if proc.returncode != 0:
    print("LaTeX compilation failed!")
    print(proc.stdout[-2000:])
    sys.exit(1)

pdf_path = tex_file.with_suffix(".pdf")
if pdf_path.is_file():
    print(f"SUCCESS: PDF generated successfully at {pdf_path} (Size: {pdf_path.stat().st_size} bytes)")
else:
    print("FAILED: PDF not found!")
    sys.exit(1)
