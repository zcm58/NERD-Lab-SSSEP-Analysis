---
name: project-path-audit
description: Use when reviewing SSSEP file I/O, input/output folders, QFileDialog behavior, saved GUI settings, generated files, .bdf discovery, Windows paths, hard-coded path cleanup, or project-root discipline.
---

# Project Path Audit

## Workflow

1. Read `AGENTS.md`, `architecture.md`, `README.md`, and any tests covering the
   path behavior being changed.
2. Identify every path source: `config.py`, GUI text fields, saved GUI settings,
   `QFileDialog`, `SSSEP_TEST_BDF`, generated output folders, and report paths.
3. Preserve the rule that `.bdf` data is external local input and not repository
   content.
4. Preserve output formats and names unless the user asked for a schema or
   naming change.
5. Handle folder-dialog Cancel without overwriting existing text or settings.
6. Validate missing, invalid, permission-denied, empty, and repeated-operation
   paths where the current workflow can reach them.
7. Avoid hard-coded absolute paths outside user-edit defaults in `config.py` or
   local test fixtures.
8. Do not make command-line flags the normal configuration surface. Keep
   user-edit settings in `sssep_batch/config.py`.
9. For tests, use `tmp_path` and synthetic files. Do not commit `.bdf` files.
10. Run focused path tests and `python -m pytest -q` when code changes.

## Return

Report path sources reviewed, changed files, behavior preserved, tests run, and
any remaining manual path cases.
