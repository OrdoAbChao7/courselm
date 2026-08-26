# Three-Day Crash Handout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn CourseLM's default output into a configurable three-day exam-crash handout for students with weak foundations.

**Architecture:** Expand the existing prompt book so NotebookLM generates one focused document per teaching module while retaining the dynamic question-type stage. Add a validated handout-template loader that orders those files and supports course-level overrides, then extend the LaTeX renderer for callouts, page breaks, headers, and long tables.

**Tech Stack:** Python 3.11, Pydantic 2, PyYAML, pytest, Markdown subset renderer, XeLaTeX with ctexart/tcolorbox/longtable.

**Spec:** `docs/superpowers/specs/2026-08-27-three-day-crash-handout-design.md`

## Global Constraints

- Default audience: students with weak foundations and three days before the final exam.
- Default daily study time: 4 to 6 hours; total: 12 to 18 hours.
- NotebookLM prompts must not invent score weights, frequency, or source attribution.
- Preserve prompt IDs `knowledge_structure`, `formula_summary`, and `question_type_summary`.
- Course overrides live at `courses/<course>/handout.yaml` and may replace sections or merge LaTeX style values.
- All source and output paths stay inside configured course/output roots.
- Unit tests use fake services; real command exit codes and artifacts are required for final verification.

---

### Task 1: Expand and validate the teaching prompt book

**Files:**
- Modify: `config/prompts.yaml`
- Modify: `modules/prompts.py`
- Modify: `tests/test_prompts.py`
- Modify: `tests/test_prompt_runner.py`

**Interfaces:**
- `REQUIRED_FIXED_IDS` includes all twelve fixed teaching modules.
- `render_fixed(prompt: FixedPrompt, max_types: int) -> str` continues to inject `{max_types}` only into `question_type_summary`.
- Existing `PromptBook` and `run_pipeline` signatures remain unchanged.

- [ ] Write failing tests asserting the twelve required IDs, exact output files, three-day-plan constraints, callout rules, and dynamic question output under `08-高频题型精讲`.
- [ ] Run `.venv\Scripts\python -m pytest tests/test_prompts.py tests/test_prompt_runner.py -q` and confirm failures reflect missing prompts/contracts.
- [ ] Replace `config/prompts.yaml` with the twelve fixed module prompts and the revised dynamic detail prompt specified by the design.
- [ ] Update validation constants and shared output rules without changing pipeline orchestration.
- [ ] Re-run the focused tests and commit `feat: generate three-day crash course modules`.

### Task 2: Add validated default and course-specific handout templates

**Files:**
- Create: `config/handout_templates/default.yaml`
- Create: `modules/handout_template.py`
- Create: `tests/test_handout_template.py`
- Modify: `modules/path_manager.py` only if a helper is needed for the template path.

**Interfaces:**
- `HandoutSection(id: str, title: str, source: str | None, glob: str | None, required: bool, page_break: bool)`.
- `HandoutTemplate(title_suffix: str, subtitle: str, sections: list[HandoutSection], latex: dict[str, str])`.
- `load_handout_template(course: str, courses_dir: Path, default_path: Path | None = None) -> HandoutTemplate`.

- [ ] Write failing tests for default loading, course title/style override, full section replacement, duplicate IDs, missing source/glob, and traversal paths.
- [ ] Run `.venv\Scripts\python -m pytest tests/test_handout_template.py -q` and confirm the module is missing.
- [ ] Implement Pydantic validation and top-level override merging; lists replace defaults and the `latex` mapping merges keys.
- [ ] Add the default YAML with the exact fourteen-module order from the spec.
- [ ] Re-run the focused tests and commit `feat: add configurable handout templates`.

### Task 3: Rebuild manuscript assembly around the template

**Files:**
- Modify: `modules/handout_builder.py`
- Modify: `tests/test_handout_builder.py`
- Modify: `main.py`
- Modify: `tests/test_cli_handout.py`

**Interfaces:**
- `build_handout(course: str, output_dir: Path, *, courses_dir: Path | None = None, template_path: Path | None = None, max_types: int = 12) -> HandoutBuildResult`.
- `HandoutBuildResult` adds `template: HandoutTemplate` and retains manuscript/tex/missing fields.
- `_build_handout_files` passes `cfg.paths.courses_dir` and template title/style into LaTeX generation.

- [ ] Replace old three-file fixtures with all default module files and write failing tests for exact order, page-break markers, dynamic question sorting, missing required modules, and custom section replacement.
- [ ] Run `.venv\Scripts\python -m pytest tests/test_handout_builder.py tests/test_cli_handout.py -q` and confirm the hard-coded builder fails the new expectations.
- [ ] Implement template-driven discovery, source markers, module purpose text, and stable glob expansion excluding duplicate index files.
- [ ] Update CLI integration while keeping `build-handout` and `export-handout` command names unchanged.
- [ ] Re-run the focused tests and commit `feat: assemble template-driven crash handouts`.

### Task 4: Render teaching semantics in LaTeX

**Files:**
- Modify: `modules/latex_renderer.py`
- Modify: `tests/test_latex_renderer.py`

**Interfaces:**
- `write_latex_document(manuscript: str, destination: Path, title: str, *, subtitle: str = "", style: dict[str, str] | None = None) -> Path`.
- Markdown `<!-- PAGE_BREAK -->` becomes `\clearpage`.
- Obsidian callouts `[!IMPORTANT]`, `[!TIP]`, `[!WARNING]`, `[!CHECK]` become colored breakable `tcolorbox` environments.
- Markdown tables render as `longtable` so they can cross pages.

- [ ] Write failing tests for title/subtitle, semantic colors, page breaks, four callout types, headers/footers, and longtable output.
- [ ] Run `.venv\Scripts\python -m pytest tests/test_latex_renderer.py -q` and confirm failures expose unsupported semantics.
- [ ] Extend the line renderer and document preamble with `xcolor`, `tcolorbox`, `fancyhdr`, `longtable`, and configurable colors.
- [ ] Preserve existing math, code-block, front-matter, list, and Obsidian-link behavior.
- [ ] Re-run the focused tests and commit `feat: style three-day teaching handouts`.

### Task 5: Update product documentation and verify the full loop

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/design.md`
- Modify: `docs/superpowers/plans/2026-08-27-three-day-crash-handout.md` to mark executed tasks.

**Interfaces:**
- Document the default three-day directory, prompt cost (`12 + N` chats on a fresh run), course override path, and exact build/export commands.

- [ ] Update documentation with the directory tree, three-day study path, custom YAML example, `--fresh` migration note, and MiKTeX requirement.
- [ ] Run `git diff --check`.
- [ ] Run `.venv\Scripts\python -m pytest tests/ -q` and record the exact pass count.
- [ ] Run `.venv\Scripts\courselm build-handout 电动力学` and inspect the generated manuscript and TeX ordering.
- [ ] If the current NotebookLM login/profile is available, run `.venv\Scripts\courselm generate 电动力学 --fresh`; otherwise report the exact authentication/profile blocker without claiming generation success.
- [ ] Run `.venv\Scripts\courselm export-handout 电动力学`, confirm exit code 0, render representative PDF pages, and inspect layout.
- [ ] Commit `docs: document three-day crash handout workflow`.
