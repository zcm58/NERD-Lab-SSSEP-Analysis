# AGENTS.md

## Repo Purpose

This repository contains a BioSemi `.bdf` SSSEP batch processor intended to be
run locally from PyCharm. The current user-facing workflow is:

1. Edit `sssep_batch/config.py`
2. Right-click `sssep_bdf_batch_processor.py`
3. Click `Run 'sssep_bdf_batch_processor'`

Do not redesign this around command-line flags unless the user explicitly asks
for that. `config.py` is the intended configuration surface.

## Repo Layout

- `sssep_bdf_batch_processor.py`
  Thin entrypoint wrapper. Keep it simple.
- `sssep_batch/`
  Actual implementation package.
- `tests/`
  Unit tests plus one optional external-fixture regression test.
- `requirements.txt`
  Project dependency list for the local `.venv`.

## Critical Project Rules

1. Preserve mathematical output unless the user explicitly asks for an analysis
   change.
2. Keep `pipeline.py` as an orchestration file. Put low-level logic in the most
   specific submodule instead of growing the pipeline.
3. Keep user-edit settings in `sssep_batch/config.py`.
4. Do not add generic utility modules when a more specific home exists.
5. Treat `.bdf` data as external local input, not as repository content.

## Known Pipeline Constraints

These are not optional cleanups. They are part of the current intended design:

- Detect `Status` events before downsampling, then carry those events through
  resampling.
- Preserve the FIR edge-exclusion rule for epochs near the start and end of the
  filtered recording.
- Keep file-level parallelism in `batch.py`. Parallelism is across files, not
  inside a single file.
- Keep native thread limits at `1` per worker to avoid oversubscription during
  parallel batch runs.
- Enforce `MAX_INDIVIDUAL_PLOTS` only for plot creation. Do not let it affect
  metrics or CSV summaries.

## Before Making Structural Changes

Read `sssep_batch/README.md` first. It contains the intended package structure,
module responsibilities, and safety checklist.

If you change processing code, validate at minimum:

1. `python -m py_compile` still passes.
2. `python -m pytest -q` still passes.
3. The PyCharm entrypoint still runs through `sssep_bdf_batch_processor.py`.
4. Output field names remain stable unless the user asked to revise them.
5. If math was not meant to change, compare results on a known local `.bdf`
   file when available.

## Scope Discipline

- Prefer surgical changes over wide refactors.
- If you notice unrelated cleanup opportunities, mention them instead of
  folding them into the current task.
- Keep documentation and code consistent when you change entrypoints,
  configuration behavior, testing workflow, or package layout.
