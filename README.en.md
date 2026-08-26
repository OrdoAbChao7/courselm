# CourseLM

[中文](README.md) | [English](README.en.md)

[![CI](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml/badge.svg)](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

CourseLM sends course materials to NotebookLM and creates a three-day final-exam crash handout that can be imported into Obsidian or exported as PDF. The default product is designed for students with weak foundations: establish the map, focus on core exam points, recognize question types, and avoid preventable mistakes.

## Download the Portable version

Windows users can download `CourseLM-portable-windows-x64.zip` from the [latest GitHub Actions build](https://github.com/OrdoAbChao7/courselm/actions).

The Portable build does not require Python or a Playwright browser. Extract the ZIP and double-click `CourseLM.exe`. Google Chrome must already be installed, and the computer must be able to reach NotebookLM.

First use:

1. Extract the ZIP before running it.
2. Edit `config/config.yaml` and set `obsidian.vault_path` to your Obsidian Vault path.
3. Double-click `CourseLM.exe`, then click “登录 NotebookLM” to complete Google sign-in.
4. Put source files in `courses/<course-name>/`, select the course, and start generation.

The Portable directory stores login state, cache, and logs in `user_data/`, `output/`, and `logs/`. These directories can be kept when upgrading.

## Python development version

Requirements: Windows or another Python-capable system, Python 3.11+, network access to Google, and optionally Obsidian.

```powershell
git clone https://github.com/OrdoAbChao7/courselm.git
cd courselm
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\courselm login
.venv\Scripts\courselm generate 电磁场
```

Supported source files include PDF, PPT, DOCX, and images. Common commands:

```powershell
.venv\Scripts\courselm scan 电磁场
.venv\Scripts\courselm generate 电磁场 --fresh
.venv\Scripts\courselm generate 电磁场 --prompts question_type_summary
```

## Build a three-day crash handout

Use `--fresh` the first time you adopt the new module set; legacy cache entries are not automatically rewritten:

```powershell
.venv\Scripts\courselm generate 电磁场 --fresh
```

A fresh run uses **12 + N NotebookLM chats**: twelve fixed teaching modules and up to `max_question_types` dynamic question-type tutorials. Then assemble and export the handout:

```powershell
.venv\Scripts\courselm build-handout 电磁场
.venv\Scripts\courselm export-handout 电磁场
```

The Markdown manuscript and LaTeX source are written under `output/<course>/handout/`; the PDF is written under `output/<course>/release/`. Install TeX Live or MiKTeX with XeLaTeX and add its `bin` directory to PATH before exporting. Review facts, formulas, examples, personal information, and copyright before selling the handout.

The default schedule assumes 4–6 hours per day: day one builds the exam map and foundations, day two focuses on formulas and question types, and day three covers mistakes, minimum practice, the cram sheet, and final self-testing.

## Workflow and output

```text
Scan course files → create/reuse a NotebookLM notebook → upload files
→ 12 fixed teaching prompts → parse the question-type map
→ generate N question-type tutorials → sanitize Markdown
→ assemble LaTeX/PDF → sync to Obsidian
```

Example output:

```text
课程/电磁场/
├── 00-使用说明.md
├── 01-考前三天学习规划.md
├── 02-考试地图.md
├── 03-零基础补给站.md
├── 04-一页知识骨架.md
├── 05-核心考点卡.md
├── 06-公式工具箱.md
├── 07-题型识别地图.md
├── 08-高频题型精讲/<题型名>.md
├── 09-易错点诊断室.md
├── 10-最小训练集.md
├── 11-考前速记.md
└── 12-综合自测与补救路线.md
```

All generated output passes through one Markdown Sanitizer. It decodes HTML entities, removes HTML residue, preserves ordinary Markdown, and repairs escaped LaTeX subscripts only inside math regions. Inline and block formulas use `$...$` and `$$...$$`, compatible with Obsidian MathJax.

## Configuration

| File | Purpose |
|---|---|
| `config/config.yaml` | Paths, Vault, timeouts, retries, and source file types |
| `config/prompts.yaml` | Prompt templates |
| `config/handout_templates/default.yaml` | Default handout order, title, and LaTeX style |
| `config/config.portable.yaml` | Portable default configuration template |

Create `courses/<course>/handout.yaml` to customize one course. Scalar values override defaults, `latex` color keys are merged, and a supplied `sections` list replaces the default directory:

```yaml
title_suffix: Final Exam Problem Manual
subtitle: Customized for this course
latex:
  primary_color: 3B2E5A
sections:
  - id: exam_map
    title: Course Exam Scope
    source: 02-考试地图.md
    required: true
    page_break: true
```

## Build the Portable ZIP from source

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

The output is `release/CourseLM-portable-windows-x64.zip`. The build script runs the full test suite and checks that the package contains no login state, secrets, or Chromium browser binaries.

## Testing

```powershell
.venv\Scripts\python -m pytest tests/ -q
```

Tests do not access a real NotebookLM account; the NotebookLM adapter is covered with a FakeClient. NotebookLM is an unofficial interface, so Google changes to its pages or APIs may require an update to `notebooklm-py`.

## License

[MIT](LICENSE)
