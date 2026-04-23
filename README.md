# NERD Lab SSSEP Analysis

## Introduction

This repository contains the BioSemi `.bdf` SSSEP batch processor as a
structured package instead of one monolithic script. That design makes the code
easier to inspect, maintain, test, and extend because configuration,
preprocessing, event handling, spectral analysis, plotting, and output writing
now live in separate focused files.

The current design also improves processing speed. It downsamples data to
`256 Hz` before later analysis stages to reduce memory use and processing cost,
and it supports file-level parallel processing so multiple `.bdf` files can be
processed at the same time on machines with enough memory.

It also fixes several correctness issues from the earlier pipeline design. In
particular, trigger events are now detected before downsampling and carried
forward through resampling, epochs near FIR filter boundaries are excluded from
analysis, and parallel runs now enforce native thread limits so worker
processes do not oversubscribe the machine.

Before you start, create or activate your local virtual environment and run:

`pip install -r requirements.txt`

## Current Role

- `sssep_bdf_batch_processor.py` is the compatibility entrypoint.
  In PyCharm, this is the file to run.
- `sssep_batch` contains the implementation.
- `sssep_batch.batch.main()` is the batch runner used by the wrapper.
- `sssep_batch.pipeline.process_one_bdf()` is the per-file orchestration layer.

## How To Run In PyCharm

Use this exact workflow:

1. Open [config.py](<C:/Users/zcm58/PycharmProjects/Dylan SSSEP/sssep_batch/config.py>) and edit the settings you want to use.
   `BATCH_WORKERS = 3` controls how many `.bdf` files run at once.
   Start with `3`. On typical 16 GB machines, values above `3` are not
   recommended unless you have tested memory headroom and stability.
2. In the PyCharm Project pane, locate [sssep_bdf_batch_processor.py](<C:/Users/zcm58/PycharmProjects/Dylan SSSEP/sssep_bdf_batch_processor.py>).
3. Right-click `sssep_bdf_batch_processor.py`.
4. Click `Run 'sssep_bdf_batch_processor'`.

Do not run package modules directly. The intended user entrypoint is
[sssep_bdf_batch_processor.py](<C:/Users/zcm58/PycharmProjects/Dylan SSSEP/sssep_bdf_batch_processor.py>), and the intended user-edit configuration file is
[config.py](<C:/Users/zcm58/PycharmProjects/Dylan SSSEP/sssep_batch/config.py>).

## Parallel Processing

Parallel processing here is across files only. Each worker is a separate
process handling one `.bdf` file at a time.

Increasing `BATCH_WORKERS` does not always make runs faster. On low-RAM
systems, memory pressure can rise quickly because each worker may hold a full
recording and several intermediate arrays during filtering, interpolation,
FFT/Welch, plotting, and report generation. On a typical 16 GB system, start
with `3` and do not increase above `3` unless you have tested memory headroom
and stability.

## Intended Repository Structure

The intended long-term shape of this repository is:

```text
C:\Users\zcm58\PycharmProjects\Dylan SSSEP\
  README.md
  sssep_bdf_batch_processor.py
  sssep_batch\
    __init__.py
    batch.py
    pipeline.py
    config.py
    models.py
    logging_utils.py
    outputs.py
    analysis\
      __init__.py
      metrics.py
      plotting.py
      spectra.py
    events\
      __init__.py
      epochs.py
      status.py
    preprocess\
      __init__.py
      bad_channels.py
      channels.py
      filtering.py
  tests\
    test_pipeline.py
    test_regression_external_bdf.py
    analysis\
      test_metrics.py
      test_spectra.py
    events\
      test_epochs.py
      test_status.py
    preprocess\
      test_channels.py
      test_filtering.py
```

## Module Responsibilities

- `config.py`
  Holds all experiment settings, trigger maps, analysis constants, and output
  toggles.
- `models.py`
  Holds small shared data containers such as `EpochSet` and `Spectrum`.
- `logging_utils.py`
  Holds folder creation and batch/per-file logging helpers.
- `batch.py`
  Discovers `.bdf` files, runs the per-file pipeline, and writes the batch
  summary.
- `pipeline.py`
  Defines the processing order for a single `.bdf` file. This file should stay
  orchestration-focused and avoid absorbing low-level implementation details.
- `outputs.py`
  Writes summary CSVs, processing reports, and error reports.
- `analysis/metrics.py`
  Computes target-frequency metrics, SNR, and baseline comparison values.
- `analysis/spectra.py`
  Computes the averaged-epoch FFT and Welch PSD spectra.
- `analysis/plotting.py`
  Converts spectra to tabular output and writes diagnostic plots.
- `events/status.py`
  Parses trigger labels and extracts intended events from the BioSemi `Status`
  channel.
- `events/epochs.py`
  Cuts fixed analysis windows from detected events and enforces edge exclusion.
- `preprocess/channels.py`
  Validates channels, applies reference handling, keeps the intended channels,
  and assigns montage/channel types.
- `preprocess/filtering.py`
  Handles downsampling, finite-value cleanup, FIR filtering, notch filtering,
  filter validation, and the FIR edge margin rule.
- `preprocess/bad_channels.py`
  Detects bad channels by kurtosis and runs interpolation.

## Design Rules

These rules should guide future edits:

1. `pipeline.py` defines stage order.
2. `config.py` remains the single source of truth for settings.
3. Avoid adding a generic `utils.py`.
4. Keep new code in the most specific module that matches its responsibility.
5. Prefer pure functions in submodules and keep file I/O concentrated in
   `batch.py`, `pipeline.py`, and `outputs.py`.
6. Preserve mathematical output unless a change is explicitly intended and
   validated.
7. The intended user-edit surface is `config.py`, not command-line arguments.

## Near-Term Cleanup Targets

The package split is in place, but these are the next logical cleanup steps:

1. Unit tests now cover `events`, `analysis`, and `preprocess` with synthetic
   arrays and small constructed MNE objects. Keep extending those tests before
   changing core math or preprocessing rules.
2. User-facing settings are already centralized in `config.py`. Keep it that
   way and avoid scattering runtime configuration across multiple files.
3. `pipeline.py` was reviewed and intentionally kept as-is for now because it
   is still mostly orchestration. Split it further only if it stops being a
   clear stage-order file.
4. `MAX_INDIVIDUAL_PLOTS` is now enforced. Keep it if output volume needs to
   stay bounded, or revise the value in `config.py` if users want a different
   cap.
5. One regression path now exists through an external local `.bdf` fixture.
   Extend that path when you need stronger before/after validation on real
   data.

## Testing

Run the unit tests from the repository root with:

`python -m pytest -q`

The regression test uses an external local `.bdf` fixture on purpose so the
repository does not need to store binary EEG data. To enable it, set the
`SSSEP_TEST_BDF` environment variable to a local `.bdf` path before running
pytest. If `SSSEP_TEST_BDF` is not set, that regression test skips cleanly by
default.

## Refactor Safety Checklist

When changing structure again, verify:

1. `python -m py_compile` still passes.
2. The wrapper entrypoint still runs.
3. The per-file stage order in `pipeline.py` did not change unintentionally.
4. Output CSV/report field names stayed stable unless intentionally revised.
5. A known `.bdf` file produces equivalent results if the math was not meant to
   change.
