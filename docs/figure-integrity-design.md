# CourseLM 原始题图完整性与绑定重构方案

日期：2026-10-16。状态：完整架构设计；其中严格绑定、自动省略、结构安全和工作台构建校验已接入生产链路，见 `docs/figure-integrity-implementation.md`。通用源题识别、OCR 参数理解及跨格式完整图自动识别仍属于后续设计，不能据本文认定全部实现。

## 1. 目标、边界和结论

用户要求：只使用 PDF/PPT/DOCX 原资料中的图；不补画、不重绘、不擦除参数；准确性高于自动化；不同任务与课程之间物理隔离。成功标准是每张交付插图都有可核验来源、完整内容、明确目标题目和有效审核记录，无法确认的图片不进入正文。

不能诚实承诺任意文档上的自动视觉理解达到数学意义上的 100% 正确。能够确定性约束的是：来源范围、文件完整性、坐标变换、审核版本、插入结构和构建准入。语义正确性仍需证据与审核；默认严格模式下，每个“题目—来源位置—原图”绑定都人工核验。零错配是发布验收目标，模型高分不是正确性证明。

推荐架构：先识别源题目，再绑定源图，再生成保留来源 ID 的讲义，最后按结构节点插入。禁止从整门课图库中按生成文字挑选“最像的一张”。旧讲义只作为待对齐内容，缺少来源身份时进入复核，不用相似图补洞。

方案选择：

| 路线 | 收益 | 局限 | 决策 |
| --- | --- | --- | --- |
| 提高旧匹配阈值并加黑名单 | 改动少 | 没有来源身份，得分不校准，仍会稳定错配 | 仅可用于临时关闭自动插入，不能作为最终方案 |
| 直接使用多模态模型挑图 | 能理解图示类别 | 小数点、负号、拓扑、同型不同参数仍会误判 | 仅作候选分析器和反证检查器 |
| 源题目和图先绑定，结构化生成，严格构建门禁 | 可追溯、可拒绝、可审核、可回归 | 需要修改数据契约与审核工作流 | 推荐 |

## 2. 本地核查证据

本次以当前工作区为准。工作区已有大量未提交修改；本方案没有覆盖这些修改，也没有重制既有讲义。

### 2.1 已确认的代码根因

| 位置 | 现有行为 | 直接后果 |
| --- | --- | --- |
| `scripts/batch_remake_handouts.py:165` | 通过尺寸、封面等少量规则的资产一律改为 `CONFIRMED` | 图形存在被等同为内容正确、题目匹配正确 |
| 同文件 `:214` | 最高候选分数 `>= 0.18` 即插入 | 图注相似一项的 `0.20` 已足以过线 |
| 同文件 `:197–221` | 逐行找“波形、框图、电路”等词，取前后固定行窗口并拼图片字符串 | 表格行、题目标题、提示、客套话都可被当作锚点 |
| `modules/figure_matcher.py:82` | 词重合按较短集合归一，图注再重复计分 | 极短“电路”上下文可取得很高分；证据重复累计 |
| 同文件 `:121/:135` | 图号、例号使用裸子串包含 | `1` 可命中 `10`；不同资料的相同图号互相污染 |
| 同文件 `:106/:129` | 页码无源文件命名空间；页码模式允许仅“第 7” | 章节号可能被误当页码；不同文件相同页码加分 |
| 同文件 `:113` | 只排除 `REJECTED`，不核验任务身份 | 混入的其他任务资产仍可成为候选 |
| `modules/figure_extractor.py:149` | PDF 中分别提取 image 对象的 bitmap | 一张题图可能由底图、文字、线条、遮罩组成，单对象不等于完整可见图 |
| 同文件 `:792/:808` | 矢量框按固定 18 pt 聚类，要求宽和高都至少 2 pt | 水平/竖直细线可能被丢弃；连接关系断裂后只剩乘法器圆圈等碎片 |
| 同文件 `:413` | PPT 图片共用整页前 500 字上下文 | 同页不同题目和说明图无法区分 |
| 同文件 `:476` 附近 | 只在一页没有提取出图片时才导出矢量幻灯片 | 同页只要有 Logo，就可能漏掉真正的组合矢量题图 |
| 同文件 `:613/:631` | DOCX 媒体文件枚举序号写入 `page_index` | 媒体序号被伪装成页码；没有正文位置和题目归属 |
| `modules/figure_models.py:137` | occurrence 去重只看文件名和页码 | 同页同图多次使用的不同坐标被合并丢失 |
| 同文件 `:186` | 载入已有 manifest 时不核验期望任务和课程 | 调用方传入新身份也不会拦截旧 manifest |
| `modules/figure_matcher.py:248–286` | 多目录和 basename 回退找图；存在文件即可计为有效来源 | 未登记图、其他位置同名图、待审核图可被误放行 |
| `modules/handout_builder.py:29` | 批量复制整份 figures 目录，再按 basename 找文件 | 无关、旧版、拒绝图也进入构建目录，追溯关系弱化 |
| `modules/latex_renderer.py:432` | 仅把独占一行的图片转成 figure；图片会关闭当前列表 | 已经插进句子的标签不一定成为图片；列表归属可能改变 |
| `studio/workspace.py:192/:219` 附近 | build/deliver 没有把题图绑定审计作为强制门禁 | 编译成功、章节审核通过不能证明图片正确 |

补充：`_extract_text_in_rect` 当前实参顺序是 left/bottom/right/top，与核对的 PDFium 文档一致，不能仅因注释犹豫就认定这里传参颠倒。真正未解决的是统一坐标契约、旋转、CropBox、阅读顺序和题目区域划分。

