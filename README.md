# CourseLM

[中文](README.md) | [English](README.en.md)

把课程资料交给 NotebookLM，生成适合初学者的 Markdown / PDF 复习讲义。

项目只围绕一条流程：**上传资料 → 分析大纲 → 生成绪论和章节 → 导出讲义**。每章按“标准例题 → 逐步讲解 → 方法归纳 → 自己练习”组织，保留公式清洗、章节缓存和失败续跑。题型索引从生成的章节直接提取，不额外请求 AI。

## 快速开始

需要 Python 3.11+、Google 账号和可访问 NotebookLM 的网络。在项目目录运行：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\courselm login
```

默认使用 Chromium 登录；如使用已安装的 Chrome，可将 `config/config.yaml` 中的 `notebooklm.browser` 改为 `chrome`，跳过 Chromium 安装。

将 PDF、PPT/PPTX、DOC/DOCX 或图片放进 `courses/<课程名>/`，然后运行：

```powershell
.venv\Scripts\courselm generate 电磁场
```

命令自动完成资料扫描、上传、内容生成和讲义组装。有 XeLaTeX 时自动导出 PDF；没有时保留 Markdown 和 LaTeX 源码并提示后续导出方式。无需安装或配置 Obsidian。

## 三个命令

| 命令 | 用途 |
| --- | --- |
| `courselm login` | 首次登录，或登录态过期后重新登录 |
| `courselm generate <课程名>` | 一次完成内容生成、讲义组装和可用时的 PDF 导出 |
| `courselm export-handout <课程名>` | 从已有本地 Markdown 重新组装和导出 PDF，不访问 NotebookLM |

`generate --no-pdf` 只生成 Markdown 和 LaTeX 源码。`generate --fresh` 清空当前生成缓存并重新上传资料、生成内容。普通重跑会跳过已成功的有效缓存，自动补齐失败章节。

PDF 需要 TeX Live 或 MiKTeX 提供的 `xelatex`，并加入 PATH。编译失败返回非零状态，Markdown 仍保留；修复编译环境后执行 `export-handout` 即可。输入不完整时不会发布 PDF。

## 输出位置

```text
output/<课程名>/
├── md/
│   ├── 00-绪论.md
│   ├── chapters/01-章节名.md
│   └── appendix/02-典型题型索引.md
├── handout/
│   ├── manuscript.md
│   └── main.tex
├── release/<课程名>-期末复习讲义.pdf
├── raw/v3/                   # 生成缓存
└── state.json                # 上传记录
```

登录态仍存放在项目的 `user_data/`，日志在 `logs/`。讲义内容面向有高中基础、刚开始复习大学课程的学生，保留例题来源标记、解题理由、练习提示和解答。

## 配置

`config/config.yaml` 管理资料、输出、浏览器和代理。请把 `network.proxy` 设为适合当前网络的地址，或用 `auto` / `none`。

Obsidian 同步默认关闭；填写已有 Vault 的路径即可启用：

```yaml
obsidian:
  vault_path: 'D:/Obsidian/Vault'
  course_folder: 课程
```

同步只复制本次生成的文档，失败不会删除本地讲义。将 `vault_path` 留空或省略整个 `obsidian` 配置即可关闭。

`config/prompts.yaml` 管理大纲、绪论和章节提示词。`config/handout_templates/default.yaml` 管理讲义排版；已有的 `courses/<课程名>/handout.yaml` 标题、配色及目录覆盖仍可使用。

## 从旧版迁移

GUI 和 Windows Portable 构建已移除，统一使用 Python 命令行。`scan` 和 `build-handout` 已合并进 `generate`；`--stage`、`--chapter` 已移除，失败后重跑同一命令即可续跑。

不再生成公式汇总、AI 题型索引和考前提要三个附录。保留从章节提取的题型索引，默认讲义不再收录旧公式汇总或考前提要。旧输出与登录态不会因升级被清空；当前 v3 章节缓存可继续复用。历史设计记录位于 `docs/superpowers/`，当前流程见 [设计说明](docs/design.md)。

## 开发与测试

```powershell
.venv\Scripts\python -m pytest tests/ -q
```

测试通过 FakeClient 验证 NotebookLM 适配、缓存、Markdown、讲义和导出流程，不访问真实服务。CI 在 Windows 的 Python 3.11 / 3.12 上运行。

核心代码位于 `main.py` 和 `modules/`，配置位于 `config/`。本项目使用 [notebooklm-py](https://github.com/teng-lin/notebooklm-py) 访问 NotebookLM。

[MIT License](LICENSE)
