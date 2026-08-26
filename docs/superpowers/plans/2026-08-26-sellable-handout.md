# Sellable Handout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local pipeline that converts generated Obsidian Markdown into an exam-focused Markdown manuscript and XeLaTeX source/PDF.

**Architecture:** Keep NotebookLM generation unchanged. Add a pure local `handout_builder` module that discovers and orders existing Markdown, a `latex_renderer` module that converts the supported Markdown subset, and CLI commands that build or compile artifacts under `output/<course>/handout` and `output/<course>/release`.

**Tech Stack:** Python 3.11, pathlib, argparse, pytest, XeLaTeX subprocess, existing PyYAML/Pydantic configuration.

**Spec:** `docs/superpowers/specs/2026-08-26-sellable-handout-design.md`

## Global Constraints

- Target audience is students with average foundations and little time before finals.
- First release is local and human-reviewable; no payment, publishing, watermark, or DRM.
- Do not add a NotebookLM call to the handout commands.
- All generated artifacts stay under configured `output_dir`.
- Missing inputs and LaTeX failures must be explicit and must not be reported as success.
- Use XeLaTeX with `ctexart` and keep formulas in LaTeX form.

### Task 1: Add handout input discovery and manuscript assembly

**Files:**
- Create: `modules/handout_builder.py`
- Create: `tests/test_handout_builder.py`

**Interfaces:**
- `build_handout(course: str, output_dir: Path, *, max_types: int = 12) -> HandoutBuildResult`
- `HandoutBuildResult.manuscript_path: Path`
- `HandoutBuildResult.tex_path: Path`
- `HandoutBuildResult.missing_inputs: tuple[str, ...]`

- [ ] **Step 1: Write failing tests** for stable section order, dynamic question files, missing-input reporting, and traversal-safe output paths.
- [ ] **Step 2: Run `pytest tests/test_handout_builder.py -q`** and confirm collection fails because `modules.handout_builder` is absent.
- [ ] **Step 3: Implement discovery and assembly** using `output/<course>/md`, fixed files first, `题型/*.md` sorted lexically, and a manuscript with a compact exam-focused preface plus source markers.
- [ ] **Step 4: Run the focused tests** and confirm they pass.
- [ ] **Step 5: Commit** with `git add modules/handout_builder.py tests/test_handout_builder.py && git commit -m "feat: assemble exam handout manuscript"`.

### Task 2: Add Markdown-to-LaTeX rendering

**Files:**
- Create: `modules/latex_renderer.py`
- Create: `tests/test_latex_renderer.py`

**Interfaces:**
- `render_markdown_to_latex(markdown: str) -> str`
- `write_latex_document(manuscript: str, destination: Path, title: str) -> Path`

- [ ] **Step 1: Write failing tests** for `ctexart`, heading conversion, lists, math preservation, table fallback, and Obsidian-link cleanup.
- [ ] **Step 2: Run the focused tests** and confirm they fail because the renderer is absent.
- [ ] **Step 3: Implement the smallest line-oriented renderer** for the supported Markdown subset and a fixed LaTeX document template.
- [ ] **Step 4: Run the focused tests** and confirm they pass.
- [ ] **Step 5: Commit** with `git add modules/latex_renderer.py tests/test_latex_renderer.py && git commit -m "feat: render handout markdown as latex"`.

### Task 3: Add CLI build/export commands

**Files:**
- Modify: `main.py`
- Modify: `tests/test_cli_generate.py` or create `tests/test_cli_handout.py`

**Interfaces:**
- `courselm build-handout <course>` calls `build_handout` and prints artifact paths.
- `courselm export-handout <course>` calls `build_handout`, then invokes `xelatex` twice in the handout directory and copies the PDF to `release`.

- [ ] **Step 1: Write failing CLI tests** for build success, missing source, missing xelatex, and compiler nonzero exit.
- [ ] **Step 2: Run the focused tests** and confirm the parser rejects the new commands or handlers are absent.
- [ ] **Step 3: Add argparse subcommands and small command handlers**; inject the compiler executable through a module-level helper so tests can use a temporary fake compiler.
- [ ] **Step 4: Run the focused CLI tests** and confirm they pass.
- [ ] **Step 5: Commit** with `git add main.py tests/test_cli_handout.py && git commit -m "feat: add handout build and export commands"`.

### Task 4: Add configuration, documentation, and full verification

**Files:**
- Modify: `README.md`
- Modify: `README.en.md` only if the command section is mirrored
- Modify: `docs/design.md`
- Modify: `.gitignore` if generated handout artifacts need exclusion

- [ ] **Step 1: Add tests** for configured output paths and verify generated artifacts never escape `output_dir`.
- [ ] **Step 2: Update docs** with the new commands, expected directory layout, XeLaTeX prerequisite, and manual review warning.
- [ ] **Step 3: Run `git diff --check`**.
- [ ] **Step 4: Run `.venv\Scripts\python -m pytest tests/ -q` and record the full result.
- [ ] **Step 5: Run a real local `build-handout` against a fixture course and inspect `main.tex`; if XeLaTeX is installed, run `export-handout` and inspect the PDF artifact.
- [ ] **Step 6: Commit** with `git add README.md README.en.md docs/design.md .gitignore tests modules main.py && git commit -m "docs: document handout product workflow"`.