### 2.2 已确认的产物与最小复现

原有 manifest：信号与系统 62 张资产；微处理器 192 张资产。

| 资产 | 核查结果 |
| --- | --- |
| `fig_ae7b52f54c7d` | `confirmed`，1056×347，28 个 occurrence；来源邻近文本为物理试题，水印可继承这些文本参加匹配 |
| `fig_19795253b663` | `confirmed`，688×405；实图为系统框图及输入输出波形组三联图，被放在单位三角脉冲反转平移练习附近 |
| `fig_6bfff686f693` | `confirmed`，207×207；实图为孤立乘法器，边缘导线被截断 |
| `fig_a475951fef46` | `confirmed`，256×256；实图为蓝色渐变色块，灰度标准差约 10.57，能通过现有 `<2.0` 空图规则 |
| `fig_cad4a1e8a620` | `confirmed`，388×143；上下文仅为 `I/O接口`，仍被用于自动配图 |

实际 Markdown 中，微处理器第 8 章表格的两条数据行之间存在渐变块图片；信号与系统第三章图片标签与“对应频域条件为：”处于同一行。仓库能证明当前产物存在该问题，但不能仅凭当前源码断言所有历史编辑的具体顺序。

使用临时目录调用现有代码，复现了：

1. task A 的 manifest 接受 task B 资产，匹配“电路”题目得分约 0.60。
2. `enhance_markdown_with_figures` 把图片直接写进两行 Markdown 表格之间。
3. 加载 manifest 时传入另一任务身份，返回值仍是原任务身份。
4. 创建未登记的 `unknown.png`，审计结果仍为 `valid_source_figures=1, audit_passed=True`。

这些是局部校验缺口，不等于已经证实某一次产物确实跨课程串图。实际目录布局已有部分隔离，需要补齐强制验证与构建限制。

现有测试命令：`python -m pytest tests/test_figure_system.py -q --disable-warnings --maxfail=1`。结果为 3 passed、1 failed，失败在 `test_extract_docx_and_pptx`：参考 PPTX 只有组合图形等对象，当前环境没有成功导出组合图形。该结果不能报告为“题图测试通过”。此外，项目 `.venv` 缺少 Pillow、NumPy、pypdfium2 等依赖，系统 Python 可以导入；`pyproject.toml` 尚未声明完整题图依赖。

## 3. 数据契约：原始对象、图资产和绑定分开

数据流：

```text
TaskInputSnapshot
  → SourceDocument + PageLayout + TextSpan/OCRSpan
  → SourceQuestion / SourceConcept
  → FigureOccurrence 候选区域
  → 原页面确定性渲染裁剪 → FigureBlob
  → CropReview：图是否完整、来源是否可信
  → FigureBinding：当前讲义题目是否确实需要这张图
  → BindingReview：逐对审核
  → DocumentIR 中插入 FigureBlock
  → 构建审计 → XeLaTeX → 成品版面复核 → 发布
```

所有坐标统一为**已处理页面旋转后的可见页面左上角、单位 pt**；bbox 使用 `[x0,y0,x1,y1]`，严格要求有限值、`0 <= x0 < x1 <= width`。像素与归一化坐标必须显式转换，禁止根据是否大于 1 猜单位；0 页、负页、反向框报错，不悄悄修正。

建议模型：

| 模型 | 必须保存的关键字段 |
| --- | --- |
| `TaskScope` | `task_id, course_id, run_id, source_snapshot_sha256` |
| `SourceDocument` | `document_id, relative_path, original_sha256, format, render_sha256, renderer_version` |
| `PageLayout` | `document_id, page_number, page_label, visible_size_pt, rotation, cropbox, source_to_visible_matrix` |
| `TextSpan` / `OCRSpan` | 文本、bbox、阅读顺序、列号、识别置信、原始证据位置；公式保留原串 |
| `SourceQuestion` | `source_question_id, document_id, page_spans, stem_spans, option_spans, solution_spans, facts` |
| `FigureBlob` | 字节 SHA256、编码、像素大小；仅负责内容去重，不带全局“已确认”语义 |
| `FigureOccurrence` | scope、document/page、bbox、题目归属、shape/XML 路径、crop transform、blob hash、多子图关系 |
| `CropReview` | occurrence 与 crop hash、判定类别、完整性、审核人、时间、pipeline version |
| `TargetQuestion` | 稳定 UUID、讲义节点 ID、题干 hash、源题 ID、是否改编、目标 facts |
| `FigureBinding` | target ID 与题干 hash、occurrence ID、角色、插入 slot、证据、参数核验、状态、审核记录 |
| `BuildReceipt` | 源资料快照、讲义 IR hash、bindings hash、每个图 hash、渲染器/模板版本、PDF hash |

同字节图片可以在**同一任务**内去重存储，但 occurrence、局部文字、来源题目和审核必须保留。其唯一键包括文档 hash、页码、bbox、shape/XML 路径，不能只用文件名+页码。匹配发生在 occurrence 层；不再只读重复图片的第一个页码和邻近文本。

绑定状态与资产状态独立：

```text
候选图：candidate → complete / incomplete / irrelevant / uncertain
图文绑定：proposed → needs_review → approved / rejected / stale
```

`complete` 不意味着可插到任何一道题。重新扫描不能自动恢复已拒绝的状态；题干、坐标、图像、来源文件、审核事实、解析策略任一改变，相关批准立即失效。

## 4. 按格式重做抽取，保留真正的可见原图

### 4.1 PDF

