# NERD Lab SSSEP Analysis

## First-Time Setup On A New PC

You only need to do this setup once per computer.

### 1. Install Python (or update it)

Install Python 3.13.5 from:

https://www.python.org/downloads/

During installation, check the box that says `Add python.exe to PATH` if it is
shown.

### 2. Install PyCharm (if you don't have it installed)

Install PyCharm Community Edition from:

https://www.jetbrains.com/pycharm/download/

### 3. Get This Project Onto The Computer

Put this project folder somewhere easy to find, for example:

```text
C:\Users\YourName\PycharmProjects\Dylan SSSEP
```

Do not put `.bdf` data files inside the project folder. Keep data in a separate
folder such as:

```text
C:\Users\YourName\Desktop\SSSEP Data
```

### 4. Open The Project In PyCharm

1. Open PyCharm.
2. Click `Open`.
3. Choose the `Dylan SSSEP` project folder.
4. Wait for PyCharm to finish loading the project.

### 5. Create The Project Virtual Environment

A virtual environment is a private Python setup for this project. It keeps this
project's libraries separate from the rest of the computer.

In PyCharm:

1. Open `File` > `Settings`.
2. Go to `Project: Dylan SSSEP` > `Python Interpreter`.
3. Click `Add Interpreter`.
4. Choose `Add Local Interpreter`.
5. Choose `Virtualenv Environment`.
6. Select `New`.
7. Use `.venv` as the environment folder name.
8. Click `OK` or `Create`.

### 6. Install The Required Libraries

In PyCharm:

1. Open the `Terminal` tab at the bottom of the window.
2. Run this command:

```powershell
pip install -r requirements.txt
```

This may take several minutes. It installs the Python libraries used by the
analysis pipeline and launcher, including MNE, NumPy, SciPy, pandas,
matplotlib, PySide6, and PyYAML.

If the command fails, first check that the PyCharm terminal shows `(.venv)` near
the start of the line. If it does not, the virtual environment is not active.

## Running The Analysis

Use this exact workflow for normal analysis runs:

1. In the PyCharm Project pane, find `sssep_bdf_batch_processor.py`.
2. Right-click `sssep_bdf_batch_processor.py`.
3. Click `Run 'sssep_bdf_batch_processor'`.
4. In the launcher, choose the input folder that contains your `.bdf` files.
5. Choose the output folder where results should be saved.
6. Leave `Save folders for next time` checked if you want the launcher to
   remember those folders on this computer.
7. Click `Process Data`.
8. When processing finishes, click `View Output`.

Do not run files inside `sssep_batch` directly. The intended entrypoint is:

```text
sssep_bdf_batch_processor.py
```

## What The Output Files Mean

The output folder will contain a batch-level summary and one folder per `.bdf`
file.

Start with:

```text
batch_processing_summary.csv
```

This tells you whether each `.bdf` file finished successfully or failed. If a
file failed, check the `error` and `error_file` columns.

Each successfully processed `.bdf` file also gets its own output folder. Inside
that folder, the most useful files are:

- `*_sssep_event_summary.csv`
  Main results table for each trigger condition.
- `*_processing_report.txt`
  Human-readable processing log for that file.
- `plots\`
  Diagnostic frequency plots for a limited number of trigger conditions.

Important columns in `*_sssep_event_summary.csv`:

- `trigger_code`
  Numeric event code found in the BioSemi `Status` channel.
- `trigger_label`
  Human-readable condition label.
- `expected_frequency_hz`
  Stimulation frequency expected for that trigger.
- `usable_epochs`
  Number of usable repetitions found for that trigger.
- `epoch_count_ok`
  Whether the expected number of repetitions was found.
- `status`
  Whether that trigger condition was analyzed successfully.
- `sssep_fft_*`
  Primary SSSEP FFT metrics.
- `welch_*`
  Supplemental Welch PSD metrics.
- `*_baseline_*`
  Comparison against the gap/break baseline trigger.

If `epoch_count_ok` is `False`, the result may still exist, but fewer usable
epochs were available than expected. Check the processing report for details.

## Common Problems

### The launcher says PySide6 is missing

The required libraries were not installed in the active virtual environment.
Open the PyCharm terminal and run:

```powershell
pip install -r requirements.txt
```

### The launcher says no `.bdf` files were found

Choose the folder that directly contains the `.bdf` files. The program looks
for files ending in `.bdf` in the selected folder.

### The run is slow

Large EEG files can take time. The project processes multiple files at once
using `BATCH_WORKERS` in `sssep_batch/config.py`. On a typical 16 GB computer,
leave this set to `3` unless you know the computer has enough memory for more.

### A file failed but the rest finished

Open `batch_processing_summary.csv`, find the failed file, then open the
`ERROR.txt` file listed in the failed file's output folder.

For a longer checklist, see:

```text
docs\troubleshooting.md
```

## Project Layout

- `sssep_bdf_batch_processor.py`
  The file to run in PyCharm for normal analysis.
- `sssep_batch`
  The implementation package.
- `sssep_batch/gui.py`
  Opens the folder-selection launcher.
- `sssep_batch/batch.py`
  Finds `.bdf` files, runs the batch, logs progress, and writes the batch
  summary.
- `sssep_batch/pipeline.py`
  Runs the processing steps for one `.bdf` file.
- `sssep_batch/config.py`
  Holds experiment settings, trigger maps, analysis constants, output toggles,
  and optional fallback folders.

## Analysis Notes

The pipeline detects `Status` events before downsampling and carries those
events through resampling. Epochs near FIR filter boundaries are excluded from
analysis. The pipeline downsamples recordings to `256 Hz` before later analysis
stages to reduce memory use and processing time.

Parallel processing is across files. It does not split filtering, FFT, plotting,
or any other work inside a single file across multiple workers.

## File Reference

- `models.py`
  Holds small shared data containers such as `EpochSet` and `Spectrum`.
- `logging_utils.py`
  Holds folder creation and batch/per-file logging helpers.
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

## Testing

Testing is mainly for development work when the code is being changed. It is
not needed for normal day-to-day analysis runs in PyCharm.

If you are changing processing logic, structure, or outputs, run the unit tests
from the repository root with:

```powershell
python -m pytest -q
```

The regression test uses an external local `.bdf` fixture on purpose so the
repository does not need to store binary EEG data. To enable it, set the
`SSSEP_TEST_BDF` environment variable to a local `.bdf` path before running
pytest. If `SSSEP_TEST_BDF` is not set, that regression test skips cleanly by
default.

## Developer Rules

If you edit this repo in the future, follow these rules:

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
8. Keep each file below 400 lines if possible.

## Refactor Safety Checklist

When changing structure again, verify:

1. `python -m py_compile` still passes.
2. The wrapper entrypoint still runs.
3. The per-file stage order in `pipeline.py` did not change unintentionally.
4. Output CSV/report field names stayed stable unless intentionally revised.
5. A known `.bdf` file produces equivalent results if the math was not meant to
   change.
