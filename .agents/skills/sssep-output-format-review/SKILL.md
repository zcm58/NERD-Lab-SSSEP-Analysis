---
name: sssep-output-format-review
description: Use when changing or reviewing SSSEP output contracts, including outputs.py, batch_processing_summary.csv, per-file event summary CSVs, processing reports, error reports, diagnostic plots, plot limits, metric fields, or baseline comparison fields.
---

# SSSEP Output Format Review

## Workflow

1. Read `AGENTS.md`, `architecture.md`, `README.md`, `sssep_batch/AGENTS.md`,
   and output-related tests before editing.
2. List the affected artifacts:
   - `batch_processing_summary.csv`
   - `*_sssep_event_summary.csv`
   - `*_processing_report.txt`
   - `ERROR.txt`
   - `plots/`
3. Treat existing CSV/report field names as externally consumed. Avoid renames
   and removals unless the user explicitly asks for a schema change.
4. Keep `MAX_INDIVIDUAL_PLOTS` scoped to plot creation only. It must not limit
   metrics, baseline comparisons, event summaries, or batch summaries.
5. Preserve status/error reporting semantics so failed files remain visible in
   the batch summary and per-file error output.
6. If adding fields, prefer backward-compatible additions and update tests or
   documentation that enumerate expected fields.
7. If changing math-backed values, use `$sssep-pipeline-safety` too.
8. Run focused output tests and `python -m pytest -q` when code changes.

## Return

Report output artifacts affected, schema changes or non-changes, files touched,
tests run, and any manual output inspection performed.
