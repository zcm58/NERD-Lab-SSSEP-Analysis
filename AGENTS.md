# AGENTS.md

## Repo Purpose

This repository contains one local SSSEP task-and-analysis application intended
to be run from PyCharm. The current user-facing workflow is:

1. Right-click `main.py`
2. Click `Run 'main'`
3. Choose the participant task, recording analysis, or saved FFT plotting tab

Do not redesign this around command-line flags unless the user explicitly asks
for that. Task settings and the plotted electrode belong in the GUI;
`config.py` remains the source for analysis defaults and advanced settings.

## Product Scope

Maintain one simple SSSEP/TENS application with a fullscreen cue/BioSemi trigger
runner, offline BDF processing, and plotting from saved FFT results.

- Condition 1: stimulate both hands; cue attention to the left or right hand;
  test stimulation-frequency amplitude over the contralateral hemisphere.
- Condition 2: stimulate the right hand and right ankle; cue attention to either
  site; test whether the stimulation-frequency scalp peak changes location.

TENS units are controlled externally. This package owns task presentation,
cue-onset BioSemi triggers, BDF processing, consolidated participant/group
per-electrode FFT CSVs, participant/group electrode or ROI plots, and raw FFT
amplitude scalp maps. Hemisphere comparisons and statistical analysis stay
outside this package; existing ROI mean compatibility fields remain in exported
CSVs/summaries.

The participant runtime alternates its two balanced cues from a randomized
starting cue, uses fixed codes `11`/`12` for both hands and `21`/`22` for hand
and ankle, and presents back-to-back configurable-duration epochs. Keep all four
code controls disabled in the GUI. Record any future timing, code, frequency,
or counterbalancing change in `docs/task-protocol.md` before implementation.

## Repo Layout

- `README.md`, `docs/installation.md`, and `docs/user-guide.md`
  Student starting page, setup, and everyday use. Keep these brief and link to
  technical details rather than repeating them.
- `architecture.md`
  Task-based code map, design rules, and testing steps. Read before code changes.
- `main.py`
  Primary GUI entrypoint. Keep it simple.
- `sssep_bdf_batch_processor.py`
  Compatibility wrapper for the former entrypoint.
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
  Use Python 3.11 because the pinned PsychoPy does not support Python 3.13.
- `docs/fpvs-parity.md`
  FPVS reference, method boundary, and comparison evidence.

## Critical Project Rules

1. Preserve mathematical output unless the user explicitly asks for an analysis
   change.
2. Keep `pipeline.py` as an orchestration file. Put low-level logic in the most
   specific submodule instead of growing the pipeline.
3. Keep task/run selections in the launcher and analysis defaults in
   `sssep_batch/config.py`. Keep the BioSemi port fixed at `COM3` and absent
   from the GUI.
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
  DC/Nyquist scaling. Average all epochs for the same cue in the time domain
  before this FFT. No Hann taper, detrending, power, or Welch PSD.
- Treat each BDF as one participant. After the participant FFTs, calculate each
  group cue spectrum by giving every participant amplitude spectrum equal
  weight, regardless of usable epoch count.
- A group plot's optional baseline must use the same selected-electrode
  participant cohort as its cue. Omit the baseline when matching data are
  unavailable.
- Exclude unresolved bad channels before the FFT. PNGs show one launcher-selected
  electrode; if it is unresolved, skip only the affected participant/group
  plot and report the contributing participant count. Existing ROI summary/CSV
  mean fields remain compatibility outputs and report their actual channels.
- Carry the launcher's condition, fixed cue codes, duration, and expected
  repetitions into the batch through `AnalysisProtocol`. Never analyze task
  recordings with unrelated event settings.
- Keep full per-electrode nonnegative-frequency amplitudes and method metadata
  in the root-run `participant_fft_amplitudes.csv` and
  `group_fft_amplitudes.csv`. These are consolidated CSVs, not Excel workbooks.
  The old power/Welch schema is intentionally retired.
- Treat `participant_fft_amplitudes.csv` as the canonical saved plotting source.
  Later ROIs average electrodes within participant before equal-participant
  group averaging. Scalp maps use finite available electrodes at the nearest
  saved FFT bin and report the actual bin and per-electrode participant counts.
- Keep file-level parallelism in `batch.py`. Parallelism is across files, not
  inside a single file.
- Keep native thread limits at `1` per worker to avoid oversubscription during
  parallel batch runs.
- Create one participant and one group selected-electrode plot per usable cue.
- Keep each batch in a newly created, unique run subfolder. Preserve previous
  runs and the GUI's parent-root saved setting.
- Retain GUI workers until completion and block window close while a batch,
  participant task, saved-data load, or saved plot is active. Keep long work off
  the UI thread and reuse one persistent presentation thread for PsychoPy on
  Windows.

## Before Making Structural Changes

Read `README.md` and `architecture.md` first. They contain the intended
workflow, package structure, module responsibilities, and safety checklist.
Keep everyday options first in `config.py`; separate experiment and advanced
processing settings. Rewording or regrouping settings must not change values.

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
3. The PyCharm entrypoint still runs through `main.py`.
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
