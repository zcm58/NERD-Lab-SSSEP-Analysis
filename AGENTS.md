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

- `architecture.md`
  Compact module map and dependency guidance. Read this before broad changes.
- `sssep_bdf_batch_processor.py`
  Thin entrypoint wrapper. Keep it simple.
- `sssep_batch/`
  Actual implementation package.
- `tests/`
  Synthetic unit tests, isolated GUI lifecycle checks, and optional external
  reference/recording regression checks.
- `.agents/skills/`
  Repo-local repeatable Codex workflows. Use the narrowest matching skill for
  pipeline, GUI, path, or output-format work.
- `requirements.txt`
  Pinned runtime dependencies for the local `.venv`; `requirements-dev.txt`
  adds pytest 9.0.1 and edfio 0.4.16 for tests and generated BDF fixtures.
  Use Python 3.13; verification used 3.13.5.
- `docs/fpvs-parity.md`
  FPVS reference, method boundary, and comparison evidence.

## Critical Project Rules

1. Preserve mathematical output unless the user explicitly asks for an analysis
   change.
2. Keep `pipeline.py` as an orchestration file. Put low-level logic in the most
   specific submodule instead of growing the pipeline.
3. Keep user-edit settings in `sssep_batch/config.py`.
4. Do not add generic utility modules when a more specific home exists.
5. Treat `.bdf` data as external local input, not as repository content.

## Known Pipeline Constraints

The authorized `fpvs_amplitude_v1` method replaces the former SSSEP power/Welch
pipeline. Preserve this current design unless a further change is authorized:

- Use the reference-compatible loader and `standard_1005` montage before
  preprocessing, then EXG reference/drop and retention of 64 scalp channels
  plus `Status`.
- Filter at the original sampling rate with the scaled-duration 0.1–50 Hz FIR,
  then downsample to 256 Hz, screen/interpolate bad channels, and apply the
  final average reference. Preserve the reference's explicitly logged
  warning-and-continue paths; do not add silent fallbacks.
- Detect `Status` events after preprocessing with the reference MNE options.
  Keep SSSEP onset windows (7.5 seconds by default), with no extra FIR edge
  exclusion or EEG zero replacement. Do not import the FPVS 1.2 Hz marker crop.
- Average trials in float64 per electrode and calculate the reference
  microvolt amplitude FFT, `abs(FFT(mean_epoch_uv)) / N * 2`, retaining its
  DC/Nyquist scaling. No Hann taper, detrending, power, or Welch PSD.
- Exclude unresolved bad channels before the FFT. Average the resulting
  electrode amplitudes for ROI plots/summaries and report actual channel lists.
- Keep full per-electrode nonnegative-frequency amplitude CSVs and method
  metadata. The old power/Welch schema is intentionally retired.
- Keep file-level parallelism in `batch.py`. Parallelism is across files, not
  inside a single file.
- Keep native thread limits at `1` per worker to avoid oversubscription during
  parallel batch runs.
- Enforce `MAX_INDIVIDUAL_PLOTS` only for plot creation. Do not let it affect
  metrics or CSV summaries; the default 5 means five amplitude PNGs per file.
- Keep each batch in a newly created, unique run subfolder. Preserve previous
  runs and the GUI's parent-root saved setting.
- Retain GUI workers until `QThread.finished` and block window close while a
  batch is active. Keep setup checks and processing off the UI thread.

## Before Making Structural Changes

Read `README.md` and `architecture.md` first. They contain the intended
workflow, package structure, module responsibilities, and safety checklist.

Use repo-local skills when they match the task:

- `$sssep-pipeline-safety` for processing-order, math, event, preprocessing, or
  parallelism changes.
- `$pyside6-gui-cleanup` for launcher, widget, dialog, worker-thread, or
  GUI-status changes.
- `$project-path-audit` for input/output folders, saved GUI settings, `.bdf`
  discovery, generated files, or Windows path handling.
- `$sssep-output-format-review` for CSV, report, plot, summary, or output-field
  changes.

If you change processing code, validate at minimum:

1. Compilation with `.\.venv\Scripts\python.exe -m py_compile` still passes.
2. `.\.venv\Scripts\python.exe -m pytest -q` still passes.
3. The PyCharm entrypoint still runs through `sssep_bdf_batch_processor.py`.
4. Output field names remain stable unless the user asked to revise them.
5. If math was not meant to change, compare results on a known local `.bdf`
   file when available.
6. For FPVS parity, use the pinned source selected by `FPVS_REFERENCE_ROOT`
   and optional recording selected by `SSSEP_TEST_BDF`; report any skipped
   checks. Compare matching methods and settings, not old SSSEP power outputs.

## Scope Discipline

- Prefer surgical changes over wide refactors.
- If you notice unrelated cleanup opportunities, mention them instead of
  folding them into the current task.
- Keep documentation and code consistent when you change entrypoints,
  configuration behavior, testing workflow, or package layout.
