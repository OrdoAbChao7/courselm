# Course Structure Handout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a versioned, course-outline-driven NotebookLM pipeline that produces a readable university exam handout with dynamic chapters and three appendices.

**Architecture:** Parse one machine-readable course outline, then run independent cached prompts for introduction, each chapter, and the appendices. Convert those artifacts into a deterministic Markdown tree and feed the existing academic Markdown-to-LaTeX renderer.

**Tech Stack:** Python 3.11+, Pydantic, PyYAML, pytest, NotebookLM service, Markdown, XeLaTeX.

**Spec:** `docs/superpowers/specs/2026-09-01-course-structure-handout-design.md`

## Global Constraints

- `generation_schema_version = 2`; new raw artifacts are isolated under `raw/v2/`.
- Chapter count and names are data-driven; the handout template cannot hard-code chapters.
- Source priority is course materials first; unsupported facts use `[待确认]` and inferred facts use `[推测]`.
- LaTeX rendering remains in `modules/latex_renderer.py`.
- Existing temporary `tmp/` and `user_data/` directories are never included in generated commits.

### Task 1: Replace Prompt Schema and configuration

**Files:**
- Modify: `config/prompts.yaml`
- Modify: `modules/prompts.py`
- Test: `tests/test_prompts.py`

- [ ] Add typed planning/global/dynamic prompt models, explicit placeholder validation, and safe render functions.
- [ ] Configure outline, introduction, chapter, formula appendix, question index, and final review prompts with the fixed five-section chapter contract.
- [ ] Test normal configuration, fenced JSON-compatible placeholders, missing prompts, duplicate ids, and invalid placeholders.

### Task 2: Add outline parser and v2 pipeline

**Files:**
- Modify: `modules/prompt_runner.py`
- Test: `tests/test_prompt_runner.py`

- [ ] Add `CourseOutline`/`ChapterPlan` models and a parser that extracts JSON from prose or a JSON fence, validates fields, removes duplicate indexes, sanitizes file names, and rejects empty outlines.
- [ ] Add `run_pipeline_v2` with independent `outline.json`, `introduction.md`, `chapters/<index>-<slug>.md`, and `appendices/*.md` caches.
- [ ] Preserve Notebook reuse, incremental upload, retry, failure isolation, and fresh behavior.
- [ ] Add stage/chapter filters and result counters.

### Task 3: Rebuild Markdown generation and handout assembly

**Files:**
- Modify: `modules/markdown_generator.py`
- Modify: `modules/handout_builder.py`
- Modify: `modules/handout_template.py`
- Modify: `config/handout_templates/default.yaml`
- Test: `tests/test_markdown_generator.py`, `tests/test_handout_builder.py`, `tests/test_handout_template.py`

- [ ] Map v2 outcomes into the prescribed `md/` tree with stable numeric filenames and front matter.
- [ ] Assemble introduction, dynamic chapters, and appendices in outline order; write chapter snapshots under `handout/chapters/`.
- [ ] Remove legacy fixed section names from the default template and validate dynamic sections.
- [ ] Test ordering, missing inputs, path safety, and manuscript/main.tex generation.

### Task 4: Update CLI and documentation

**Files:**
- Modify: `main.py`
- Modify: `README.md`, `README.en.md`, `docs/design.md`
- Test: `tests/test_cli_generate.py`, `tests/test_cli_handout.py`

- [ ] Add `--stage outline|introduction|appendices`, `--chapter N`, and retain `--fresh`.
- [ ] Update summary output to outline/chapter/appendix/Markdown/LaTeX/PDF counts.
- [ ] Document the new end-to-end workflow and cache recovery commands.

### Task 5: End-to-end verification

**Files:**
- No new production files.

- [ ] Run `pytest tests/ -q`.
- [ ] Run `courselm generate 数学分析 --fresh` with the configured NotebookLM environment.
- [ ] Run `courselm build-handout 数学分析` and `courselm export-handout 数学分析`.
- [ ] Inspect generated Markdown, `main.tex`, PDF page count, and representative rendered pages for formula/layout regressions.
- [ ] Commit and push the completed branch.