PDF 的 image/path/text/form 是绘制对象，不是“完整图”标签。`get_bitmap()` 可用于资产盘点，最终交付优先采用**原页面可见区域整体渲染裁剪**，把文字层、矢量线、位图底图、遮罩、箭头和子图标号一起保留。该流程是对原资料的渲染，不生成新学术内容。

1. 一页只做一次布局分析和 OCR，先识别多栏、题干、图注、表格、公式、页眉页脚。
2. 使用原生文字位置；扫描页或文字损坏区域追加 OCR。全页扫描图是输入容器，应继续区域检测，不能因占比大直接扔掉整页。
3. 题号、分值、选项、解析标题和阅读顺序用于切分 source question；跨页题保留多个 page span，不盲目合并页面像素。
4. 图形、文字标签、引线、箭头建邻接图。水平线、竖直线和细线允许零厚度 bbox，经显式膨胀后参与连接，不能用 `w>=2 and h>=2` 删除。
5. 组件合并受题目、栏、图注和留白边界约束；固定距离聚类只当候选生成器。使用尺度相对阈值、连通性和层级，不把 18 pt 当通用真值。
6. 输出 union 区域包含坐标轴端点、单位、极性、变量、子图编号。边界有线条截断、标签落在框外或多个竞争题干时标为 uncertain，扩大原图区域重新检测或转人工。
7. 复合图保留整体父区域，只有明确子图边界与归属时才可独立使用子图；父图已选时默认不再重复选择其碎片子区域。
8. 默认 300 DPI；细小参数可从矢量源提高渲染分辨率。低分辨率扫描不能通过放大声称恢复信息，参数不可读则复核。

坐标转换保存 3×3 仿射矩阵，处理 CropBox 偏移、页面旋转、显示缩放和 UI 选区。rounding 明确为左上取 floor、右下取 ceil；整图完整性审核后记录最终 bbox。旋转和透视修正只用于分析副本；交付图采用记录的原页面裁剪，禁止自动去水印、修补、锐化造字或超分辨率生成参数。

核对 PDFium 文档：它本身不提供完整布局分析；对象和文字 API 不能代替题目区域识别。渲染并行使用进程池，或给 PDFium 调用加互斥，不能直接多线程并行调用。

### 4.2 PPT/PPTX

递归读取 group、shape、connector、textbox、table、chart、picture，并处理组坐标变换、图片 crop、旋转、翻转和叠放关系。slide master/layout 中跨页固定位置的元素参与装饰识别。图片的原始 blob 与用户在幻灯片上看到的裁剪结果可能不同。

每页图片和矢量图形同时分析，不能“有图片就不导出图形”。先通过 PowerPoint 或固定版本 LibreOffice 导出该页可见 PDF，再按原 slide 几何区域裁剪复合图。保存原 PPT hash、转换后 PDF hash、渲染器与字体环境。不能固定导出为 1920×1080 而忽略实际幻灯片比例。没有可用渲染器时保留待审状态并报告，不把整页幻灯片直接当合格题图。

### 4.3 DOC/DOCX

读取 `document.xml` 的正文顺序、drawing 的 rId 与 relationships；包括 inline/anchor、文本框、组合 drawing、VML 兼容对象，追溯到段落、表格单元格及所属题目。区分页眉、页脚中的图标与正文。`word/media/*` 枚举仅作资源盘点，media 序号永远不能作为页码。

DOCX 是流式文档，准确分页需固定渲染环境。用 Word 或固定 LibreOffice 转 PDF 后记录真实页码和 bbox；转换存在版式变化时人工核验。无法渲染时只记录 XML 位置与 `page_number=null`，不得伪造页码。旧 `.doc/.ppt` 先用相应渲染器转换，不能直接交给只支持 OOXML 的解析器并吞掉异常。

## 5. 质量过滤与“完整学术图”判定

采用多标签分类：`academic_diagram / academic_photo / data_table / formula / text_strip / logo_watermark / decoration / background / fragment / unknown`，同时输出结构完整性。题目需要的表格或照片不是天然垃圾，但走明确的表格/照片来源绑定，不进入通用题图池。

| 类型 | 分析信号 | 安全处理 |
| --- | --- | --- |
| 空白、纯色、渐变 | alpha 合成后的可见色彩、局部方差、边缘密度、主色占比、低阶渐变拟合残差 | 高确定无内容时拒绝；灰度 std 只能作一个特征 |
| 空边框、按钮框 | 边缘仅在外圈、内部缺乏文字/连接线、重复的圆角/阴影/渐变模板 | 装饰候选；若与题目电路元件等存在歧义则复核 |
| Logo、水印 | 跨页重复 hash/pHash、稳定页边位置、绘制层级、机构文字、相同字体图案 | 多信号确认后拒绝；重复本身不足，因为真图也可能复用 |
| 整页背景 | 版面占比、底层 z-order、跨页模板重复 | 与扫描页容器区分；扫描页继续分割 |
| 文字条、公式截图 | OCR 长行、基线排列、与题干文字重合、几乎无图形结构 | 路由为文本/公式，OCR 不确定则保留证据待审 |
| 排版表格 | 单元格网格、行列关系、OCR 分布 | 路由表格；真正题设数据表可作为已绑定的表格块交付 |
| 孤立乘法器、运放等 | 小结构、边界截断导线、无完整输入输出、属于更大 parent figure | 合并父区域或复核；不能单靠像素尺寸或符号类别一刀切 |
| 无关照片 | 场景语义、源页面角色、与题目无直接引用 | 不参与习题配图；物理实验/晶体照片有明确题设引用时保留 |

所谓完整，是相对于题目角色成立：一张单个运放符号也可能是“识别元件”的完整题图；一个 207px 图也可能很清晰。自动拒绝应依靠“被切断的连接、缺失参数和父子图关系”等证据，不能靠“小”“文字多”“有圆圈”直接定性。

