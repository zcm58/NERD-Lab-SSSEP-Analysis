# NERD Lab SSSEP Analysis

## First-Time Setup On A New PC

You only need to do this setup once per computer.

### 1. Install Python (or update it)

Use **64-bit Python 3.13** for this project's pinned packages. Verification
used Python 3.13.5; its release page includes the Windows 64-bit installer:

[Python 3.13.5 release](https://www.python.org/downloads/release/python-3135/)

Do not automatically choose the newest Python major/minor version. Python
3.14 and later are not the tested environment, and these package pins may not
have compatible wheels for them.

During installation, check the box that says `Add python.exe to PATH` if it is
shown.

### 2. Install PyCharm (if you don't have it installed)

Install PyCharm from:

[PyCharm downloads](https://www.jetbrains.com/pycharm/download/)

PyCharm now uses a unified application; its free core features are sufficient
for this project. See the official
[PyCharm quick start guide](https://www.jetbrains.com/help/pycharm/quick-start-guide.html).

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
7. Set `Base interpreter` to the installed **Python 3.13** interpreter
   (3.13.5 for the exact tested version), not an automatically selected newer Python.
8. Use `.venv` as the environment folder name.
9. Click `OK` or `Create`.

### 6. Install The Required Libraries

In PyCharm:

1. Open the `Terminal` tab at the bottom of the window.
2. Run this command:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

This may take several minutes. It installs the Python libraries used by the
analysis pipeline and launcher. Versions are pinned to the FPVS reference
environment: MNE 1.9.0, NumPy 2.3.1, SciPy 1.16.0, pandas 2.3.0,
matplotlib 3.10.3, and PySide6 6.9.1.

Run this command from the project folder. It explicitly uses the project's
Python interpreter, so activating the virtual environment is not required.
If the interpreter is not found, finish step 5 before installing packages.

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

Setup checks and processing run in the background. The launcher stays open
while a batch is active; clicking its close button during processing displays
a reminder to wait. After processing, it can be closed normally.

Every run creates a new folder named `run_YYYYMMDD_HHMMSS_<unique>` beneath your
chosen output folder. `View Output` opens that run folder. Saved folder defaults
remember the parent folder after a completed batch, not the individual run.
Existing results are never reused or overwritten by a later batch.

Do not run files inside `sssep_batch` directly. The intended entrypoint is:

```text
sssep_bdf_batch_processor.py
```

## What The Output Files Mean

Each new run folder contains a batch-level summary and one folder per `.bdf`
file. Use the folder opened by `View Output`, rather than results from an older
run.

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
  Trigger subfolders containing `*_sssep_fft_amplitude.csv` spectra and
  `*_sssep_fft_amplitude.png` diagnostic plots. CSVs retain every good scalp
  electrode from 0 Hz through the highest nonnegative FFT bin (128 Hz for the
  default 256 Hz, 7.5-second epochs). Plots show the selected-channel mean over
  `FMIN` to `FMAX`, currently 3–50 Hz.
- `detected_status_events.csv`
  Event audit on the final, preprocessed sampling grid.
- `bad_channel_metrics.csv`
  Kurtosis screening and interpolation details to review with the report.

`MAX_INDIVIDUAL_PLOTS = 5` creates at most five amplitude PNGs per recording.
It does not limit condition summaries or FFT calculations. With
`SAVE_CSV_SUMMARIES = True`, amplitude CSVs are written for every usable active
condition, including conditions without a PNG. The main event summary is
always written.

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
- `processing_method` and `fpvs_reference_commit`
  Identify `fpvs_amplitude_v1` and reference commit
  `185d803f0056daebee04e5f28cc6b554c47336ce`.
- `analysis_channels` and `fft_channels`
  Record the actual electrodes used in the summary and full FFT. Channels still
  marked bad after interpolation are excluded; the summary may therefore use
  fewer than the configured 16 electrodes.
- `sssep_fft_nearest_amplitude_uv`, `sssep_fft_target_band_mean_amplitude_uv`,
  and related `*_amplitude_uv` fields
  FFT amplitudes in microvolts, averaged across the selected electrodes after
  computing each electrode's FFT.
- `sssep_fft_local_amplitude_snr` and `sssep_fft_local_amplitude_snr_db`
  The target-bin amplitude relative to the local SSSEP noise band. This is an
  SSSEP summary, not the FPVS Toolbox's neighboring-bin SNR method.
- `baseline_sssep_fft_*` and `sssep_fft_*_amplitude_ratio` / `*_amplitude_db`
  Comparisons against separately measured Gap/Break baseline epochs. Missing
  baseline epochs leave these comparisons unavailable. Amplitude ratios use
  `20 * log10(ratio)` for decibels.

If `epoch_count_ok` is `False`, the usable repetition count differs from the
expected count; it may be lower or higher. Check the processing report before
interpreting the result. A batch success does not remove warnings or prove that
all conditions have complete data.

The former power and Welch outputs have been intentionally retired. New
amplitude fields are not numerically interchangeable with old `*_power` or
`welch_*` results. Do not pool old and new methods; rerun recordings with the
same settings when a common method is needed. See
[FPVS method and parity checks](docs/fpvs-parity.md) for the comparison boundary.

## Common Problems

### The launcher says PySide6 is missing

The required libraries were not installed in the active virtual environment.
Open the PyCharm terminal and run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
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
`ERROR.txt` file listed in the failed file's output folder within that run.
An unexpected worker-process crash may have no `error_file`; in that case,
read the row's `error` value and `sssep_batch_processing.log`.

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
- `docs/fpvs-parity.md`
  Records the FPVS reference, comparison scope, and verification evidence.
- `requirements.txt` and `requirements-dev.txt`
  Pinned runtime packages and the development/test environment, respectively.

## Analysis Notes

The current method follows FPVS preprocessing and its per-electrode amplitude
FFT while retaining this experiment's SSSEP triggers, expected frequencies,
and 7.5-second onset windows. It does not apply FPVS's visual-oddball 1.2 Hz
marker crop.

The processing order is:

1. Load the first 64 scalp channels, EXG references, and `Status`; apply the
   `standard_1005` montage before preprocessing.
2. Apply the EXG1/EXG2 reference, drop those references, and keep scalp EEG plus
   `Status`.
3. Apply the 0.1–50 Hz FIR filter at the original sampling rate, scaling its
   length to preserve the FPVS filter duration, then downsample to 256 Hz.
4. Detect unusual kurtosis at the configured threshold of 5, interpolate bad
   channels, and apply the final average reference over retained good EEG.
5. Detect `Status` events after preprocessing with the reference MNE event
   options, then extract complete SSSEP onset windows. There is no additional
   FIR edge margin and no replacement of EEG values with zeros. Match FPVS's
   MNE `EpochsArray` construction, including its default reference projection.
6. Average repetitions in float64 separately for each electrode; convert volts
   to microvolts; calculate `abs(FFT(mean_epoch_uv)) / N * 2` for the first
   `N // 2 + 1` bins. This follows FPVS's scaling, including DC and Nyquist,
   without a Hann taper, detrending, power squaring, or Welch PSD.

The FFT retains good scalp electrodes. Only afterward are electrode amplitudes
averaged across the configured 16-channel ROI for plots and summaries. If
interpolation leaves bad channels unresolved, they are excluded and the actual
channel lists are reported. This is not an FFT of a channel-averaged EEG signal.

Some preprocessing operations preserve the FPVS reference's logged
warning-and-continue behavior. Review the report's warnings, final sampling
rate, and actual channel lists; a finished run alone does not establish that
every requested preprocessing step succeeded.

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
  Computes target-frequency amplitude metrics, local SSSEP amplitude SNR,
  and Gap/Break amplitude comparisons.
- `analysis/spectra.py`
  Computes the float64 trial mean and each electrode's FPVS amplitude FFT.
- `analysis/plotting.py`
  Converts spectra to tabular output and writes diagnostic plots.
- `events/status.py`
  Parses labels and extracts intended events from `Status` after preprocessing.
- `events/epochs.py`
  Cuts complete fixed SSSEP windows; skips windows outside the recording.
- `loading.py`
  Reads the FPVS-compatible BioSemi channel subset without changing the input.
- `preprocess/channels.py`
  Validates channels, applies reference handling, keeps the intended channels,
  and assigns montage/channel types.
- `preprocess/filtering.py`
  Applies the scaled FIR filter at the original sampling rate, then resamples.
- `preprocess/bad_channels.py`
  Detects bad channels by kurtosis and runs interpolation.

## Testing

Testing is mainly for development work when the code is being changed. It is
not needed for normal day-to-day analysis runs in PyCharm.

If you are changing processing logic, structure, or outputs, install the
development requirements from the repository root, then run the tests:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

`requirements-dev.txt` includes the runtime pins, pytest 9.0.1, and edfio
0.4.16 for generated BDF fixtures. The default suite uses synthetic data;
GUI lifecycle checks run in isolated offscreen SSSEP subprocesses without
processing participant EEG.

Optional regression checks use external files so the repository does not need
to store binary EEG data. Set `SSSEP_TEST_BDF` to a local recording and
`FPVS_REFERENCE_ROOT` to the reference source checkout when running the
corresponding checks:

```powershell
$env:SSSEP_TEST_BDF = "C:\Data\SSSEP\recording.bdf"
$env:FPVS_REFERENCE_ROOT = "C:\Projects\FPVS Toolbox Repo"
.\.venv\Scripts\python.exe -m pytest -q
```

Checks whose optional environment variable is unset skip. A supplied reference
path must exist and match the expected source hashes. Reference comparisons use
the pinned FPVS source and matching settings, not historical SSSEP power or
Welch results. See [FPVS method and parity checks](docs/fpvs-parity.md) for
details and the limits of the available evidence.

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

1. Compilation with the project interpreter still passes.
2. The wrapper entrypoint still runs.
3. The per-file stage order in `pipeline.py` did not change unintentionally.
4. Output CSV/report field names stayed stable unless intentionally revised.
5. A known `.bdf` file produces equivalent results when the method was not
   meant to change; intentional method changes have explicit reference tests
   and output-version documentation.
