# CourseLM Automation Pipeline — 设计文档

- 日期：2026-08-25
- 状态：已与需求方确认（技术路线、复用策略、Prompt 来源、产出结构修订版 v2）
- 项目位置：`e:\Projects\note-agent`
- 修订记录：v2（2026-08-25）产出结构由"6 个固定文档"改为
  "知识结构 + 公式总结 + 题型/（总结 + 动态题型文件）"两阶段流水线

## 1. 项目目标

个人课程资料自动化处理系统。将大学课程资料放入 `courses/<课程名>/`，执行：

```
courseLM generate 电磁场
```

即在 Obsidian Vault 中生成结构化复习文档（2026-08-25 需求修订版）：

```
<Vault>/课程/电磁场/
├── 知识结构.md            # 整本书的知识结构
├── 公式总结.md            # 全书公式清单
└── 题型/
    ├── 题型总结.md        # 常考题型清单 + 每类题型的高频解法
    ├── <题型名A>.md       # 单个题型详解（动态数量）
    └── <题型名B>.md
```

单个题型文件包含：例题、解法、易错点提醒、与其他题型的联系。

完整流水线为**两阶段动态编排**：

```
扫描资料 → 上传 NotebookLM
  → 阶段一（固定 Prompt）：知识结构.md + 题型总结.md + 公式总结.md
  → 解析题型总结，提取题型清单
  → 阶段二（动态 Prompt）：每个题型一次提问 → 生成对应题型文件
  → 转换为 Obsidian Markdown → 写入 Vault
```

与初版设计的差异：原"6 个固定文档"方案取消（高频考点/核心知识点/易错点并入
题型体系），新增按题型动态生成文件的第二阶段。

## 2. 关键技术决策

### D1 技术路线：notebooklm-py 作为 NotebookLM 交互层（已确认）

NotebookLM 无官方 API。经评估 `teng-lin/notebooklm-py`（MIT，PyPI 发布，活跃维护）：

- 该库通过逆向 NotebookLM 内部 RPC 接口通信，Playwright 仅用于首次登录采集 Cookie
- 提供本项目所需的全部能力：创建/列出 Notebook、上传文件（PDF/PPT/DOCX/图片）、
  `chat.ask()` 提问并返回回答、等待 source 索引完成
- 登录态以 Cookie 形式持久化于 `~/.notebooklm/`，内置自动刷新

**放弃**自建 Playwright UI 自动化（DOM 选择器脆弱、维护成本高、Google 改版即失效）。
本决策推翻了最初"不要设计 API 调用方案"的约束，依据是：该约束的前提
（没有可用的接口）已被此逆向客户端证伪；需求方已于 2026-08-25 确认改采用本路线。

### D2 复用与断点续跑（已确认）

重复 `generate` 同一课程时：

1. 按 Notebook 标题（约定为课程名）在 `notebooks.list()` 中查找已有 Notebook，命中则复用，
   未命中则新建；notebook_id 持久化到 `output/<课程>/state.json`
2. 已成功的 Prompt 直接读缓存跳过（省 chats 配额）。缓存键：固定 Prompt 用其 id；
   题型文件用题型名（`output/<课程>/raw/题型_<名称>.md`），题型清单变化时旧缓存自然失效
3. 输出 md 直接覆盖（Obsidian 自带文件历史）
4. `--fresh` 强制新建 Notebook、清空缓存重跑

### D3 Prompt 外置（已确认）

Prompt 全部放在 `config/prompts.yaml`，分两类：

- **固定模板** 3 条：`knowledge_structure`（知识结构）、`question_type_summary`
  （题型总结，输出格式需含机器可解析的题型清单）、`formula_summary`（公式总结）
- **动态模板** 1 条：`question_type_detail`，含 `{type_name}` 占位符，
  运行时按解析出的题型名填充后逐个执行

每条固定模板含 `id / title / output_file / template` 四个字段。用户审阅初稿后
可持续自行修改，不改代码。

### D4 题型清单解析

题型总结 Prompt 中约定输出格式：文档末尾输出一个 markdown 表格
（`| 序号 | 题型名称 | ... |`），程序解析表格得到题型清单。

- 解析策略分级：① 约定格式的表格 → ② 备用：任意 markdown 表格 →
  ③ 备用：编号标题（`1. xxx` / `一、xxx`）。全部失败才报错，并保留已生成文件，
  提示用 `--prompts question_type_summary` 单独重跑该 Prompt
- 阶段二 Prompt 中附上完整题型清单，使模型能写出"与其他题型的联系"
- 题型数量上限（默认 12，可配置）：Prompt 中明确要求"总结不超过 N 类"，
  防止 chats 配额失控（免费版 50/天，单课用量 = 3 固定 + N 题型）
- 题型名 → 文件名清洗：去除 Windows 非法字符 `\ / : * ? " < > |`，长度截断