完整性审核至少检查：题目要求的所有子图齐全；连接和坐标轴无截断；关键标签和单位齐全；原页可见范围一致；不含另一题的图；没有遮挡造成的参数不可读。分类模型和拓扑分析都只能提供证据，不构成绝对证明。

原图内容含水印时允许保留水印的原始裁剪；无法避开水印就保持原样并审核可读性。禁止擦除水印后补画被遮挡参数。

## 6. 源题身份、参数和双向约束

### 6.1 候选集合先做硬限制

候选必须来自当前 task/run 快照允许的源文档、当前源题及其明确图号引用。图号键为 `(document_id, section_id, figure_number)`；题号键为 `(document_id, exam_version, section_id, question_number)`。页码只是位置属性，不能独立授权配图。

源题不存在、讲义为自由生成例题、仅有“老师课件”字样、只有章节名或泛化知识点时，不自动绑定。若改编了参数或函数定义，即使源图外观相同也先停止绑定；只有人工逐项确认仍适用后才能采用原图。完全新编题没有匹配原图时用文字题，或标记缺少原始配图。

在 `prompt_runner` 上游增加源题/图 catalog，生成器输出 target ID 与 source question ID。LLM 输出的 ID 不是证明：服务器验证 ID 存在、范围一致、题干与事实一致，再决定是否批准。若 NotebookLM 无法可靠回传来源身份，该题进入复核；不恢复模糊搜索自动配图。

### 6.2 结构化事实和冲突检测

OCR 保留原始串与证据 bbox；归一化生成如下类型的事实：

```json
{
  "entity": "R1",
  "attribute": "resistance",
  "value": "2000",
  "unit": "ohm",
  "raw": "2 kΩ",
  "evidence_span_id": "ocr-17",
  "recognition_status": "verified"
}
```

按对象和属性比较，不比较裸数字袋：R1=2kΩ 与 R2=2kΩ 不能互换；2kΩ 与 2000Ω 可等价；2Ω 不等于 2kΩ。保留 A/B 端点、参考零点、正负极性、箭头方向、元件拓扑、边界条件、坐标轴变量、连续/离散域、时间/频率/s 域、函数区间开闭与幅值。

使用三值核验：`consistent / conflict / unknown`。关键字段未识别、OCR 候选有歧义、图中字符过小属于 unknown，不能当作“没有冲突”。两个 OCR/模型相同结论也可能是相关错误；高风险字段需人工或独立可核查原生文本证据。

明确冲突直接阻断：三角脉冲与系统框图、频响幅值图与 s 域结构图、20Ω 与 200Ω、+12V 与 −12V、闭区间与开区间、乘法器与求和器、不同参考方向等。不能通过其他相似性加分抵消冲突。若 OCR 误识别导致冲突，先修正有证据支持的结构化事实并生成新版本，再重新审核。

### 6.3 双向验证和置信度

正向：给定一道题，源题引用和局部几何区域是否唯一指向该 occurrence？

反向：给定该 occurrence，原页面题干、图号、参数和子图关系是否只支持这个目标题或显式共享题组？两道题竞争同一图或前后候选难分时拒绝自动批准。一个题可以需要多个子图；一个原图可以被同一共享题组合法复用，不能强行做全局一对一匹配。

可做带 null（不分配）选项的约束图匹配；约束包括题组共享、父子图排他、相同题多次引用和复合图完整性。图匹配不是“必须填满所有槽位”的最大覆盖算法。

多模态模型的职责是分类、提取可见标签/结构、指出冲突并返回证据位置。返回 JSON；没有看到的字段填 unknown。模型没有插图、生成像素或修改参数的权限。CLIP/embedding 仅用于当前允许集合内的候选排序，不能充当准入门槛。

```text
可进入草稿 = 范围与来源有效 AND 原图完整 AND 来源题已对齐
             AND 关键事实核验完成且无冲突 AND 插入槽位有效
             AND （严格模式下逐对审核有效）
```

不要把旧 score 或模型口述的 confidence 当概率。可选自动模式先用标注集校准多特征模型，按课程/题型报告 precision 与 coverage、校准误差、第一第二候选间隔、反向唯一性和域外检测。样本按文档/模板分割训练与测试，避免重复图片泄漏。未校准课程默认禁用自动批准。

严格模式是默认：模型只减少候选审阅量。自动模式是另行选择的效率策略，不能宣称 100% 准确。即使 3000 个独立测试样本零错配，95% 单侧上界仍约为 0.1% 错误率；有限测试不证明零错误。

## 7. 结构化 Markdown 与 LaTeX 插入

### 7.1 统一 DocumentIR，取消逐行注入

引入 `DocumentIR`，节点包括 `Section / Paragraph / MathBlock / Table / CodeBlock / List / ListItem / Question / Stem / Options / FigureSlot / FigureBlock / Solution`。Markdown 和 LaTeX 从同一 IR 输出。

推荐沿用 Python 栈，使用 markdown-it-py 的 token/tree 和 source map 作为解析前端，显式启用表格、数学、frontmatter、必要的 Obsidian callout/wikilink 支持；插件不足时拒绝相关结构中的自动插入。不能以 commonmark 默认解析器“没认出表格/数学”就宣称安全。替代方案 Pandoc AST 也可行，但需一次性迁移现有 Obsidian 语义和模板，避免长期两套解析语法不同。

目标题目用稳定 UUID 定位，不用标题字符串、行号或“例 1”序号作为身份。现有 `question_index` 的展示索引可以继续生成，但它的顺序锚点不能代替来源身份。

