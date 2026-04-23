# NERD Lab SSSEP Analysis

## Overview

This repository contains the BioSemi `.bdf` SSSEP batch processor as a
structured package instead of one monolithic script. That design makes the code
easier to inspect, maintain, test, and extend because configuration,
preprocessing, event handling, spectral analysis, plotting, and output writing
now live in separate focused files.

The current design also improves processing speed. It downsamples data to
`256 Hz` before later analysis stages to reduce memory use and processing cost,
and it supports file-level parallel processing so multiple `.bdf` files can be
processed at the same time. Yay for multi-core CPUs. 

It also fixes several issues from Dylan's earlier design (no hate, just trying to help)
In particular, trigger IDs are now detected before downsampling and carried
forward through resampling, epochs near FIR filter boundaries are excluded from
analysis, and parallel processing was implemented and is designed for potato laptops with 16 gigs of ram. 

Before you start, create or activate your local virtual environment and run:

`pip install -r requirements.txt`

The above command will install the libraries directly into your virtual environment rather than
across your whole machine. This is good coding practice - keeping projects and their dependencies separate from each other. 

The PyCharm entrypoint now opens a small folder-selection launcher. The
launcher lets you choose input and output folders, save those folders for the
next run, start processing, and open the output folder when processing is done.

## Project Layout

- `sssep_bdf_batch_processor.py` is THE file. It's like Dr. D.

  In PyCharm, this is the file you'll run to actually process/analyze the data. 
- `sssep_batch` contains the implementation.
- `sssep_batch.gui.launch_gui()` opens the basic launcher used by the wrapper.
- `sssep_batch.batch.run_batch()` is the batch runner used by the launcher.
- `sssep_batch.pipeline.process_one_bdf()` is the per-file orchestration layer.

## How To Run In PyCharm

Use this exact workflow:

1. Create or activate the project virtual environment and run
   `pip install -r requirements.txt`.
2. In the PyCharm Project pane, locate
   [sssep_bdf_batch_processor.py](sssep_bdf_batch_processor.py).
3. Right-click `sssep_bdf_batch_processor.py`.
4. Click `Run 'sssep_bdf_batch_processor'`.
5. In the launcher, choose the input folder containing `.bdf` files and the
   output folder where results should be saved.
6. Leave `Save folders for next time` checked if you want the launcher to
   remember those folders locally, then click `Process Data`.
7. When processing finishes, click `View Output` to open the output folder.

Do not run package modules directly. The intended user entrypoint is
[sssep_bdf_batch_processor.py](sssep_bdf_batch_processor.py). Advanced
experiment constants and fallback defaults live in
[config.py](sssep_batch/config.py), but routine folder selection is handled by
the launcher.

## Parallel Processing

Parallel processing just lets you process more than one file at a time. Should speed up analysis. 

The 'batch worker' count sets how many files you wwant to process at once. 

Increasing `BATCH_WORKERS` does not always make runs faster. On low-RAM
systems, memory pressure can rise quickly because each worker may hold a full
recording and several intermediate arrays during filtering, interpolation,
FFT/Welch, plotting, and report generation. On a typical 16 GB system, start
with `3` and do not increase above `3` unless you have tested memory headroom
and stability.

## Repository Structure

The intended long-term shape of this repository is:

```text
C:\Users\zcm58\PycharmProjects\Dylan SSSEP\
  README.md
  sssep_bdf_batch_processor.py
  sssep_batch\
    __init__.py
    batch.py
    gui.py
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

## Here's what each file does 

- `config.py`
  Holds experiment settings, trigger maps, analysis constants, output toggles,
  and optional fallback folders.
- `models.py`
  Holds small shared data containers such as `EpochSet` and `Spectrum`.
- `logging_utils.py`
  Holds folder creation and batch/per-file logging helpers.
- `gui.py`
  Opens the basic PySide6 launcher, saves local folder defaults, and starts the
  batch runner in a background thread.
- `batch.py`
  Validates selected folders, discovers `.bdf` files, runs the per-file
  pipeline, logs batch progress, and writes the batch summary.
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

If you're editing this repo in the future, follow these rules: 

1. `pipeline.py` defines stage order.
2. `config.py` remains the single source of truth for experiment settings.
3. Avoid adding a generic `utils.py`.
4. Keep new code in the most specific module that matches its responsibility.
5. Prefer pure functions in submodules and keep file I/O concentrated in
   `batch.py`, `pipeline.py`, and `outputs.py`.
6. Preserve mathematical output unless a change is explicitly intended and
   validated.
7. The intended user entrypoint is the PyCharm launcher, not command-line
   arguments.
8. Keep each file below 400 lines if possible. The smaller each file is, the easier it is to understand.

## Testing

Testing is mainly for development work when the code is being changed. It is
not something you need for normal day-to-day analysis runs in PyCharm.

If you are changing processing logic, structure, or outputs, run the unit tests
from the repository root with:

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