### D5 异步架构

notebooklm-py 基于 asyncio。流水线内部全 async，`main.py` 顶层 `asyncio.run()`。
Windows 平台事件循环策略由 notebooklm-py 自动处理。

### D6 CLI 设计（标准库 argparse）

```
courseLM login                     # 首次登录（调 notebooklm-py 登录流程）
courseLM scan <课程名>              # 只扫描，列出识别到的资料清单
courseLM generate <课程名>          # 完整流水线（两阶段）
courseLM generate <课程名> --prompts knowledge_structure   # 只跑指定固定 Prompt（调试）
courseLM generate <课程名> --fresh  # 强制新建 Notebook 重跑
```

`--prompts` 仅支持固定模板 id；阶段二题型文件始终基于最新解析的题型清单执行。

### D7 日志与可诊断性

loguru 输出到控制台 + `logs/`（按日滚动）。关键节点（扫描结果、上传进度、
每个 Prompt 开始/结束/耗时、写盘路径）全部记录。异常带堆栈。

## 3. 模块设计

依赖方向单向：`main → prompt_runner → notebooklm → (notebooklm-py)`；
file_manager / markdown_generator / obsidian_sync 为独立纯本地模块，可单测。

### 3.1 file_manager

- 职责：扫描 `courses/<课程名>/`（递归），识别 PDF/PPT/PPTX/DOCX/图片
  （.pdf .ppt .pptx .doc .docx .jpg .jpeg .png .webp .gif），生成资料清单
- 接口：`scan_course(course_name) -> CourseManifest`（含文件绝对路径、大小、类型）
- 边界：课程目录不存在时明确报错；空目录警告并中止；超出 50 sources 上限时警告
- 扩展名集合外置到 config.yaml

### 3.2 notebooklm（薄适配层）

- 职责：封装 `NotebookLMClient`，提供本项目语义化的四个操作
- 接口：
  - `get_or_create_notebook(course_name) -> notebook_id`（实现 D2 复用）
  - `upload_sources(notebook_id, manifest) -> UploadReport`（逐个 `add_file(wait=True)`，
    失败记录并继续；`wait_timeout` 可配置）
  - `ask(notebook_id, question) -> str`（`chat.ask()`，返回 answer 文本）
  - `login()`（包装 notebooklm-py 登录流程）
- 异常翻译：将库异常映射为项目内异常类型（如 `NotebookLMAuthError`），上层统一处理

### 3.3 prompt_runner

- 职责：编排两阶段 Prompt 的执行、题型清单解析、缓存读写、失败重试
- 流程：
  1. **阶段一**：依次执行 3 个固定 Prompt（知识结构 → 题型总结 → 公式总结），
     缓存命中则跳过；每个回答立即落盘 `output/<课程>/raw/<id>.md`
  2. **解析**：从题型总结回答中提取题型清单（见 D4）；清洗题型名并确定
     各自的缓存键/输出文件名
  3. **阶段二**：对每个题型填充 `question_type_detail` 模板并执行，
     回答落盘 `output/<课程>/raw/题型_<名称>.md`
- 重试：单 Prompt 网络类失败重试 1 次（可配置）；失败不中断整批
- 计数：累计当日 chats 用量提示（单课 = 3 固定 + N 题型；免费版 50/天上限）

### 3.4 markdown_generator

- 职责：raw 回答 → Obsidian 格式 md
- 处理：
  - Front Matter：`course / type / generated_at / tags`（模板外置 config.yaml；
    题型文件额外带 `type_name` 字段）
  - 标题层级规整：确保文档有且仅有一个 H1
  - LaTeX 定界符统一为 `$...$` / `$$...$$`（NotebookLM 输出偶有 `\(...\)` 形式）
  - 内链：不主动改写；Prompt 中约定输出 `[[...]]` 链接（如 `[[Maxwell方程]]`），
    生成器仅做格式校验
- 输出目录结构（镜像 Vault 目标结构）：
  ```
  output/<课程>/md/
  ├── 知识结构.md
  ├── 公式总结.md
  └── 题型/
      ├── 题型总结.md
      └── <题型名>.md ...
  ```

### 3.5 obsidian_sync

- 职责：将 `output/<课程>/md/` 整体复制到 `config.yaml` 指定的 Vault 路径
- 行为：自动创建 `Vault/课程/<课程名>/题型/`；覆盖同名文件；`--dry-run` 只打印目标路径
- 安全校验：目标路径必须位于配置的 Vault 根目录内

### 3.6 main.py（CLI）

argparse 子命令 `login / scan / generate`。编排：读取配置（pydantic 校验）→
按子命令调度上述模块。退出码：0 成功，1 配置/参数错误，2 运行时失败（部分 Prompt
失败也计 2，但已成功的产物保留）。