默认插入顺序：

```text
Question
  Stem（包括题干连续文字、题干数学与题设表格）
  FigureSlot(role=given, after=stem)
  Options（如选项必须先展示则由模板显式规定）
  Solution
```

原题“图见选项”等特殊布局用显式角色建模。解答引用图使用 `role=solution` 槽位，不能提前插入题干；无目标题或明确概念角色的章节、结语、客套话不提供槽位。

`FigureBlock` 必须是 block 子节点：禁止位于 Text/Inline/Math/Code/TableCell 内。表格题设结束后插图；列表题目把图放在所属 ListItem 的 block children 中，不关闭整个列表。超长题干允许分页，图与题干尾部/解答标题用有限 needspace 保持关联，不把整道长题塞进不可分页 minipage。

### 7.2 旧 Markdown 的渐进兼容

先解析整棵树，辨识完整题目与题干结束边界，再在合法 block 边界插入。第一阶段只自动处理结构清晰的顶层 Question；嵌套列表、跨表格题干或未闭合公式进入复核。若必须保留原 Markdown，使用 source map 做自后向前的块边界 patch，重解析并验证不变量；不能切行号后凭关键词写入。

不变量：原表格的单元格、行列与顺序不变；代码和数学内容字节不变；已有段落文字不变；列表父子关系不变；只增加已批准 FigureBlock；插入两次结果一致。AST 规范化比较时只剔除本次带 binding ID 的新增图节点，不能删掉所有图再声称结构一致。

“对应频域条件为：”和后面的公式作为同一 Stem/Paragraph 结构保留，图片放在完整逻辑块结束之后。非正文对话内容在生成校验阶段报警；不要依靠一长串客套话黑名单来承担插图定位。

### 7.3 尺寸与 XeLaTeX

根据源区域物理尺寸、实际像素和局部版心计算宽度：`min(source_width_pt * allowed_scale, available_linewidth, pixel_width*72/min_effective_dpi)`，保留长宽比并限制高度。每类图可设可读性范围；天然低清图不能靠放大解决。嵌入 bitmap 的 `dpi=300` 元数据不证明它真的有 300 DPI，必须结合其页面显示尺寸计算。

图需要紧随题干时使用文档结构内的非浮动图块，例如 `center + includegraphics + captionof{figure}`（模板显式加载相应包），并用有限 `needspace` 控制间距。不要依赖 `[H]` 修复错误语义位置；过高图可单独占页并保留题目标签。列表中使用局部 `linewidth`，禁用超出版心的固定宽度。

图注和路径经结构化转义，保留学术符号。原始图注优先，人工可核验的描述次之；不再把 width/align 控制信息塞进 alt 文本。原图号、讲义图号、页码分字段保存。

图注例：`图 3-2 零状态系统结构与子系统输入、输出波形（原资料图 a–c）`；来源另列文件名、页码、原题号。没有证据不能把某图命名为“三角脉冲”。`第 14 页题图` 可以作来源提示，不能替代内容描述。

## 8. 任务物理沙箱与构建门禁

```text
studio_data/jobs/<task_id>/runs/<run_id>/
  inputs/                 # 仅本任务批准源文件的只读快照
  sources.json            # course/task + 文件 SHA256 白名单
  parsed/                 # 布局、OCR、题目、图候选
  figures/                # 仅本任务原图，无全局图库读取权限
  bindings.json
  reviews.json
  build/<build_id>/        # 新目录，只复制已批准的引用图
  reports/figures.json
```

需要从公共课程资料导入时，启动任务时显式登记并复制/快照到 inputs，禁止运行时扫描其他课程目录。不同任务相同字节图也不跨目录硬链接复用；模型可以共享，语料和题图索引不共享。

加载 manifest 时要求 scope 与 sources snapshot 完全匹配；未知/损坏 manifest 是错误，不静默创建空 manifest。模型开启字段与取值校验；所有资产、occurrence 和 binding 逐层核验 scope。路径 resolve 后必须在当前根目录内，处理 Windows junction/symlink；拒绝绝对路径、`..`、外部 URL、basename 回退。构建阶段在新目录复制固定 hash 的文件并再次校验，避免同名旧文件或审核后更换文件。严格物理约束可配合子进程受限 ACL/容器挂载，只暴露本任务 inputs 与 build。

构建成功要求：每张引用图在本任务 manifest 登记、来源 hash 可核验、crop/hash 对应有效记录、逐对绑定有效、题干版本一致、插入 slot 合法、实际文件 hash 一致。图片存在只满足其中一个条件。

审计结果分开报告：`provenance_valid / binding_valid / structure_valid / required_figures_complete / review_current / layout_reviewed`。不再用一个 `audit_passed` 混淆含义。

降级策略：

| 情况 | 草稿行为 | 交付行为 |
| --- | --- | --- |
| 模型低分、参数 unknown、竞争候选、OCR 故障 | 无图，注明目标题待核验，输出 review queue | 未解决的必需图题不能作为完整已解题交付 |
| 源资料根本没有该图 | 改为不依赖图的文字题，或明确标为未完成题 | 需要用户可见地接受缺项/移除该题，不能暗中用相似图补上 |
| 来源越界、hash 变化、缺失批准 | 阻止受影响绑定与正式构建 | 必须修复来源/版本后重审 |
| 图可读、来源匹配、逐对审核有效 | 按 slot 插入 | 编译及版面验证通过后可交付 |

队列每项保存：源页预览和 bbox、原题干、候选图、目标题干、参数差异、拒绝理由、候选排序证据。审核操作针对 binding，不提供一次点击“批准全部尺寸合格图”。任何不确定都允许选择“不使用图”。

