# AGENTS.md

## Package Role

`sssep_batch` implements the SSSEP participant task, BDF processor, and saved
FFT plotting workflow in focused modules with dedicated responsibilities.

The root `README.md` links the short student setup and user guides. Use
`architecture.md` for the code map and validation steps, and
`docs/fpvs-parity.md` for the numerical contract.

The package is organized around these boundaries:

- `batch.py`
  Batch discovery, worker setup, and parent-process summary writing.
- `pipeline.py`
  Per-file stage order only.
- `saved_plots_gui.py`
  Saved-result/data selectors and background load/plot workers. All conditions
  renders separate FFT PNGs per ROI/event. Scalp maps support separate event
  figures and an explicit paired-condition figure with a shared amplitude
  scale, retaining successes and reporting failures in the scrollable results
  box.
- `roi_selection_gui.py`
  Modal BioSemi64 diagram and named electrode/ROI selection. Use ROI applies
  the draft; Cancel preserves the prior selection. Presets and schematic
  coordinates come from the personal website, not the preprocessing montage.
- `roi_settings.py`
  Persistent custom ROIs in ignored `.sssep_rois.json`. Explicit saves are atomic
  and separate from the dialog's Use/Cancel actions and experiment preferences.
- `gui_style.py`
  Launcher-only FPVS Studio styling, section cards, forms, and scrolling.
  Keep View-menu workflow navigation and action/status footers; leave task frames alone.
- `task_settings_gui.py`
  Modal File > Settings editor. Save validates and persists a draft before applying
  it; Cancel preserves prior settings. Regions of Interest opens the large ROI
  selector for each Add/Edit entry in a named ROI list; its draft affects plots
  only after outer Save. Remove changes the plotting list, not the saved custom
  library. The home starts both conditions.
- `launcher_settings.py`
  Validated persistent preferences in ignored `.sssep_gui_settings.json`. Atomic
  writes, legacy folder/single-ROI migration to `plot_rois`, and hardware settings
  excluded from storage.
- `loading.py`
  FPVS-compatible BioSemi channel-subset loading from external input.
- `analysis/`
  Batch event protocol, per-electrode amplitude FFT, SSSEP amplitude summaries,
  consolidated participant/group tables, equal-participant group averaging,
  saved-table reloading, later ROI aggregation, plot/source-data output, and
  plotting helpers.
- `experiment/`
  Task models, balanced scheduling, PySide6 presentation, BioSemi serial
  triggers, and task-event logs. It does not control TENS hardware.
- `events/`
  Status-channel event detection and epoch extraction.
- `preprocess/`
  Channel setup, downsampling, filtering, and bad-channel handling.
- `outputs.py`
  Summary CSV and text report writing.

## Non-Negotiable Design Intent

1. `pipeline.py` defines order; helper modules define implementation.
2. The GUI owns task/run selections; `config.py` owns analysis defaults. The
   BioSemi port is fixed at `COM3`, and cue codes are fixed at `11`, `12`, `21`,
   and `22`; neither can be edited in the GUI.
3. Keep helpers close to their domain. Do not reintroduce a monolith through
   cross-cutting helper files.
4. Prefer pure or near-pure functions in submodules where practical.

## Pipeline Facts Future Agents Must Preserve

- Current method: `fpvs_amplitude_epoch_crop_v2`, referenced to FPVS commit
  `185d803f0056daebee04e5f28cc6b554c47336ce`. See
  [FPVS method and parity checks](../docs/fpvs-parity.md).
- Load the reference channel subset, assign `standard_1005` before
  preprocessing, then apply EXG reference/drop and keep scalp EEG plus Status.
- Apply the scaled-duration 0.1–50 Hz FIR at the original sampling rate before
  downsampling to 256 Hz. Kurtosis screening/interpolation precedes the final
  average-reference projection.
- `find_status_events()` runs after preprocessing on the final sampling grid.
  Its MNE options match the reference; do not restore the old mask or
  event-before-downsample path.
- Require the complete configured SSSEP onset duration, 15 seconds by default.
  Skip out-of-recording windows, but add no FIR edge margin or EEG zero
  replacement. Before averaging and FFT, crop 2.5 seconds from each end. The
  default retains samples 640:3200 at 256 Hz: 2560 samples, or 10 seconds.
  This is SSSEP-specific and is not the FPVS visual-oddball 1.2 Hz marker crop.
- Average trials in float64 per electrode, convert to microvolts, then use
  `abs(np.fft.fft(mean_epoch_uv)[:, :N // 2 + 1]) / N * 2` without a taper,
  detrending, or power squaring. Average same-cue epochs in the time domain
  before this participant FFT. Preserve the reference DC/Nyquist scaling.
- Treat one BDF as one participant. Group cue results are arithmetic means of
  the participant amplitude spectra, with equal participant weight regardless
  of usable epoch count. Group averaging is downstream of FPVS parity.
- Match each optional group baseline overlay to that cue's selected-electrode
  participant cohort; omit it if any cue contributor lacks matching baseline
  data.
- Exclude unresolved bad channels before FFT. Retain full good-scalp amplitude
  spectra and nonnegative frequencies in consolidated CSVs. PNGs show one
  selected electrode; skip only affected PNGs when it is unresolved and retain
  contributing-participant counts. Existing ROI means remain only in downstream
  summaries and CSV mean columns.
