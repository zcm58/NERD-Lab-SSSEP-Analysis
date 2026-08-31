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
  thread, progress updates, and "View Output" action. Setup checks run in the
  worker. Closing is blocked while it runs; worker ownership lasts until
  `QThread.finished`. Saved defaults keep the chosen parent output root,
  while "View Output" opens the completed run's actual child folder.

## Processing Flow

`sssep_batch/pipeline.py` is the per-file orchestration layer. It should describe
stage order, not hold low-level processing details.

Current high-level order:

1. Load the first 64 scalp channels plus EXG references and `Status`; assign
   channel types and the `standard_1005` montage before preprocessing.
2. Apply the EXG1/EXG2 reference, drop those channels, and retain scalp EEG plus
   `Status`.
3. Apply the scaled-duration 0.1–50 Hz FIR filter at the original sampling rate.
4. Downsample to 256 Hz, preserving FPVS filter metadata.
5. Run kurtosis screening at threshold 5 and interpolation, then the final
   average-reference projection over retained good EEG.
6. Find `Status` events on the preprocessed sampling grid using
   `shortest_event=1` and the reference MNE defaults for other event options.
7. Exclude unresolved bad channels from the FFT channel set. Extract complete
   SSSEP onset windows, 7.5 seconds by default, without an additional FIR edge
   margin or EEG zero replacement. Construct MNE `EpochsArray` over all retained
   channels with `baseline=None` and default projection before selecting EEG;
   this preserves FPVS's final floating-point projector effects.
8. Average repetitions in float64 per electrode, convert volts to microvolts,
   and calculate `abs(np.fft.fft(mean_epoch_uv)[:, :N // 2 + 1]) / N * 2`.
   Preserve the reference scaling at DC/Nyquist; do not taper, detrend,
   square into power, or compute Welch PSD.
9. Average amplitudes across the available configured ROI electrodes for
   plots/SSSEP summaries; retain all good scalp electrodes and nonnegative
   frequencies in amplitude CSVs. Write reports and Gap/Break comparisons.

This is `fpvs_amplitude_v1`, referenced to FPVS commit
`185d803f0056daebee04e5f28cc6b554c47336ce`. It intentionally retains SSSEP codes,
expected frequencies, and onset durations rather than FPVS's visual-oddball
1.2 Hz marker crop. Local SSSEP SNR and baseline summaries are downstream of
the parity boundary. See [FPVS method and parity checks](docs/fpvs-parity.md).

## Module Boundaries

- `sssep_batch/batch.py`
  Finds input `.bdf` files, validates batch requests, manages file-level
  parallelism, limits native threads per worker, atomically creates a unique
  run folder, and writes the batch summary there. Previous runs remain intact.
- `sssep_batch/loading.py`
  Loads the reference-compatible BioSemi channel subset from external input.
- `sssep_batch/config.py`
  User-edit configuration surface for experiment settings, trigger maps,
  constants, and optional folder defaults.
- `sssep_batch/events/`
  Parses trigger labels, filters intended `Status` events, and extracts epochs.
- `sssep_batch/preprocess/`
  Handles channel validation, montage/reference setup, scaled FIR filtering,
  subsequent downsampling, bad-channel interpolation, and final average
  reference. Preserves explicitly logged FPVS warning-and-continue behavior.
- `sssep_batch/analysis/`
  Computes per-electrode amplitude spectra, SSSEP amplitude summaries,
  Gap/Break comparisons, full-frequency tables, and diagnostic plots.
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
- A default limit of 5 means at most five amplitude PNGs per file, not five
  FFT/Welch pairs. Available condition spectra/summary rows remain independent
  of that limit.
- Keep `processing_method`, reference commit, and actual `analysis_channels` /
  `fft_channels` traceable in event summaries and reports. Old power/Welch
  schemas are retired; do not silently mix their values with amplitudes.
- Do not reuse a previous batch's output directory for a new run. Direct
  per-file callers must supply a destination without that file's result folder.

## Verification Map

- Environment: Python 3.13 (3.13.5 tested); runtime pins in `requirements.txt`;
  `requirements-dev.txt` adds pytest 9.0.1 and edfio 0.4.16 for generated BDFs.
- Processing code: compile with `.\.venv\Scripts\python.exe -m py_compile`
  and run `.\.venv\Scripts\python.exe -m pytest -q`.
- Math-sensitive changes: add/update focused unit tests and compare against a
  known local `.bdf` file when available.
- GUI changes: add/update a lightweight test for helper behavior where possible,
  and exercise worker lifetime with the isolated SSSEP Qt/process-pool tests.
- Output changes: inspect generated field names and explain intentional schema
  differences.
- External checks: `FPVS_REFERENCE_ROOT` selects the source checkout;
  `SSSEP_TEST_BDF` selects an optional recording. Keep both external to the repo.
