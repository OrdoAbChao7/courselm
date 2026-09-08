# CourseLM

[中文](README.md) | [English](README.en.md)

<div align="center">

[![CI](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml/badge.svg)](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

# 把课程 PDF 变成“考前三天冲刺讲义”

CourseLM 是一条自动化流水线：把课程资料(PDF / PPT / DOCX / 图片)交给 NotebookLM 处理，自动生成可导入 Obsidian、也可导出为 PDF 的结构化复习讲义。默认面向基础薄弱、临近期末的学生——重点是搭结构、抓考点、识别题型，减少可避免失分。

一瓶奶茶的时间配置好，之后每门课只需一条命令：

```powershell
courselm generate 电磁场
```

## ✨ 功能特性

- 🧭 **课程结构驱动** — 先分析教材结构生成大纲 JSON，再按大纲生成绪论、逐章内容和三个附录，内容始终跟随你的课程
- 📚 **NotebookLM 撑腰** — 无需自建 API，直接复用 NotebookLM 的资料理解能力，支持 PDF、PPT/PPTX、DOC/DOCX 和图片
- ♻️ **阶段独立缓存** — 每个生成阶段独立缓存，单章失败单独重跑即可续跑；`--fresh` 一键重置
- 📕 **一键 PDF 讲义** — Markdown 初稿自动组装为 LaTeX(XeLaTeX)源码并编译出学术排版 PDF，目录/标题/配色可按课程定制
- 🧹 **Obsidian 原生输出** — 统一 Markdown Sanitizer:解码 HTML、清理残留，只在数学区修复 LaTeX 转义;`$...$` / `$$...$$` 适配 MathJax
- 🖥️ **Windows Portable + GUI** — 免安装 Python 的便携包，双击即用，图形界面里登录、选课、生成
- 🧪 **零网络测试** — 完整 pytest 套件通过 FakeClient 覆盖 NotebookLM 适配层，CI 在 Windows 上验证 Python 3.11 / 3.12

<!-- Add demo GIF here: 录制 generate → build-handout → export-handout 全流程 -->

## 🚀 快速开始

### 方式一:Portable 版(Windows 用户推荐)

从 [最新 GitHub Actions 构建](https://github.com/OrdoAbChao7/courselm/actions) 的 Artifact 下载 `CourseLM-portable-windows-x64.zip`。无需安装 Python,无需 Playwright 浏览器。

首次使用:

1. 解压 ZIP 后再运行(不要在压缩包内直接运行)
2. 编辑 `config/config.yaml`,把 `obsidian.vault_path` 改为你的 Obsidian Vault 路径
3. 双击 `CourseLM.exe`,点击"登录 NotebookLM"完成 Google 登录
4. 把资料放入 `courses/<课程名>/`,在窗口中选择课程并点击生成

**要求:** Windows 10/11、预装 Google Chrome、能访问 NotebookLM 的网络。登录态、缓存和日志保存在 Portable 目录的 `user_data/`、`output/` 和 `logs/` 中，升级版本时可整体保留。

### 方式二:Python 开发版

要求 Python 3.11+、可访问 Google 的网络环境，可选 Obsidian。

```powershell
git clone https://github.com/OrdoAbChao7/courselm.git
cd courselm
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\courselm login
.venv\Scripts\courselm generate 电磁场
```

## 📖 命令行参考

| 命令 | 说明 |
|---|---|
| `courselm login` | 打开浏览器登录 NotebookLM（仅需一次） |
| `courselm scan <课程名>` | 扫描 `courses/<课程名>/`，列出识别到的资料清单 |
| `courselm generate <课程名> [--fresh]` | 完整流水线:大纲 → 绪论 → 逐章 → 附录 |
| `courselm generate <课程名> --stage {outline,introduction,appendices}` | 只重跑指定阶段（调试用） |
| `courselm generate <课程名> --chapter <N>` | 只重新生成第 N 章 |
| `courselm build-handout <课程名>` | 从 Obsidian Markdown 组装讲义初稿 + LaTeX 源码 |
| `courselm export-handout <课程名>` | 编译 LaTeX 并导出 PDF 到 `output/<课程名>/release/` |

> 首次生成请加 `--fresh`:旧版本缓存不会自动变成新模块。

## 🏗️ 工作流程与输出

```text
扫描课程资料 → 创建/复用 NotebookLM Notebook → 上传资料
→ 分析课程结构 JSON → 生成绪论 → 逐章生成 → 生成三个附录
→ 清洗 Markdown → 组装 LaTeX/PDF → 同步 Obsidian
```

同步到 Obsidian Vault 的目录结构：

```text
课程/电磁场/
├── 00-绪论.md
├── chapters/
│   ├── 01-静电场.md
│   └── 02-电势.md
└── appendix/
    ├── 01-重要公式汇总.md
    ├── 02-典型题型索引.md
    └── 03-考前复习提要.md
```

讲义产物:`output/<课程名>/handout/`(Markdown 初稿与 LaTeX 源码)、`output/<课程名>/release/`(PDF)。导出 PDF 前需要安装带 XeLaTeX 的 TeX Live 或 MiKTeX,并把其 `bin` 目录加入 PATH。

> 讲义是**人工审阅初稿**：正式使用或出售前，请检查事实、公式、例题、个人信息和版权。

## ⚙️ 配置

| 文件 | 用途 |
|---|---|
| `config/config.yaml` | 路径、Obsidian Vault、浏览器、代理、超时、重试和资料类型 |
| `config/prompts.yaml` | 各阶段 Prompt 模板（附录三件套 + 动态章节模板） |
| `config/handout_templates/default.yaml` | 通用讲义目录、标题副标题和 LaTeX 配色 |
| `config/config.portable.yaml` | Portable 默认配置模板 |

某门课需要不同的标题、配色或目录时，创建 `courses/<课程名>/handout.yaml` 即可。标量覆盖默认值，`latex` 配色按键合并;提供 `sections` 时完整替换默认目录:

```yaml
title_suffix: 期末重点题型手册
subtitle: 适用于本校闭卷考试
latex:
  primary_color: 3B2E5A
sections:
  - id: exam_map
    title: 本校考试范围
    source: 02-考试地图.md
    required: true
    page_break: true
```

常用 `config.yaml` 字段:

| 键 | 说明 |
|---|---|
| `paths.courses_dir / output_dir / logs_dir` | 课程资料、中间产物与日志目录(相对于项目根) |
| `obsidian.vault_path` | 【必填】Obsidian Vault 根目录 |
| `obsidian.course_folder` | Vault 内存放各课程的文件夹名(默认 `课程`) |
| `notebooklm.browser` | 登录浏览器:`chromium`(Playwright 内置)/ `chrome` / `msedge` |
| `notebooklm.source_limit_warn` | 单 Notebook 资料数告警阈值(免费版上限 50) |
| `network.proxy` | NotebookLM 网络环境代理；无代理时改为 `none` |
| `prompt_runner.retry` | 单个 Prompt 失败后的重试次数 |

## 📁 项目结构

<details>
<summary>点击展开</summary>

```text
├── main.py                     # CLI 入口:login / scan / generate / build-handout / export-handout
├── launcher.py                 # Portable 版 Windows 图形启动器
├── modules/                    # 核心模块
│   ├── file_manager.py         #   课程资料扫描与清单
│   ├── notebooklm.py           #   NotebookLM 适配层(封装 notebooklm-py)
│   ├── prompt_runner.py        #   两阶段流水线编排与缓存
│   ├── markdown_sanitizer.py   #   Markdown/LaTeX 清洗
│   ├── handout_builder.py      #   讲义组装(Obsidian MD → 讲义初稿)
│   ├── handout_template.py     #   讲义目录模板加载与覆盖合并
│   ├── latex_renderer.py       #   LaTeX 源码渲染
│   └── obsidian_sync.py        #   同步到 Vault
├── config/                     # config.yaml / prompts.yaml / handout_templates/
├── scripts/                    # build_portable.ps1 / build_launcher.ps1 等
├── tests/                      # 18 个测试文件,FakeClient 零网络覆盖
└── docs/design.md              # 设计文档
```

</details>

## 🔨 从源码构建 Portable ZIP

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

产物为 `release/CourseLM-portable-windows-x64.zip`。构建脚本会先运行完整测试，并检查发布包不含登录态、密钥或 Chromium 浏览器二进制。

## 🧪 测试

```powershell
.venv\Scripts\python -m pytest tests/ -q
```

测试不访问真实 NotebookLM，使用 FakeClient 覆盖 NotebookLM 适配层。NotebookLM 没有官方 API，本项目基于 [notebooklm-py](https://github.com/teng-lin/notebooklm-py) 的逆向内部 RPC 客户端工作;Google 页面或接口变化时可能需要更新该依赖。

## 📄 License

[MIT](LICENSE)

## 🙏 致谢

- [notebooklm-py](https://github.com/teng-lin/notebooklm-py) — NotebookLM 逆向 RPC 客户端
- [Obsidian](https://obsidian.md/) 与 [Obsidian MathJax](https://publish.obsidian.md/) — 复习文档的最终载体

---

<div align="center">

**[OrdoAbChao7](https://github.com/OrdoAbChao7)** · 觉得有用请给个 ⭐

[![GitHub](https://img.shields.io/badge/GitHub-OrdoAbChao7-181717?logo=github&logoColor=white)](https://github.com/OrdoAbChao7)

</div>