- Use the `AnalysisProtocol` supplied by the launcher for both conditions'
  four fixed codes and labels, epoch duration, expected counts, and
  optional stimulation frequency. That task protocol keeps code `100` in event
  auditing as an epoch-end/break delimiter and disables baseline FFT calculation
  for its variable following intervals.
- Local SSSEP amplitude SNR and Gap/Break comparisons are downstream summaries,
  not a claim of parity with FPVS's neighboring-bin SNR method.
- `process_one_bdf()` writes durable per-file reports and should keep its final
  success lines in `report_lines` before the report is written.

## Parallel Processing Notes

- Worker parallelism is file-level and process-based.
- The parent process owns the shared batch log, final batch summary, consolidated
  participant/group CSVs, and equal-participant group plots.
- Worker detail should stay in per-file reports and per-file outputs.
- `BATCH_WORKERS = 3` is the recommended ceiling for typical 16 GB systems, but
  it remains configurable in `config.py`.
- Thread-cap environment variables are intentionally forced to `1` before
  worker spawn. Do not weaken that behavior casually.
- `run_batch()` creates a unique child run directory beneath the selected
  output root and returns that child's path. Never merge a new run into old
  outputs; direct per-file processing also rejects an existing result folder.

## Editing Guidance By Area

### `analysis/`

- Changes here are likely to affect mathematical output.
- Add or update tests before changing frequency-domain behavior.
- Preserve the current microvolt amplitude schema. The former power/Welch
  outputs were deliberately retired with the method change.
- `grouping.py` combines already-computed participant spectra; it must not
  recompute FFTs or weight participants by their epoch counts.
- Keep `participant_fft_amplitudes.csv` and `group_fft_amplitudes.csv` at the
  run root. They contain all participant/cue/electrode spectra and group means,
  respectively; they are CSV files, not Excel workbooks.
- Use the participant CSV as the canonical input for later plots. It preserves
  participant identity for within-participant ROI means and equal-participant
  group aggregation, plus the schema version, FPVS reference, montage, actual
  sampling rate, extracted epoch duration, crop durations, FFT analysis-window
  duration, and plot-frequency range. ROI calculations retain each participant's
  contributing electrodes and curve in memory. Scalp maps keep variable
  electrode Ns visible, omit labels without montage coordinates, and never
  replace missing channels with zero. Save later PNGs directly in `saved_fft_plots`:
  no CSV/Excel copies or per-plot folders. Reserve unique filenames with numbered
  suffixes and remove only the failed attempt's PNG. Preserve older outputs.
  Canonical CSVs keep all values, provenance, and participant counts.
- Save one participant and one group selected-electrode PNG per usable cue.
  FFT filenames use full condition label + ROI/electrode + `FFT_Amplitude`,
  with underscores for spaces. Shared plot helpers reserve numbered PNG paths;
  failed renders remove only their own reserved file. Scalp names stay unchanged.

### `events/`

- Be careful with sample indexing and trigger-code filtering.
- Event timing mistakes silently change which data enters each epoch.

### `experiment/`

- Open the fixed `COM3` connection before participant-facing screens in normal
  runs. Confirmed test mode uses the simulated backend and must be logged.
- Keep cue emission as the first external action in the matching
  `QOpenGLWindow.frameSwapped` callback for each newly drawn cue.
- Run both hands first, then right hand/right ankle. Freshly randomize balanced
  cues per condition with at most two identical cues in a row and insert breaks
  within each block. The block boundary
  waits for Space on the visible handover screen, then Y on a separate visible
  confirmation screen; ignore held-key repeats. Send `100` on the first handover
  swap, none on confirmation. Initial Space starts a five-second lead-in; the
  final thank-you screen closes after five seconds. End every completed attention
  epoch by sending `100` on the first following break, handover, or thank-you
  swap. Log each epoch-end send on that attention epoch's row.
  Align a Qt `PreciseTimer` deadline to each accepted timed-screen swap; close
  cues on the following break, handover, or thank-you swap. Confirmation and
  countdown redraws send no markers. The persistent countdown toggle controls
  visibility, not timing.
- BioSemi events are one raw byte, codes `1..255`, over fixed `COM3` at 115200
  baud by default.
- Never continue silently after a serial or trigger failure. Preserve partial
  task logs after an in-task abort or write failure.
- Keep the participant presenter on the Qt main thread.

### `preprocess/`

- Downsampling, filtering, and interpolation can affect both performance and
  analysis correctness.
- Preserve the FPVS reference's logged warning-and-continue behavior where it
  is implemented. Keep those warnings visible and do not add silent fallbacks
  or new zero replacement/edge exclusions that would change parity.

### `outputs.py`

- Treat CSV/report field names as externally consumed outputs.
- Record `processing_method`, `fpvs_reference_commit`, and actual analysis/FFT
  channel lists. New amplitude fields must not be mislabeled as old power or
  Welch metrics.

## Validation Expectations

When touching this package, usually run:

1. Compile touched modules with `.\.venv\Scripts\python.exe -m py_compile`.
2. Run `.\.venv\Scripts\python.exe -m pytest -q` from the repository root.

If you change behavior in `analysis`, `events`, or `preprocess`, prefer to
extend tests in `tests/` in the same change. Optional source/recording checks
use `FPVS_REFERENCE_ROOT` and `SSSEP_TEST_BDF`. Keep the FPVS source checkout
read-only; never launch its GUI as part of parity verification.
