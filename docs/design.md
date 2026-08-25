# CourseLM Automation Pipeline — 设计文档

- 日期：2026-08-25
- 状态：已与需求方确认（技术路线、复用策略、Prompt 来源）
- 项目位置：`e:\Projects\note-agent`

## 1. 项目目标

个人课程资料自动化处理系统。将大学课程资料放入 `courses/<课程名>/`，执行：

```
courseLM generate 电磁场
```

即在 Obsidian Vault 中生成 6 个结构化复习文档：

```
<Vault>/课程/电磁场/
├── 00_课程知识体系.md
├── 01_高频考点分析.md
├── 02_核心知识点.md
├── 03_题型与通用解法.md
├── 04_易错点.md
└── 05_公式总结.md
```

完整流水线：扫描资料 → 上传 NotebookLM → 执行 6 个固定 Prompt → 转换为 Obsidian Markdown → 写入 Vault。

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
2. 已成功的 Prompt 直接读 `output/<课程>/raw/<id>.md` 缓存跳过（省 chats 配额）
3. 输出 md 直接覆盖（Obsidian 自带文件历史）
4. `--fresh` 强制新建 Notebook、清空缓存重跑

### D3 Prompt 外置（已确认）

Prompt 全部放在 `config/prompts.yaml`，含 `id / title / output_file / template` 四个字段。
用户审阅初稿后可持续自行修改，不改代码。

### D4 异步架构

notebooklm-py 基于 asyncio。流水线内部全 async，`main.py` 顶层 `asyncio.run()`。
Windows 平台事件循环策略由 notebooklm-py 自动处理。

### D5 CLI 设计（标准库 argparse）

```
courseLM login                     # 首次登录（调 notebooklm-py 登录流程）
courseLM scan <课程名>              # 只扫描，列出识别到的资料清单
courseLM generate <课程名>          # 完整流水线
courseLM generate <课程名> --prompts 00,01   # 只跑指定 Prompt（调试）
courseLM generate <课程名> --fresh  # 强制新建 Notebook 重跑
```

### D6 日志与可诊断性

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

- 职责：编排 6 个 Prompt 的执行、缓存读写、失败重试
- 流程：加载 prompts.yaml → 逐个执行（缓存命中则跳过）→ 每个回答立即落盘
  `output/<课程>/raw/<id>.md` → 返回全部（成功 + 失败清单）
- 重试：单 Prompt 网络类失败重试 1 次（可配置）；失败不中断整批
- 计数：累计当日 chats 用量提示（免费版 50/天上限）

### 3.4 markdown_generator

- 职责：raw 回答 → Obsidian 格式 md
- 处理：
  - Front Matter：`course / generated_at / tags`（模板外置 config.yaml）
  - 标题层级规整：确保文档有且仅有一个 H1
  - LaTeX 定界符统一为 `$...$` / `$$...$$`（NotebookLM 输出偶有 `\(...\)` 形式）
  - 内链：不主动改写；Prompt 中约定输出 `[[...]]` 链接（如 `[[Maxwell方程]]`），
    生成器仅做格式校验
- 输出：`output/<课程>/md/<NN>_<名称>.md`

### 3.5 obsidian_sync

- 职责：将 `output/<课程>/md/` 复制到 `config.yaml` 指定的 Vault 路径
- 行为：自动创建 `Vault/课程/<课程名>/`；覆盖同名文件；`--dry-run` 只打印目标路径
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

6 条：00 课程知识体系（章节结构/知识依赖/学习路线）、01 高频考点（高频知识/
考试重点/分值价值）、02 核心知识（定义/公式/物理意义/应用/易错点）、
03 题型与通用解法（典型题型/解题步骤/通用方法）、04 易错点（常见错误/原因/避免）、
05 公式总结（全公式清单/适用条件/记忆要点）。

## 5. 错误处理

| 场景 | 行为 |
|------|------|
| 课程目录不存在 / 为空 | 明确报错退出（exit 1） |
| Cookie 过期（auth 失败） | 提示运行 `courseLM login`，exit 2 |
| 单文件上传失败 | 记录、跳过、继续；若全部失败则中止 |
| 单 Prompt 失败 | 重试 1 次后跳过，其余继续；结束时汇总失败清单 |
| Vault 路径未配置 | generate 前置校验失败，exit 1 |

## 6. 测试策略

- **单元测试**（pytest）：file_manager（临时目录 + 各类扩展名）、markdown_generator
  （伪造回答文本验证 Front Matter/公式/标题）、obsidian_sync（dry-run 路径计算）
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
| chats 配额耗尽 | 低 | 缓存续跑 + 用量提示 |
| 非官方接口的 ToS 灰色地带 | — | 个人低频使用；与 UI 自动化同级风险 |

## 8. 开发计划

| 阶段 | 内容 | 验证 |
|------|------|------|
| M0 | 骨架：目录、pyproject、config.yaml + prompts.yaml、日志 | 配置加载自检 |
| M1 | file_manager | 单元测试 + `scan` 实测 |
| M2 | notebooklm 适配层 + login | 手动全链路验证脚本 |
| M3 | prompt_runner + 缓存 | `--prompts 00` 单 Prompt 调试 |
| M4 | markdown_generator | 单元测试 |
| M5 | obsidian_sync | dry-run |
| M6 | CLI 集成 + 端到端 | 真实课程完整跑通 |

## 9. 未来扩展（本期不实现）

自动生成学习计划、错题系统、多课程批处理、知识图谱、AI 复习助手。
notebooklm-py 还提供 quiz/flashcards/mind-map 生成能力，可作为错题系统的技术底座。
