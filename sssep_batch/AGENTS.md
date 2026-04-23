# AGENTS.md

## Package Role

`sssep_batch` is the implementation package for the SSSEP processor. It exists
to keep the old monolithic script split into focused modules with small,
dedicated responsibilities.

The main human-facing repository overview now lives in the root `README.md`.
Use that file for project-level workflow, structure, and validation context.

The package is organized around these boundaries:

- `batch.py`
  Batch discovery, worker setup, and parent-process summary writing.
- `pipeline.py`
  Per-file stage order only.
- `analysis/`
  Spectrum computation, metrics, and plotting helpers.
- `events/`
  Status-channel event detection and epoch extraction.
- `preprocess/`
  Channel setup, downsampling, filtering, and bad-channel handling.
- `outputs.py`
  Summary CSV and text report writing.

## Non-Negotiable Design Intent

1. `pipeline.py` defines order; helper modules define implementation.
2. `config.py` is the single settings source for normal use.
3. Keep helpers close to their domain. Do not reintroduce a monolith through
   cross-cutting helper files.
4. Prefer pure or near-pure functions in submodules where practical.

## Pipeline Facts Future Agents Must Preserve

- `find_status_events()` runs before downsampling.
- `downsample_if_needed()` may receive events and must return the event matrix
  aligned to the post-resample sample grid.
- Filter validation exists to protect target SSSEP frequencies from invalid
  cutoffs.
- `get_fir_edge_margin_samples()` is part of the analysis correctness model.
  Epochs inside that edge margin are intentionally excluded.
- `process_one_bdf()` writes durable per-file reports and should keep its final
  success lines in `report_lines` before the report is written.

## Parallel Processing Notes

- Worker parallelism is file-level and process-based.
- The parent process owns the shared batch log and final batch summary.
- Worker detail should stay in per-file reports and per-file outputs.
- `BATCH_WORKERS = 3` is the recommended ceiling for typical 16 GB systems, but
  it remains configurable in `config.py`.
- Thread-cap environment variables are intentionally forced to `1` before
  worker spawn. Do not weaken that behavior casually.

## Editing Guidance By Area

### `analysis/`

- Changes here are likely to affect mathematical output.
- Add or update tests before changing frequency-domain behavior.
- Keep outputs stable unless the user explicitly requests a metric/schema
  change.

### `events/`

- Be careful with sample indexing and trigger-code filtering.
- Event timing mistakes silently change which data enters each epoch.

### `preprocess/`

- Downsampling, filtering, and interpolation can affect both performance and
  analysis correctness.
- Avoid hidden fallbacks that let invalid filter settings or missing channels
  slip through silently.

### `outputs.py`

- Treat CSV/report field names as externally consumed outputs.
- Backward-compatible additions are safer than renames or removals.

## Validation Expectations

When touching this package, usually run:

1. `python -m py_compile sssep_bdf_batch_processor.py sssep_batch\...`
2. `python -m pytest -q`

If you change behavior in `analysis`, `events`, or `preprocess`, prefer to
extend tests in `tests/` in the same change.