## 4. 配置设计

### config.yaml

```yaml
paths:
  courses_dir: ./courses
  output_dir: ./output
  logs_dir: ./logs
obsidian:
  vault_path: ""            # 必填，如 D:/Obsidian/Vault
  course_folder: 课程
notebooklm:
  upload_wait_timeout: 300  # 单文件索引等待秒数
  source_limit_warn: 50     # 免费版上限，超出告警
prompt_runner:
  retry: 1
  max_question_types: 12   # 阶段二题型数量上限（chats 配额保护）
markdown:
  front_matter_template: ...
file_types:
  - .pdf
  - .ppt
  - .pptx
  - .doc
  - .docx
  - .jpg
  - .jpeg
  - .png
  - .webp
  - .gif
```

pydantic 模型校验：启动时发现缺失/非法配置立即失败并给出可读错误。

### prompts.yaml（初稿由开发方提供，需求方审阅）

- 固定模板 3 条：
  - `knowledge_structure` 知识结构：整本书的章节结构、章节间依赖关系、学习路线
  - `question_type_summary` 题型总结：遍历资料识别常考题型，每类给出高频解法概要；
    **末尾按约定格式输出题型清单表格（供程序解析）**，且题型数 ≤ max_question_types
  - `formula_summary` 公式总结：全书公式清单、适用条件、记忆要点
- 动态模板 1 条：
  - `question_type_detail` 题型详解（占位符 `{type_name}`）：该题型的典型例题
    （含完整解答过程）、高频解法与解题步骤、易错点提醒、与其他题型的联系

## 5. 错误处理

| 场景 | 行为 |
|------|------|
| 课程目录不存在 / 为空 | 明确报错退出（exit 1） |
| Cookie 过期（auth 失败） | 提示运行 `courseLM login`，exit 2 |
| 单文件上传失败 | 记录、跳过、继续；若全部失败则中止 |
| 题型总结解析失败（无清单表格） | 阶段二中止，保留阶段一产物；提示重跑该 Prompt |
| 单 Prompt 失败 | 重试 1 次后跳过，其余继续；结束时汇总失败清单 |
| Vault 路径未配置 | generate 前置校验失败，exit 1 |

## 6. 测试策略

- **单元测试**（pytest）：file_manager（临时目录 + 各类扩展名）、markdown_generator
  （伪造回答文本验证 Front Matter/公式/标题）、obsidian_sync（dry-run 路径计算）、
  **题型清单解析**（伪造题型总结文本，验证表格提取/名称清洗/上限截断）
- **手动验证脚本**：notebooklm 适配层（login → 建测试 notebook → 传 1 个文件 →
  问 1 个问题 → 删除 notebook），因为依赖真实账号，不进自动化测试
- **端到端**：用一门真实课程完整跑 `generate`，核对 Vault 产物

## 7. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| notebooklm-py 与内部 API 不兼容（Google 改协议） | 低-中 | pyproject 锁版本；升级前冒烟测试；上游活跃维护 |
| Cookie 过期 | 低 | 库自动刷新；过期时提示重新 login |
| 大 PDF 索引超时 | 中 | 超时可配置；失败跳过继续 |
| 回答格式漂移 | 中 | markdown_generator 防御性清洗 |
| 题型总结输出不含可解析清单（模型不听格式指令） | 中 | Prompt 强约束格式 + 多重解析策略（表格→编号标题）+ 明确报错引导重跑 |
| 题型间上下文依赖（阶段二需知道其他题型名才能写"联系"） | 低 | 阶段二 Prompt 中附上完整题型清单，让模型可引用 |
| chats 配额耗尽（单课 3+N 次） | 低-中 | max_question_types 上限 + 缓存续跑 + 用量提示 |
| 非官方接口的 ToS 灰色地带 | — | 个人低频使用；与 UI 自动化同级风险 |

## 8. 开发计划

| 阶段 | 内容 | 验证 |
|------|------|------|
| M0 | 骨架：目录、pyproject、config.yaml + prompts.yaml、日志 | 配置加载自检 |
| M1 | file_manager | 单元测试 + `scan` 实测 |
| M2 | notebooklm 适配层 + login | 手动全链路验证脚本 |
| M3 | prompt_runner 两阶段编排 + 题型解析 + 缓存 | `--prompts question_type_summary` 单 Prompt 调试；题型解析单测 |
| M4 | markdown_generator | 单元测试 |
| M5 | obsidian_sync | dry-run |
| M6 | CLI 集成 + 端到端 | 真实课程完整跑通 |

## 9. 未来扩展（本期不实现）

自动生成学习计划、错题系统、多课程批处理、知识图谱、AI 复习助手。
notebooklm-py 还提供 quiz/flashcards/mind-map 生成能力，可作为错题系统的技术底座。