## 9. 文件级重构与迁移顺序

以下均为拟实施变更，本次没有修改生产代码。

| 阶段 | 文件/接口 | 可审查结果与完成判据 |
| --- | --- | --- |
| P0 停止错误自动化 | `scripts/batch_remake_handouts.py` | 默认只分析，移除按尺寸确认和 0.18 自动插入；不会改写已有章节 |
| P0 强制审计 | `figure_models.py`, `figure_matcher.py`, `handout_builder.py`, `studio/workspace.py` | 加载身份校验；未登记/未审核/异任务图拒绝；只复制引用白名单；build/deliver 都要求有效题图审计 |
| P1 数据契约 | 新增 `modules/figures/models.py`, `store.py`, `provenance.py` | scope、blob、occurrence、source question、binding、review 分离；schema version 和旧数据迁移测试 |
| P1 源资料解析 | 新增 `pdf_layout.py`, `office_layout.py`, `coordinates.py` | 原生文字/OCR、题干分块、Office 渲染适配、统一坐标；原页与 crop 对齐测试 |
| P1 图形完整性 | 新增 `regions.py`, `quality.py` | 保留细线和标签；父子图、装饰与水印分类；不确定候选进入队列 |
| P2 来源与参数绑定 | 新增 `question_linker.py`, `facts.py`, `matching.py`, `policy.py` | 同题身份优先；冲突不可由得分抵消；null 分配；严格模式默认开启 |
| P2 生成契约 | `prompt_runner.py`, `config/prompts.yaml`, `question_index.py` | 传入受限 source catalog；生成来源 ID 由服务端验证；保留展示编号与稳定 UUID |
| P2 结构注入 | 新增 `document_ir.py`, `figure_injector.py`；调整 renderer | Markdown/LaTeX 共用 IR；表格/代码/数学/列表不变量通过；幂等 |
| P3 审核 UI | `studio/workspace.py`, `studio/static/figures.js`, HTTP endpoints | 并排展示源页、目标题、关键事实；批准绑定并锁定版本；没有有效批准无法交付 |
| P3 发布 | build receipt / figures audit / 页面渲染报告 | 每张图追溯到题目和源坐标；编译成功后仍核验图片位置、裁切、尺寸与邻接关系 |

兼容：现有 `modules/figure_extractor.py` 等可保留薄适配层，但旧 CandidateMatch 只返回候选，不能产生 approved。`ReviewStatus.CONFIRMED` 迁移为 legacy-unverified，不自动变成绑定批准；现有产物先复制归档、扫描绑定、输出候选 diff，再从已审核源版本重建。不要对污染的 Markdown 一边模糊删图一边重新匹配。

旧章节存在表格拆断或图片与句子粘连时，从 `raw/v3` 或已知干净版本恢复结构，再重放经审核的绑定；若无干净版本，输出逐块修复 diff 供检查，不能假设删除 `![]()` 就能恢复全部原语法。旧 `release` 以旧版本身份保留，不能继续被标为“当前已验证”。

依赖：在 `pyproject.toml` 增加明确的 figures extra（Pillow、NumPy、pypdfium2、python-pptx、python-docx、markdown-it-py 与选定数学/frontmatter 插件），锁定经验证版本。OCR/版面模型放单独 extra/进程服务，使用固定模型文件 hash；没有安装时安全降级。CI 同时测试最小安装和 figures 安装，避免系统 Python 可用而项目虚拟环境缺依赖。

接口草案：

```python
parse_source(snapshot, document_id) -> PageLayoutSet
segment_questions(layouts) -> list[SourceQuestion]
detect_figure_occurrences(layouts, questions) -> list[FigureOccurrence]
render_source_crop(snapshot, occurrence) -> FigureBlob
assess_completeness(occurrence, blob, layouts) -> CropAssessment
propose_bindings(targets, questions, occurrences) -> list[BindingProposal]
verify_binding(proposal, facts, reviews, policy) -> BindingDecision
inject_figures(document_ir, approved_bindings) -> DocumentIR
audit_build(document_ir, task_store, receipts) -> FigureAudit
```

这些接口是拟实施契约，不是当前已经存在的 API。

## 10. 可运行的严格决策内核示例

本节只演示确定性准入，不包含 OCR/视觉识别、存储层、路径校验或 Markdown 注入。输入 Evidence 必须由服务端验证器构造，Review 必须从受信审核存储加载，不能让模型、HTTP 请求或用户上传 JSON 自行填写 approved。fingerprint 是失效检测，不是签名或身份认证。

将以下两个代码块分别保存为 `figure_gate.py` 和 `test_figure_gate.py`，在同一临时目录运行 `python -m unittest -v`。只需要 Python 标准库。

