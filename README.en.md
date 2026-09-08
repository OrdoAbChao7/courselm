# CourseLM

[中文](README.md) | [English](README.en.md)

<div align="center">

[![CI](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml/badge.svg)](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

# Turn course PDFs into a "three-day final-exam crash handout"

CourseLM is an automation pipeline: it sends your course materials (PDF / PPT / DOCX / images) to NotebookLM and generates structured review handouts that import into Obsidian and export to PDF. The default product is designed for students with weak foundations days before the final — build the map, focus on core exam points, recognize question types, and avoid preventable mistakes.

Set it up once, then every course is one command:

```powershell
courselm generate Electromagnetics
```

## ✨ Features

- 🧭 **Course-outline driven** — analyzes your textbook structure into an outline JSON first, then generates the introduction, each chapter, and three appendices; content always follows your actual course
- 📚 **Powered by NotebookLM** — no DIY scraping API; reuses NotebookLM's source comprehension with PDF, PPT/PPTX, DOC/DOCX, and image files
- ♻️ **Per-stage caching** — every generation stage is cached independently; a failed chapter reruns on its own, and `--fresh` resets everything
- 📕 **One-command PDF handout** — assembles the Markdown draft into LaTeX (XeLaTeX) source and compiles an academically typeset PDF; outline, title, and colors are customizable per course
- 🧹 **Obsidian-native output** — one unified Markdown Sanitizer decodes HTML, strips residue, and repairs LaTeX escaping only inside math regions; `$...$` / `$$...$$` work with Obsidian MathJax
- 🖥️ **Windows Portable + GUI** — a portable build that needs no Python, launched by double-click, with login / course selection / generation in a GUI
- 🧪 **Zero-network tests** — the full pytest suite covers the NotebookLM adapter through a FakeClient; CI verifies Python 3.11 / 3.12 on Windows

<!-- Add demo GIF here: record the generate → build-handout → export-handout flow -->

## 🚀 Getting Started

### Option 1: Portable build (recommended for Windows users)

Download `CourseLM-portable-windows-x64.zip` from the [latest GitHub Actions build](https://github.com/OrdoAbChao7/courselm/actions) artifacts. No Python or Playwright browser required.

First use:

1. Extract the ZIP before running (do not run from inside the archive).
2. Edit `config/config.yaml` and set `obsidian.vault_path` to your Obsidian Vault path.
3. Double-click `CourseLM.exe`, then click "登录 NotebookLM" to complete Google sign-in.
4. Put source files in `courses/<course-name>/`, select the course, and start generation.

**Requirements:** Windows 10/11, Google Chrome preinstalled, and network access to NotebookLM. Login state, cache, and logs live in the Portable directory under `user_data/`, `output/`, and `logs/`; keep these folders when upgrading.

### Option 2: Python development version

Requirements: Python 3.11+, network access to Google, and optionally Obsidian.

```powershell
git clone https://github.com/OrdoAbChao7/courselm.git
cd courselm
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\courselm login
.venv\Scripts\courselm generate 电磁场
```

## 📖 CLI Reference

| Command | Description |
|---|---|
| `courselm login` | Open a browser and sign in to NotebookLM (once) |
| `courselm scan <course>` | Scan `courses/<course>/` and list recognized files |
| `courselm generate <course> [--fresh]` | Full pipeline: outline → introduction → chapters → appendices |
| `courselm generate <course> --stage {outline,introduction,appendices}` | Rerun one stage only (debugging) |
| `courselm generate <course> --chapter <N>` | Regenerate chapter N only |
| `courselm build-handout <course>` | Assemble Obsidian Markdown into a handout draft + LaTeX source |
| `courselm export-handout <course>` | Compile LaTeX and export the PDF to `output/<course>/release/` |

> Add `--fresh` on your first run: legacy cache entries are not automatically rewritten to the new module set.

## 🏗️ Workflow and Output

```text
Scan course files → create/reuse a NotebookLM notebook → upload files
→ analyze course-outline JSON → introduction → chapters → three appendices
→ sanitize Markdown → assemble LaTeX/PDF → sync to Obsidian
```

Directory synced into the Obsidian Vault:

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

Handout artifacts: `output/<course>/handout/` (Markdown draft and LaTeX source) and `output/<course>/release/` (PDF). Before exporting, install TeX Live or MiKTeX with XeLaTeX and add its `bin` directory to PATH.

> The handout is a **human-reviewed draft**: check facts, formulas, examples, personal information, and copyright before using or selling it.

## ⚙️ Configuration

| File | Purpose |
|---|---|
| `config/config.yaml` | Paths, Obsidian Vault, browser, proxy, timeouts, retries, source file types |
| `config/prompts.yaml` | Per-stage prompt templates (appendix trio + dynamic chapter template) |
| `config/handout_templates/default.yaml` | Default handout order, title/subtitle, and LaTeX colors |
| `config/config.portable.yaml` | Portable default configuration template |

To customize one course, create `courses/<course>/handout.yaml`. Scalar values override defaults, `latex` color keys are merged, and a supplied `sections` list replaces the default outline:

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

Commonly used `config.yaml` keys:

| Key | Description |
|---|---|
| `paths.courses_dir / output_dir / logs_dir` | Course materials, intermediate artifacts, and log directories (relative to the project root) |
| `obsidian.vault_path` | [Required] Root directory of your Obsidian Vault |
| `obsidian.course_folder` | Folder inside the Vault that stores courses (default `课程`) |
| `notebooklm.browser` | Login browser: `chromium` (Playwright built-in) / `chrome` / `msedge` |
| `notebooklm.source_limit_warn` | Sources-per-notebook warning threshold (free tier limit is 50) |
| `network.proxy` | Proxy for the NotebookLM network environment; set to `none` when not needed |
| `prompt_runner.retry` | Retries per failed prompt |

## 📁 Project Structure

<details>
<summary>Click to expand</summary>

```text
├── main.py                     # CLI entry: login / scan / generate / build-handout / export-handout
├── launcher.py                 # Windows GUI launcher for the Portable build
├── modules/                    # Core modules
│   ├── file_manager.py         #   Course file scanning and manifests
│   ├── notebooklm.py           #   NotebookLM adapter (wraps notebooklm-py)
│   ├── prompt_runner.py        #   Two-stage pipeline orchestration and caching
│   ├── markdown_sanitizer.py   #   Markdown/LaTeX sanitizing
│   ├── handout_builder.py      #   Handout assembly (Obsidian MD → draft)
│   ├── handout_template.py     #   Handout outline template loading and merging
│   ├── latex_renderer.py       #   LaTeX source rendering
│   └── obsidian_sync.py        #   Sync into the Vault
├── config/                     # config.yaml / prompts.yaml / handout_templates/
├── scripts/                    # build_portable.ps1 / build_launcher.ps1 and more
├── tests/                      # 18 test files, FakeClient zero-network coverage
└── docs/design.md              # Design document
```

</details>

## 🔨 Build the Portable ZIP from Source

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

The output is `release/CourseLM-portable-windows-x64.zip`. The build script runs the full test suite first and checks that the package contains no login state, secrets, or Chromium browser binaries.

## 🧪 Testing

```powershell
.venv\Scripts\python -m pytest tests/ -q
```

Tests do not access a real NotebookLM account; the NotebookLM adapter is covered with a FakeClient. NotebookLM has no official API — this project builds on the reverse-engineered internal RPC client [notebooklm-py](https://github.com/teng-lin/notebooklm-py), so Google changes to its pages or APIs may require updating that dependency.

## 📄 License

[MIT](LICENSE)

## 🙏 Acknowledgments

- [notebooklm-py](https://github.com/teng-lin/notebooklm-py) — reverse-engineered NotebookLM RPC client
- [Obsidian](https://obsidian.md/) and [Obsidian MathJax](https://publish.obsidian.md/) — the final home of the review documents

---

<div align="center">

**[OrdoAbChao7](https://github.com/OrdoAbChao7)** · If this helps, please give it a ⭐

[![GitHub](https://img.shields.io/badge/GitHub-OrdoAbChao7-181717?logo=github&logoColor=white)](https://github.com/OrdoAbChao7)

</div>
