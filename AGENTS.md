# AGENTS.md

## Repo Purpose

This repository contains one local SSSEP task-and-analysis application intended
to be run from PyCharm. The current user-facing workflow is:

1. Right-click `main.py`
2. Click `Run 'main'`
3. Use View > SSSEP Task, Process Data, or Generate FFT Plots

Do not redesign this around command-line flags unless the user explicitly asks
for that. Task settings and the plotted electrode belong in **File > Settings**;
`config.py` remains the source for analysis defaults and advanced settings.

Use **trigger code** in app text and plot labels. Preserve internal `cue` event
values, task-log fields, and filenames so existing results remain compatible.

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

Every run completes both hands first, then right hand/right ankle. Freshly
shuffle balanced cues within each condition (default 10 epochs each). Timed
breaks (default 10 seconds) separate cues within a condition. Between conditions,
wait for Space on the electrode handover screen, then a fresh Y on its visible
confirmation screen. Neither screen sends markers or has a countdown.
Cue/break text is editable in File > Settings. Save preferences across launches
in ignored `.sssep_gui_settings.json`; never save hardware codes or random seeds.
The home shows only its title, Start SSSEP Task button, and settings hint. Use
the View menu instead of workflow tabs. Keep fixed codes `11`/`12` for both hands and `21`/`22`
for hand and ankle, with all four code controls disabled in the GUI. Record any
future timing, code, frequency, or counterbalancing change in
`docs/task-protocol.md` before implementation.

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
  Use 64-bit Python 3.13.
- `install.ps1`
  Creates the Python 3.13 `.venv`, installs `requirements.txt`, and verifies
  the PySide6 presentation and pyserial imports. Keep it as the simple Windows
  setup path.
- `docs/fpvs-parity.md`
  FPVS reference, method boundary, and comparison evidence.

## Critical Project Rules

1. Preserve mathematical output unless the user explicitly asks for an analysis
   change.
2. Keep `pipeline.py` as an orchestration file. Put low-level logic in the most
   specific submodule instead of growing the pipeline.
3. Keep task/run selections in the launcher and analysis defaults in
   `sssep_batch/config.py`. Keep the BioSemi port fixed at `COM3` and absent
   from the GUI. The explicit, confirmed test-mode checkbox may bypass COM3;
   normal runs may not.
4. Do not add generic utility modules when a more specific home exists.
5. Treat `.bdf` data as external local input, not as repository content.

## Known Pipeline Constraints

The authorized `fpvs_amplitude_epoch_crop_v2` method replaces the former SSSEP
power/Welch pipeline. Preserve this current design unless a further change is
authorized:

- Use the reference-compatible loader and `standard_1005` montage before
  preprocessing, then EXG reference/drop and retention of 64 scalp channels
  plus `Status`.
- Filter at the original sampling rate with the scaled-duration 0.1–50 Hz FIR,
  then downsample to 256 Hz, screen/interpolate bad channels, and apply the
  final average reference. Preserve the reference's explicitly logged
  warning-and-continue paths; do not add silent fallbacks.
- Detect `Status` events after preprocessing with the reference MNE options.
  Require complete SSSEP onset windows (15 seconds by default), with no extra
  FIR edge exclusion or EEG zero replacement.
- Before same-cue averaging and FFT calculation, remove 2.5 seconds from the
  start and end of every epoch. At the default, analyze samples 640:3200 at
  256 Hz: the middle 2560 samples, or 10 seconds. This is an SSSEP-specific
  analysis window, not the FPVS visual-oddball 1.2 Hz marker crop.
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
- Carry both conditions' fixed cue codes, the configured duration, and expected
  repetitions into the batch through `AnalysisProtocol`. Never analyze task
  recordings with unrelated event settings.
- Keep full per-electrode nonnegative-frequency amplitudes and method metadata
  in the root-run `participant_fft_amplitudes.csv` and
  `group_fft_amplitudes.csv`. These are consolidated CSVs, not Excel workbooks.
  The old power/Welch schema is intentionally retired.
- Treat `participant_fft_amplitudes.csv` as the canonical saved plotting source.
  Later ROIs average electrodes within participant before equal-participant
  group averaging. Scalp maps use finite available electrodes at the nearest
  saved FFT bin. Keep per-electrode participant counts in the canonical group
  CSV. Save later plots as PNGs directly in `saved_fft_plots`, without per-plot
  CSV/Excel files or subfolders. Add numbered suffixes rather than overwriting;
  on failure remove only the newly reserved PNG. Preserve earlier exports.
  Report unmapped electrodes in the GUI; keep their values in the canonical CSVs.
- Keep file-level parallelism in `batch.py`. Parallelism is across files, not
  inside a single file.
- Keep native thread limits at `1` per worker to avoid oversubscription during
  parallel batch runs.
- Create one participant and one group selected-electrode plot per usable cue.
- Default the TENS frequency to 26 Hz without overwriting saved preferences.
  FFT plots mark the selected frequency with a dashed vertical line labeled
  `TENS Unit Stimulation Frequency`; saved-plot marker overrides never change
  FFT values or source metadata.
- Opening Generate FFT Plots auto-loads the selected source in its worker.
  A parent results folder selects its most recently updated immediate run;
  invalidate stale selections on path changes and report load failures.
- Keep each batch in a newly created, unique run subfolder. Preserve previous
  runs and the GUI's parent-root saved setting.
- Retain GUI workers until completion and block window close while a batch,
  participant task, saved-data load, or saved plot is active. Keep BDF and
  saved-plot work off the UI thread. Run the PySide6 participant presenter on
  the Qt main thread.

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