```python file=figure_gate.py
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Literal


@dataclass(frozen=True)
class Scope:
    task_id: str
    course_id: str
    run_id: str
    source_snapshot_hash: str


@dataclass(frozen=True)
class Evidence:
    scope: Scope
    target_id: str
    target_hash: str
    occurrence_id: str
    source_document_hash: str
    crop_hash: str
    slot_id: str
    pipeline_hash: str
    source_question_id: str
    target_source_question_id: str
    provenance_valid: bool
    crop_complete: bool
    slot_valid: bool
    reverse_unique: bool
    facts: Literal['consistent', 'conflict', 'unknown']

    def fingerprint(self) -> str:
        data = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return sha256(data.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class Review:
    evidence_hash: str
    reviewer: str
    decision: Literal['approved', 'rejected']


@dataclass(frozen=True)
class Decision:
    state: Literal['approved', 'rejected', 'needs_review']
    reason: str


def decide(expected: Scope, evidence: Evidence,
           review: Review | None = None) -> Decision:
    # expected comes from the active task, never from a candidate asset.
    if not all(asdict(expected).values()):
        return Decision('rejected', 'INVALID_SCOPE')
    if evidence.scope != expected:
        return Decision('rejected', 'SCOPE_MISMATCH')
    identifiers = (
        evidence.target_id, evidence.target_hash, evidence.occurrence_id,
        evidence.source_document_hash, evidence.crop_hash,
        evidence.slot_id, evidence.pipeline_hash,
    )
    if not all(identifiers) or not evidence.provenance_valid:
        return Decision('rejected', 'INVALID_PROVENANCE')
    if evidence.facts == 'conflict':
        return Decision('rejected', 'PARAMETER_CONFLICT')
    if not evidence.slot_valid:
        return Decision('rejected', 'INVALID_SLOT')
    if not evidence.crop_complete:
        return Decision('needs_review', 'INCOMPLETE_OR_UNCERTAIN_CROP')
    if (not evidence.source_question_id or
            evidence.source_question_id != evidence.target_source_question_id):
        return Decision('needs_review', 'SOURCE_QUESTION_NOT_ALIGNED')
    if evidence.facts != 'consistent':
        return Decision('needs_review', 'UNKNOWN_CRITICAL_FACTS')
    if not evidence.reverse_unique:
        return Decision('needs_review', 'AMBIGUOUS_BINDING')
    if (review is None or not review.reviewer.strip() or
            review.evidence_hash != evidence.fingerprint()):
        return Decision('needs_review', 'MISSING_OR_STALE_REVIEW')
    if review.decision != 'approved':
        return Decision('rejected', 'REVIEW_REJECTED')
    return Decision('approved', 'VERIFIED_BINDING')
```

```python file=test_figure_gate.py
from dataclasses import replace
import unittest
from figure_gate import Scope, Evidence, Review, decide


class GateTests(unittest.TestCase):
    def setUp(self):
        self.scope = Scope('task-A', 'signals', 'run-1', 'snapshot-1')
        self.e = Evidence(
            scope=self.scope, target_id='q-1', target_hash='stem-1',
            occurrence_id='occ-1', source_document_hash='source-1',
            crop_hash='crop-1', slot_id='q-1/after-stem',
            pipeline_hash='pipeline-1', source_question_id='src-q-1',
            target_source_question_id='src-q-1', provenance_valid=True,
            crop_complete=True, slot_valid=True, reverse_unique=True,
            facts='consistent',
        )
        self.review = Review(self.e.fingerprint(), 'reviewer-1', 'approved')

    def test_valid_binding(self):
        self.assertEqual(decide(self.scope, self.e, self.review).state, 'approved')

    def test_no_implicit_approval(self):
        self.assertEqual(decide(self.scope, self.e).state, 'needs_review')

    def test_scope_is_hard_gate(self):
        for key in ('task_id', 'course_id', 'run_id', 'source_snapshot_hash'):
            with self.subTest(key=key):
                foreign = replace(self.scope, **{key: 'different'})
                e = replace(self.e, scope=foreign)
                r = Review(e.fingerprint(), 'reviewer-1', 'approved')
                self.assertEqual(decide(self.scope, e, r).reason, 'SCOPE_MISMATCH')

    def test_parameter_conflict_cannot_be_approved(self):
        e = replace(self.e, facts='conflict')
        r = Review(e.fingerprint(), 'reviewer-1', 'approved')
        self.assertEqual(decide(self.scope, e, r).reason, 'PARAMETER_CONFLICT')

    def test_unknown_incomplete_or_ambiguous_is_not_approved(self):
        cases = ({'facts': 'unknown'}, {'crop_complete': False},
                 {'reverse_unique': False}, {'source_question_id': ''},
                 {'target_source_question_id': 'another-question'})
        for change in cases:
            with self.subTest(change=change):
                e = replace(self.e, **change)
                r = Review(e.fingerprint(), 'reviewer-1', 'approved')
                self.assertEqual(decide(self.scope, e, r).state, 'needs_review')

    def test_changed_evidence_invalidates_review(self):
        for key in ('target_hash', 'crop_hash', 'source_document_hash',
                    'occurrence_id', 'slot_id', 'pipeline_hash'):
            with self.subTest(key=key):
                e = replace(self.e, **{key: 'changed'})
                self.assertEqual(decide(self.scope, e, self.review).reason,
                                 'MISSING_OR_STALE_REVIEW')

    def test_invalid_source_and_slot_are_blocked(self):
        self.assertEqual(decide(self.scope, replace(self.e, provenance_valid=False),
                                self.review).state, 'rejected')
        self.assertEqual(decide(self.scope, replace(self.e, slot_valid=False),
                                self.review).state, 'rejected')

    def test_rejected_review(self):
        r = replace(self.review, decision='rejected')
        self.assertEqual(decide(self.scope, self.e, r).reason, 'REVIEW_REJECTED')


if __name__ == '__main__':
    unittest.main()
```

验证记录：本次已从本文提取这两个代码块，在自动清理的临时目录执行 `python -m unittest discover -s <temp> -v`，8 个测试全部通过。该结果只验证上述决策内核示例，不代表现有 CourseLM 已完成重构或修复。

生产版本还应使用严格模型校验（禁止字符串冒充 bool、非法 enum、缺字段），持久化不可变的审核事实和 evidence hash；源码、crop hash 必须来自实际字节重算。此示例不宣称解决了上游模型可能产生错误证据的问题。

## 11. 测试用例与发布验收

