# CourseLM

[中文](README.md) | [English](README.en.md)

Turn course materials into beginner-friendly Markdown and PDF study handouts with NotebookLM.

One workflow: **upload sources → plan chapters → generate introduction and chapters → export handout**. Chapters teach through worked examples, explained steps, reusable methods and practice with solutions. A question-type index is extracted locally; it needs no extra AI requests. Valid chapter caches support automatic recovery.

## Quick start

Requires Python 3.11+, a Google account and network access to NotebookLM. Run from the repository:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\courselm login
```

Alternatively, set `notebooklm.browser: chrome` in `config/config.yaml` to use installed Chrome and skip the Chromium download.

Put PDFs, presentations, Word documents or images in `courses/<course>/`, then run:

```powershell
.venv\Scripts\courselm generate "Electromagnetism"
```

This scans and uploads sources, generates content and assembles the handout. When XeLaTeX is available, it also exports a PDF. Otherwise, Markdown and LaTeX sources remain available. Obsidian is optional.

## Commands

| Command | Purpose |
| --- | --- |
| `courselm login` | Sign in initially or renew expired authentication |
| `courselm generate <course>` | Generate content, assemble the handout and export PDF when available |
| `courselm export-handout <course>` | Rebuild and export existing Markdown locally, without contacting NotebookLM |

Use `generate --no-pdf` to skip PDF compilation. Use `generate --fresh` to clear current generation caches, re-upload sources and regenerate content. Normal reruns reuse valid caches and retry failed chapters.

PDF export requires `xelatex` from TeX Live or MiKTeX on PATH. Compilation failures return a nonzero status and preserve Markdown. After fixing the compiler, rerun `export-handout`. Incomplete inputs are not published as a PDF.

## Output

```text
output/<course>/
├── md/
│   ├── 00-绪论.md
│   ├── chapters/01-<chapter>.md
│   └── appendix/02-典型题型索引.md
├── handout/
│   ├── manuscript.md
│   └── main.tex
├── release/<course>-期末复习讲义.pdf
├── raw/v3/
└── state.json
```

Prompts and generated content default to Chinese. Authentication stays in `user_data/`; logs stay in `logs/`.

## Configuration

`config/config.yaml` controls paths, browser and proxy. Set `network.proxy` to your proxy address, `auto` or `none`.

Obsidian synchronization is disabled by default. To enable it, point to an existing vault:

```yaml
obsidian:
  vault_path: 'D:/Obsidian/Vault'
  course_folder: 课程
```

Only documents generated in the current run are copied. Sync failures preserve local outputs. Leave `vault_path` empty or omit `obsidian` to disable synchronization.

Edit `config/prompts.yaml` for outline, introduction and chapter prompts. Layout lives in `config/handout_templates/default.yaml`. Existing course overrides in `courses/<course>/handout.yaml` remain supported.

## Migration

The GUI and Windows Portable build have been removed. Use the Python CLI. Source scanning and handout assembly now run inside `generate`; the separate `scan` and `build-handout` commands and `--stage` / `--chapter` options are removed.

The three AI-generated appendices are removed. The local chapter index remains; the default handout excludes old formula and final-review appendices. Existing outputs and authentication are preserved, and current v3 chapter caches remain reusable. Historical plans live in `docs/superpowers/`; [the current design](docs/design.md) describes the simplified workflow.

## Development

```powershell
.venv\Scripts\python -m pytest tests/ -q
```

Tests use fake NotebookLM clients without network access. CI runs on Windows with Python 3.11 and 3.12.

Entry point: `main.py`; implementation: `modules/`; configuration: `config/`. Built on [notebooklm-py](https://github.com/teng-lin/notebooklm-py).

[MIT License](LICENSE)
