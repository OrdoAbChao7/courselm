# CourseLM

[中文](README.md) | [English](README.en.md)

[![CI](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml/badge.svg)](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

CourseLM 将课程资料交给 NotebookLM 处理，自动生成可导入 Obsidian、也可导出为 PDF 的“考前三天冲刺讲义”。默认面向基础薄弱、临近期末的学生，重点是搭结构、抓考点、识别题型和减少可避免失分。

## 下载 Portable 版

Windows 用户可以从 [最新 GitHub Actions 构建](https://github.com/OrdoAbChao7/courselm/actions) 的 Artifact 下载 `CourseLM-portable-windows-x64.zip`。

Portable 版无需安装 Python 或 Playwright 浏览器，解压后双击 `CourseLM.exe` 即可。电脑需要预先安装 Google Chrome，并能访问 NotebookLM。

首次使用：

1. 解压 ZIP，不要直接在压缩包内运行。
2. 编辑 `config/config.yaml`，将 `obsidian.vault_path` 改为你的 Obsidian Vault 路径。
3. 双击 `CourseLM.exe`，点击“登录 NotebookLM”完成 Google 登录。
4. 将资料放入 `courses/<课程名>/`，在窗口中选择课程并点击生成。

登录态、缓存和日志保存在 Portable 目录的 `user_data/`、`output/` 和 `logs/` 中。升级版本时可以保留这些目录。

## Python 开发版

要求 Windows 或其他支持 Python 的系统、Python 3.11+、可访问 Google 的网络环境，以及可选的 Obsidian。

```powershell
git clone https://github.com/OrdoAbChao7/courselm.git
cd courselm
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\courselm login
.venv\Scripts\courselm generate 电磁场
```

资料支持 PDF、PPT、DOCX 和图片。常用命令：

```powershell
.venv\Scripts\courselm scan 电磁场
.venv\Scripts\courselm generate 电磁场 --fresh
.venv\Scripts\courselm generate 电磁场 --stage outline
```

## 生成“考前三天冲刺讲义”

首次使用新目录时请加 `--fresh`，旧缓存不会自动变成新模块：

```powershell
.venv\Scripts\courselm generate 电磁场 --fresh
```

一次完整生成先分析课程结构，再分别生成绪论、每一章和三个附录。每个阶段独立缓存，单章失败可以单独恢复：

```powershell
.venv\Scripts\courselm build-handout 电磁场
.venv\Scripts\courselm export-handout 电磁场
```

产物位于 `output/<课程名>/handout/` 和 `output/<课程名>/release/`。导出 PDF 前需要安装带 XeLaTeX 的 TeX Live 或 MiKTeX，并将其 `bin` 目录加入 PATH。讲义是人工审阅初稿，正式出售前请检查事实、公式、例题、个人信息和版权。

开发调试命令：

```powershell
.venv\Scripts\courselm generate 电磁场 --stage outline
.venv\Scripts\courselm generate 电磁场 --stage introduction
.venv\Scripts\courselm generate 电磁场 --chapter 3
.venv\Scripts\courselm generate 电磁场 --stage appendices
```

## 工作流程与输出

```text
扫描课程资料 → 创建/复用 NotebookLM Notebook → 上传资料
→ 分析课程结构 JSON → 生成绪论 → 逐章生成 → 生成三个附录
→ 清洗 Markdown → 组装 LaTeX/PDF → 同步 Obsidian
```

生成目录示例：

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

输出经过统一 Markdown Sanitizer 处理：解码 HTML Entity、清理 HTML 残留、保护普通 Markdown，并只在数学区域修复 LaTeX 下标转义。公式使用 `$...$` 或 `$$...$$`，适配 Obsidian MathJax。

## 配置

| 文件 | 用途 |
|---|---|
| `config/config.yaml` | 路径、Vault、超时、重试和资料类型 |
| `config/prompts.yaml` | Prompt 模板 |
| `config/handout_templates/default.yaml` | 通用讲义目录、标题和 LaTeX 样式 |
| `config/config.portable.yaml` | Portable 默认配置模板 |

单门课程需要不同的标题、配色或目录时，可创建 `courses/<课程名>/handout.yaml`。标量覆盖默认值，`latex` 配色按键合并；提供 `sections` 时会完整替换默认目录：

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

## 从源码构建 Portable ZIP

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

产物为 `release/CourseLM-portable-windows-x64.zip`。构建脚本会先运行完整测试，并检查发布包不含登录态、密钥或 Chromium 浏览器二进制。

## 测试

```powershell
.venv\Scripts\python -m pytest tests/ -q
```

测试不访问真实 NotebookLM，使用 FakeClient 覆盖 NotebookLM 适配层。NotebookLM 是非官方接口，Google 页面或接口变化可能需要更新 `notebooklm-py`。

## License

[MIT](LICENSE)