测试必须同时包含正确图保留与错误图拒绝，不能靠“全部拒绝”取得完美正确率。保守运行时允许没有图，但测试应证明已核验有效图能正常进入交付。

| 测试组 | 样本/变体 | 期望 |
| --- | --- | --- |
| 现场资产回归 | 五个已列 ID，附原页面坐标、题干与人工 gold label | 水印/渐变/按钮拒绝；乘法器返回父图或复核；系统图只绑定原系统题 |
| 有效小图 | 元件识别题的单个运放、小型光路/晶格示意 | 不因体积或类别误杀；有审核可插入 |
| 有效照片/表格 | 实验装置照片、题设数据表；长城历史照片作负例 | 根据题目角色路由；不能按照片/文字占比通杀 |
| PDF 复合图 | 位图+矢量线+文字；Form 嵌套；soft mask；横竖细线 | 原页面 crop 包含全部可见内容和参数 |
| 几何变换 | 0/90/180/270°；非零 CropBox；不同页面大小；UI 缩放 | 标记区域与 crop 一致，单元误差界明确，原图不被转错或截断 |
| 扫描/多栏/跨页 | 无文字层；双栏相邻题；题干跨页；a–c 三联图 | OCR 与题目归属正确；不能确认则复核，不整页误拒 |
| Office | PPT Logo+矢量图混合、递归组、图片裁剪；DOCX header/body 同图、anchor 和重复 rId | 正确题目归属；无渲染器报告不可用；不伪造页码 |
| 关键参数反例 | 2Ω/2kΩ、20/200、±12V、R1/R2、s/jω、端点方向、区间开闭、同型不同拓扑 | 冲突阻断；无法识别为 unknown；绝不被高语义分覆盖 |
| 命名空间 | 两文件图1、图1/图10、章节7/页7、相同 hash 不同 occurrence | 按完整键与本地证据区分 |
| 沙箱 | 其他任务 manifest、未知资产、同名文件、绝对路径、`../`、symlink/junction | 路径/范围拒绝；不做 basename 回退 |
| 审核失效 | 修改题干负号、替换图片、移动 crop、更新源文件、版本回退 | 审核变 stale，重新核验前不能发布 |
| Markdown 结构 | 表格首中末行、含图片代码示例、四反引号 fence、行内/块数学、嵌套列表、引用与 callout | 原表格/代码/数学/列表结构不变，仅合法 slot 新增图 |
| 锚点与幂等 | 缺失/重复 UUID、正文不存在、重复运行、章节排序改变 | 不猜位置；缺失/重复报错；同 binding 只插一次 |
| 构建文件 | 图存在但未登记、hash 不符、未批准、缺源文件、旧 build 残图 | 正式构建或交付阻断；旧图不被批量复制 |
| 原图一致性 | 固定渲染器重渲染相同源 crop，像素 hash 和标签核查 | 图像来自原页；没有改图操作；差异触发复核 |
| PDF 端到端 | 题干—图—解答，多页长题，列表内图，超高图，合法特殊字符图注 | XeLaTeX 成功、图不越界、无截断、关联位置正确；不得只检查 PDF 存在 |
| 故障降级 | OCR/模型超时、返回非法 JSON、渲染失败、文件损坏、未安装 OCR | 返回明确原因并保留可重试记录，不转为空证据后自动通过 |

回归夹具保存不可变输入的 hash 与 gold annotations，不直接依赖易变 output 目录；可公开样本使用最小合法夹具，真实题库样本仅在当前任务/本地受控回归中读取。合成图只用于测试坐标、像素和结构，不作为讲义题图来源。

指标必须分开：已插入图的来源合规率、绑定正确率、裁剪完整率、参数准确率、覆盖率、拒绝率、人工修正率、Markdown 结构破坏数。默认门槛：现场已知错配回归数为 0、来源违规数为 0、未经审核绑定数为 0、结构破坏数为 0；报告 coverage，不能用数量多奖励放宽准入。

对预先确认的正确样本要求能完整交付，防止全拒绝系统。视觉端到端使用固定字体/渲染器，保存页面 PNG、图块位置与邻接题 ID；像素比较容忍光栅抗锯齿差异，但关键文字和完整性仍核验。版面扫描不是语义正确性证明，必须与 binding 和人工 gold 一起检查。

建议拟实施后的命令（当前对应模块尚未创建）：

```powershell
python -m pytest tests/figures/test_policy.py tests/figures/test_provenance.py -q
python -m pytest tests/figures/test_coordinates.py tests/figures/test_extraction.py -q
python -m pytest tests/figures/test_binding.py tests/figures/test_injection.py -q
python -m pytest tests/figures/test_known_failures.py tests/figures/test_pdf_delivery.py -q
```

## 12. 核对的技术资料

- [pypdfium2 Python API](https://pypdfium2.readthedocs.io/en/stable/python_api.html)：文字边界、渲染、对象资源释放、缺少完整布局分析和线程限制。
- [python-pptx Shapes](https://python-pptx.readthedocs.io/en/latest/api/shapes.html)：组形状、图片 crop、位置和尺寸等对象语义。
- [python-docx shapes](https://python-docx.readthedocs.io/en/latest/user/shapes.html)：流式文字层、inline/floating shapes 支持边界。
- [markdown-it-py 使用说明](https://markdown-it-py.readthedocs.io/en/latest/using.html)：tokens、source map、语法树。
- [Pandoc filters](https://pandoc.org/filters.html)：reader → AST → filter → writer 的替代路线。
- [PaddleOCR PP-StructureV3](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PP-StructureV3.md)：可作为布局、表格和公式分析候选工具；本次没有测评其在 CourseLM 真题上的准确率，不预设它能直接满足准入标准。
