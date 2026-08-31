# Code map

[Home](README.md) · [Student user guide](docs/user-guide.md) · [Processing method](docs/fpvs-parity.md)

For normal runs, use `sssep_bdf_batch_processor.py`. For settings, edit
`sssep_batch/config.py`. Read the map below when changing the program itself.

## Find the right file

| If you want to change… | Start here |
| --- | --- |
| Everyday options or study settings | [config.py](sssep_batch/config.py) |
| The launcher window, folder choices, or progress messages | [gui.py](sssep_batch/gui.py) |
| Finding files, running workers, or creating run folders | [batch.py](sssep_batch/batch.py) |
| The order of processing steps for one recording | [pipeline.py](sssep_batch/pipeline.py) |
| Reading a BDF file | [loading.py](sssep_batch/loading.py) |
| Electrode types, montage, or references | [preprocess/channels.py](sssep_batch/preprocess/channels.py) |
| Filtering or resampling | [preprocess/filtering.py](sssep_batch/preprocess/filtering.py) |
| Bad-channel detection or interpolation | [preprocess/bad_channels.py](sssep_batch/preprocess/bad_channels.py) |
| Trigger detection or trial windows | [events/](sssep_batch/events/) |
| FFT calculation | [analysis/spectra.py](sssep_batch/analysis/spectra.py) |
| Target-frequency results or baseline comparisons | [analysis/metrics.py](sssep_batch/analysis/metrics.py) |
| Graphs or full FFT tables | [analysis/plotting.py](sssep_batch/analysis/plotting.py) |
| Summary CSVs, reports, or error files | [outputs.py](sssep_batch/outputs.py) |

[models.py](sssep_batch/models.py) defines the data containers passed between
modules. [logging_utils.py](sssep_batch/logging_utils.py) supports file logging.

## How the parts connect

`entrypoint → gui → batch → pipeline → preprocessing / events / analysis → outputs`

`pipeline.py` coordinates stages; low-level work belongs in the relevant
module. Keep the entrypoint thin and settings in `config.py`. Do not add a
second launcher, duplicate settings file, or generic utility module.

The numerical order is load/montage → EXG reference/drop → filter → resample
→ interpolate → average reference → events → SSSEP epochs → trial mean
→ per-electrode amplitude FFT → ROI plots and summaries.

Epochs must pass through MNE `EpochsArray` with all retained channels and
default projection before good EEG selection. This preserves FPVS's
floating-point projector behavior. The full numerical contract and reference
source are in [fpvs-parity.md](docs/fpvs-parity.md); do not duplicate that
specification in student instructions.

## Keep these behaviors

- Preserve the validated FPVS method unless an analysis change is authorized.
- Keep SSSEP trial timing and output field names stable.
- Keep data outside the repo and each batch in a fresh run folder.
- Parallelize across recordings; cap native threads at one per worker.
- Retain GUI workers until `QThread.finished`; block close while processing.
- Limit only PNG creation with `MAX_INDIVIDUAL_PLOTS`, never FFTs or CSVs.
- Keep warnings and failures visible; do not hide them with silent fallbacks.

## After changing code

1. Change one thing at a time and inspect the diff.
2. Install the test libraries once, then run the checks from the project folder:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
   .\.venv\Scripts\python.exe -m pytest -q
   ```

3. Run the usual PyCharm entrypoint and check the affected behavior.
4. Update the relevant guide if a setting, output, or workflow changed.

Tests mirror the code folders under [tests/](tests/). They use synthetic EEG;
an unset `FPVS_REFERENCE_ROOT` or `SSSEP_TEST_BDF` skips the corresponding
optional check. For math changes, also run the
[FPVS reference comparisons](docs/fpvs-parity.md#verification-and-reproducibility)
and compare a known recording when available. Do not treat a skipped check
as a passing comparison.

Use Python 3.13 (3.13.5 tested) and the existing dependency pins. Keep
`AGENTS.md` as a map for coding assistants, student guides brief, and detailed
scientific documentation in `docs/fpvs-parity.md`.
