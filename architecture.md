# Architecture

This repository is a local BioSemi `.bdf` SSSEP batch processor with a small
PySide6 launcher. It is optimized for the PyCharm workflow documented in
`README.md`: users edit `sssep_batch/config.py`, run
`sssep_bdf_batch_processor.py`, choose folders in the launcher, and review CSV,
text, and plot outputs.

## Entry Points

- `sssep_bdf_batch_processor.py`
  Imports `sssep_batch.gui.launch_gui()` and exits with its return code. Keep it
  as a thin wrapper.
- `sssep_batch/gui.py`
  Owns the PySide6 folder-selection launcher, saved folder defaults, worker
  thread, progress updates, and "View Output" action.

## Processing Flow

`sssep_batch/pipeline.py` is the per-file orchestration layer. It should describe
stage order, not hold low-level processing details.

Current high-level order:

1. Load one `.bdf` file.
2. Detect BioSemi `Status` events before downsampling.
3. Validate and prepare channels.
4. Downsample while carrying events to the resampled sample grid.
5. Filter, notch filter, and preserve the FIR edge-exclusion rule.
6. Detect/interpolate bad channels.
7. Extract epochs from event timing.
8. Compute FFT, Welch, SSSEP, and baseline-comparison metrics.
9. Write per-file outputs and reports.

## Module Boundaries

- `sssep_batch/batch.py`
  Finds input `.bdf` files, validates batch requests, manages file-level
  parallelism, limits native threads per worker, and writes the batch summary.
- `sssep_batch/config.py`
  User-edit configuration surface for experiment settings, trigger maps,
  constants, and optional folder defaults.
- `sssep_batch/events/`
  Parses trigger labels, filters intended `Status` events, and extracts epochs.
- `sssep_batch/preprocess/`
  Handles channel validation, reference setup, downsampling, finite-value
  cleanup, filtering, notch filtering, FIR edge margins, and bad-channel
  interpolation.
- `sssep_batch/analysis/`
  Computes spectra, metrics, baseline comparisons, plot data, and diagnostic
  plots.
- `sssep_batch/outputs.py`
  Writes per-file CSV summaries, processing reports, and error reports.
- `sssep_batch/logging_utils.py`
  Creates output folders and logging helpers.
- `sssep_batch/models.py`
  Holds small shared data containers.

## Dependency Direction

Prefer this direction:

`gui.py` -> `batch.py` -> `pipeline.py` -> domain modules -> `models.py`

Keep cross-cutting helpers out of generic `utils.py` files. Put new behavior in
the most specific existing module that owns the concept.

## Stability Contracts

- Preserve mathematical output unless the user asks for an analysis change.
- Preserve output field names unless the user asks for a schema change.
- Preserve the PyCharm launcher entrypoint.
- Preserve file-level parallelism in `batch.py`.
- Treat `.bdf` files as external local input, not repository content.
- Keep `MAX_INDIVIDUAL_PLOTS` limited to plot creation only.

## Verification Map

- Processing code: `python -m py_compile` and `python -m pytest -q`.
- Math-sensitive changes: add/update focused unit tests and compare against a
  known local `.bdf` file when available.
- GUI changes: add/update a lightweight test for helper behavior where possible,
  or document a manual launcher smoke test.
- Output changes: inspect generated field names and explain intentional schema
  differences.
