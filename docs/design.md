# CourseLM 三天冲刺讲义流水线

- 当前版本：v3
- 更新日期：2026-08-27
- 默认受众：基础薄弱、距离期末考试三天的学生

## 1. 产品目标

CourseLM 不再默认追求“完整课程笔记”，而是生成一份低门槛、可执行的冲刺讲义。学生应能在三天、每天 4–6 小时内完成主线学习，最终达到四个最低目标：看懂课程结构、抓住核心考点、识别高频题型、减少可避免失分。

生成内容必须以课程资料为依据。资料没有给出时，不得虚构考试权重、出题频率、教师偏好或来源页码；不确定的信息要明确标注“需结合任课教师范围确认”。

## 2. 默认内容模型

一次全新生成包含 12 个固定模块和 N 个动态题型模块，NotebookLM 对话量为 `12 + N`，其中 N 受 `prompt_runner.max_question_types` 限制。

```text
00-使用说明.md
01-考前三天学习规划.md
02-考试地图.md
03-零基础补给站.md
04-一页知识骨架.md
05-核心考点卡.md
06-公式工具箱.md
07-题型识别地图.md
08-高频题型精讲/
  <题型名>.md
09-易错点诊断室.md
10-最小训练集.md
11-考前速记.md
12-综合自测与补救路线.md
```

三天不是简单按页数平均切分，而是按认知任务组织：

- 第一天：建立方向感。完成使用说明、学习规划、考试地图、零基础补给、一页知识骨架和核心考点卡。
- 第二天：建立解题能力。完成公式工具箱、题型识别地图和高频题型精讲。
- 第三天：建立得分稳定性。完成易错诊断、最小训练、考前速记和综合自测，并根据结果回跳补救。

每个模块使用短段落、步骤化表达、先结论后解释，并通过 Obsidian callout 表达教学语义：`IMPORTANT` 表示必须掌握，`TIP` 表示解题捷径，`WARNING` 表示易错点，`CHECK` 表示即时自测。

## 3. 两阶段生成

```text
扫描课程资料 → 创建或复用 NotebookLM Notebook → 上传资料
  → 阶段一：依次执行 12 个固定 Prompt
  → 从“题型识别地图”解析题型清单
  → 阶段二：每个题型执行一次动态 Prompt
  → 统一清洗 Markdown → 写入 output 与 Obsidian
  → 按讲义模板组装 manuscript.md → 渲染 main.tex → XeLaTeX 导出 PDF
```

固定 Prompt 由 `config/prompts.yaml` 管理。保留 `knowledge_structure`、`formula_summary` 和 `question_type_summary` 等稳定 ID，以兼容定向重跑与既有自定义配置。动态模板 `question_type_detail` 使用 `{type_name}` 和完整题型清单作为上下文。

`--fresh` 会新建 Notebook 并清空生成缓存。升级到 v3 目录后第一次生成必须使用该参数，否则旧缓存不会自动拥有新模块。

## 4. 模板与课程定制

默认讲义模板位于 `config/handout_templates/default.yaml`，控制：

- PDF 标题后缀和副标题；
- 章节顺序、来源文件、是否必需、是否换页；
- 动态题型文件的 glob；
- LaTeX 主色、强调色、警告色、成功色和辅助色。

单门课程可在 `courses/<课程名>/handout.yaml` 覆盖。标量覆盖默认值，`latex` 字典按键合并，`sections` 列表一旦提供则完整替换默认目录。模板加载器拒绝重复章节 ID、同时缺失或同时提供 `source/glob`、以及任何目录穿越路径。

模板只改变讲义的组装和呈现，不会凭空生成未在 `config/prompts.yaml` 中定义的 NotebookLM 内容。因此新增课程专属章节时，应同时提供对应 Prompt 或指向已有生成文件。

## 5. 断点续跑和缓存

- Notebook ID 和运行状态保存在 `output/<课程>/state.json`。
- 固定 Prompt 按 ID 缓存；动态题型按清洗后的题型名缓存。
- 普通 `generate` 复用已有成功结果，减少对话消耗。
- `--prompts <id>` 可定向重跑固定模块；依赖题型清单的动态阶段仍以最新的 `question_type_summary` 为准。
- 单个 Prompt 失败会按配置重试，已成功的原始回答立即落盘。

## 6. Markdown、LaTeX 与 PDF

Markdown 生成器负责 Front Matter、唯一 H1、数学定界符和文件名安全。讲义组装器严格按模板顺序读取固定文件，并稳定排序动态题型文件；缺失必需章节时列出缺失项并让 CLI 失败。

LaTeX 使用 `ctexart` 和 XeLaTeX，支持：

- `$...$` 与 `$$...$$` 数学公式；
- 可跨页 `longtable`；
- 可跨页彩色 `tcolorbox` 教学提示框；
- 章节分页标记、目录、页眉和页码；
- 模板配置的语义配色。

PDF 是待人工审阅的商业讲义初稿。正式出售前必须检查事实、公式、例题答案、个人信息、来源授权和第三方版权。

## 7. 模块边界

- `file_manager`：扫描课程资料并校验来源文件。
- `notebooklm`：登录、Notebook 复用、上传和提问的薄适配层。
- `prompts` / `prompt_runner`：Prompt 校验、两阶段编排、题型解析、缓存与重试。
- `markdown_generator`：原始回答到安全 Obsidian Markdown。
- `obsidian_sync`：在 Vault 根目录内安全同步。
- `handout_template`：默认模板与课程级覆盖的加载和校验。
- `handout_builder`：按模板组装讲义 Markdown 和 LaTeX 输入。
- `latex_renderer`：Markdown 子集到中文 LaTeX 文档。
- `main.py`：`login`、`scan`、`generate`、`build-handout`、`export-handout` 命令入口。

## 8. 验证标准

自动化测试覆盖配置校验、Prompt 契约、题型解析、断点缓存、Markdown 清洗、模板覆盖、目录组装和 LaTeX 语义。发布前还必须执行真实闭环：

```powershell
.venv\Scripts\courselm generate <课程名> --fresh
.venv\Scripts\courselm build-handout <课程名>
.venv\Scripts\courselm export-handout <课程名>
```

真实验证以命令退出码、生成的 `manuscript.md` / `main.tex` / PDF 文件，以及代表性 PDF 页面的人工检查为准；仅有单元测试通过不等于 NotebookLM 与 XeLaTeX 闭环可用。
