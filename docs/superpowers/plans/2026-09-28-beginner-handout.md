# Beginner-first handout implementation plan

## Goal

Make the generated handout teach a student who knows high-school material but is starting the course during exam revision. Each chapter follows the course; each question type teaches from one simple worked example before extracting a reusable method. The PDF and Markdown must make that path easy to follow.

## Task 1: Generation contract and cache

- Replace the chapter prompt's separate knowledge/method/example blocks with a chapter route, repeated question-type units, and a short chapter check. Require a concrete worked solution, reasons for each key step, a nearby practice question with hint and solution, and source labels without invented marks or frequency.
- Revise the introduction and appendices for the agreed study path and quick lookup.
- Bump the generation cache version so existing content cannot silently masquerade as the redesigned handout. Preserve known uploads across the version change.
- Verify prompt rendering and cached pipeline behavior with targeted tests.

## Task 2: Reader-facing manuscript

- Remove internal file paths and draft warnings from the student manuscript.
- Keep one chapter heading per chapter and a stable question-type order. Produce a question-type index that links to worked examples in the PDF and Markdown.
- Verify generated manuscript structure with focused tests.

## Task 3: PDF layout

- Use two-level, clickable contents, unnumbered display headings, readable body spacing and restrained color. Keep a worked-example heading with its opening text, and avoid breaking a step across pages where practicable.
- Render numbered solution steps as numbered lists. Convert wide tables into readable stacked entries.
- Verify LaTeX output with tests, compile a representative sample, and inspect rendered pages.

## Task 4: Documentation and release checks

- Update usage instructions for the new cache version and handout shape.
- Run the relevant tests and whole suite, inspect the diff, and remove review-only temporary files.
