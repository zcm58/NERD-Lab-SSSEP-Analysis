---
name: sssep-pipeline-safety
description: Use when changing or reviewing SSSEP processing behavior, including sssep_batch/pipeline.py, analysis, events, preprocess, batch parallelism, config constants that affect math, event timing, filtering, epochs, spectra, metrics, or real-data regression risk.
---

# SSSEP Pipeline Safety

## Overview

Use this workflow to keep processing changes behavior-preserving unless the user
explicitly asks for an analysis change.

## Workflow

1. Read `AGENTS.md`, `architecture.md`, `sssep_batch/AGENTS.md`, and the
   relevant module tests before editing.
2. State whether the task is intended to change mathematical output. If unclear,
   stop and ask.
3. Identify the smallest module that owns the behavior. Keep `pipeline.py` as
   orchestration only.
4. Preserve these invariants:
   - `Status` events are detected before downsampling.
   - Resampling carries event sample positions to the post-resample grid.
   - FIR edge-exclusion behavior is preserved.
   - File-level parallelism stays in `batch.py`.
   - Native thread caps stay at `1` per worker.
   - `MAX_INDIVIDUAL_PLOTS` affects plot creation only, not metrics or CSVs.
5. Add or update focused tests for changed math, event timing, filtering, epoch,
   spectrum, metric, or batch behavior.
6. Run `python -m py_compile` and `python -m pytest -q` when code changes.
7. If math was not meant to change and a local `.bdf` fixture is available, run
   the external regression path or compare representative outputs.

## Return

Report files touched, whether math/output contracts changed, verification gates
run, and any skipped regression reason.
