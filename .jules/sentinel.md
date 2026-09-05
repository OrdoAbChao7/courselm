## 2026-09-05 - [Path Traversal Fix in course_name handling]
**Vulnerability:** Path traversal vulnerability due to unsanitized `course_name` input across `file_manager.py`, `obsidian_sync.py`, and `prompt_runner.py`.
**Learning:** External inputs like course names used for file path generation can easily lead to path traversal if not validated properly at the API or internal module boundaries.
**Prevention:** Always validate directory or file name inputs to ensure they do not contain path separators (`/`, `\`) or relative directory markers (`.`, `..`) before using them in file system operations.
