# AGENTS.md

## Test Strategy

This directory holds synthetic unit tests, isolated SSSEP GUI lifecycle tests,
and optional checks against external FPVS source and a local `.bdf` file.

Keep the default test suite lightweight:

- Prefer synthetic NumPy arrays.
- Prefer small constructed MNE objects.
- Avoid large fixtures and avoid committing EEG binary files to the repo.

## Current Test Layout

- `analysis/`
  Per-electrode amplitude FFT, SSSEP summaries, and full-spectrum table/plot
  contracts. Include time-domain same-cue trial averaging, channel order,
  units, DC/Nyquist, equal-participant group means, missing-electrode counts,
  and consolidated participant/group tables.
  Saved-FFT tests also cover strict CSV reloading, participant-first later ROI
  means, nearest-bin scalp values, and plotted-value exports.
- `events/`
  Trigger parsing, intended-event filtering, and epoch extraction behavior.
- `preprocess/`
  Channel/montage/reference behavior, scaled filtering before downsampling,
  bad-channel handling, and reference-compatible warning paths.
- `experiment/`
  Task validation, balanced randomized schedules, editable prompts, swap-timed
  cues/breaks, countdowns, one-byte cue triggers, frame ordering, aborts, and
  task-event logs using fakes rather than a real display or COM port. Breaks
  and countdown redraws must not send markers.
- `test_pipeline.py`
  High-signal orchestration behavior that can be tested with stubs.
- `test_regression_external_bdf.py`
  Optional real-data regression path using an external local fixture.
- `test_batch.py`
  Discovery, preflight, worker results, unique run directories, consolidated
  CSVs, group plots, and preservation of earlier outputs.
- `test_gui_settings.py`, `test_gui_lifecycle.py`, and `test_task_gui.py`
  Saved parent-root settings plus batch and main-thread task lifecycle behavior
  in isolated SSSEP subprocesses. Do not modify the user's actual settings file.
- `test_saved_plot_gui.py`
  Saved-result loading and post-processing worker lifecycle in an isolated GUI
  subprocess.

## Regression Fixture Rule

The repository intentionally does not store a `.bdf` fixture.

Use the `SSSEP_TEST_BDF` environment variable when a real-data regression is
needed. The regression test must skip cleanly when that variable is unset or
points to a missing file.

Do not convert the regression test into a mandatory repo-backed binary fixture
unless the user explicitly asks for that tradeoff.

`FPVS_REFERENCE_ROOT` selects the read-only source checkout for optional direct
reference comparisons. The current method references commit
`185d803f0056daebee04e5f28cc6b554c47336ce`; use matching packages/settings.
Unset optional fixture variables skip their checks; a supplied reference path
must exist and match its source hashes. No GUI, offscreen Qt session,
or source modification is needed in the FPVS reference checkout. SSSEP's own
isolated GUI tests are separate from reference-method verification.

Install `requirements-dev.txt` with the project interpreter before testing;
it includes pinned runtime versions, pytest 9.0.1, and edfio 0.4.16 for
generated BDF fixtures. Run from the repo root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

## What To Test When Changing Core Code

- `analysis/`
  Exact float64 trial-mean FFT amplitudes, output shapes, frequency bins,
  electrode amplitude averaging, equal participant weighting after FFT, and
  invalid-input handling. Test absence of Hann taper/detrending, preservation
  of the reference's factor of two, the exact 2.5-second crop at both epoch
  ends, and rejection of incompatible frequency grids or duplicate
  participant/cue inputs. The default 15-second epoch must retain samples
  640:3200 at 256 Hz, producing 2560 samples and 0.1 Hz FFT spacing.
- `events/`
  Reference MNE event behavior after preprocessing, SSSEP epoch counts,
  onset indexing, and out-of-bounds behavior. Extra FIR edge exclusion is no
  longer part of the method; legacy edge-count fields remain zero.
- `preprocess/`
  Original-rate scaled filtering followed by resampling, montage/reference
  order, bad-channel exclusion after unresolved interpolation, and warnings.
- `pipeline.py`
  Only high-value orchestration behavior. Verify that full epochs determine
  usability and that cue and baseline FFTs receive the same cropped window.
  Keep heavy signal-processing details in lower-level tests where possible.

## Test Writing Guidance

1. Keep tests deterministic.
2. Prefer one clear behavior per test.
3. Use monkeypatching in pipeline tests to isolate orchestration from heavy I/O.
4. If a bug changed math or sample indexing, add a regression-style test for
   that exact failure mode.
5. If a change only affects docs or markdown files, do not add unnecessary test
   churn.
6. The former SSSEP power/Welch pipeline is not a numerical baseline for the
   authorized FPVS amplitude method. Compare the same signal windows and
   settings through per-electrode amplitudes; document SSSEP-specific windows
   and downstream metrics separately in `docs/fpvs-parity.md`.
