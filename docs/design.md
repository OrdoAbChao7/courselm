# CourseLM 当前设计

更新日期：2026-10-03。生成内容沿用 schema 3。

## 目标与范围

为有高中基础、刚开始复习课程的学生生成按章组织的讲义。每类题保留必要概念、标准例题、解释原因的解题步骤、方法归纳、练习提示与解答。课程范围和题目来源以资料为依据。

主流程为资料扫描与上传、大纲分析、绪论、逐章内容、Markdown 清洗、本地索引、讲义组装和 PDF 导出。移除 GUI、Portable 构建、独立扫描/组装命令、阶段选择参数及三个 AI 附录。

## 命令与数据流

- `login`：调用 notebooklm-py 登录；登录态仍位于项目 `user_data/`。
- `generate <课程>`：扫描课程目录，上传未记录的资料，生成大纲/绪论/章节，输出 Markdown，组装 manuscript.md 与 main.tex。有 XeLaTeX 时编译两次并复制 PDF 到 release/。
- `export-handout <课程>`：只读取本地 Markdown，重新组装并导出 PDF，不调用 NotebookLM。

`--no-pdf` 跳过自动编译。`--fresh` 清空当前生成缓存并重置上传记录，重新上传和生成。普通重跑自动跳过有效缓存。

## 模块职责

| 模块 | 职责 |
| --- | --- |
| main | 命令入口、串联生成与导出、错误状态 |
| config / path_manager / network | 配置、项目路径、登录态和代理 |
| file_manager / notebooklm | 资料清单、服务适配与上传 |
| prompts / prompt_runner | 提示词、章节结构检查、缓存续跑 |
| markdown_sanitizer / markdown_generator | 公式与 Markdown 清洗、文档输出 |
| question_index | 从章节例题提取索引和链接 |
| handout_template / handout_builder / latex_renderer | 模板、讲义组装与 LaTeX 排版 |
| obsidian_sync | 可选复制本次生成的 Markdown |

## 输出与兼容

章节缓存继续使用 `output/<课程>/raw/v3/`，以保留已有内容。Markdown 在 `md/`，讲义与 LaTeX 在 `handout/`，PDF 在 `release/`。

不再向 AI 请求公式汇总、题型索引或考前提要。索引从本次成功章节直接提取，默认模板只保留这一份附录。已有输出不会因升级被删除，旧附录不会由默认模板纳入新讲义。已有课程模板覆盖仍受支持。

Obsidian 配置可省略或留空。启用后只同步本次输出，不重新复制目录里的历史遗留文件。

## 失败处理与验证

单章生成失败保留其他成功章节，重跑时自动恢复；本次生成有失败时不自动发布 PDF。离线导出也会检查所需输入是否完整。

缺少 XeLaTeX 时，普通生成成功保留 Markdown 和源码，明确提示后续导出命令；显式导出失败返回非零状态。编译或可选同步失败不会删除本地 Markdown。

测试通过 FakeClient 覆盖生成、缓存、索引、无 Vault 运行、自动 PDF 导出及失败保留产物；CI 在 Windows Python 3.11 / 3.12 上运行。历史方案留在 `docs/superpowers/`，不作为当前命令契约。
