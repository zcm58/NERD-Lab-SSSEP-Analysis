# Troubleshooting

Use this checklist when the launcher opens but processing does not finish as
expected.

## The Launcher Says A Package Is Missing

The active Python environment does not have everything from `requirements.txt`.

What to try:

1. Open the PyCharm terminal.
2. Confirm its working directory is this project and `.venv` exists.
3. Run `.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt`.
4. Run `sssep_bdf_batch_processor.py` again.

The command explicitly selects the project interpreter; an activated-terminal
prompt is not required. Keep the package pins so the numerical environment
matches the FPVS reference. pytest 9.0.1 and edfio 0.4.16 are development-only
dependencies for tests and generated BDF fixtures; install them with
`.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt`.

## No `.bdf` Files Were Found

The input folder must directly contain the `.bdf` files. The program does not
search every subfolder.

What to try:

1. Open the folder in Windows Explorer.
2. Confirm files ending in `.bdf` are visible there.
3. Choose that exact folder in the launcher.

## The Output Folder Cannot Be Created

Windows may block writing to protected folders or disconnected drives.

What to try:

1. Choose a normal folder such as Desktop or Documents.
2. Avoid system folders such as `C:\Program Files`.
3. Make sure the drive is connected and not read-only.

## A Single File Failed But The Batch Continued

This is expected. The batch tries to process the remaining files.

What to check:

1. Click `View Output` and open that run's `batch_processing_summary.csv`.
2. Find the row for the failed file.
3. Open the path listed in the `error_file` column.
4. Read the beginner summary at the top of `ERROR.txt`.

An unexpected worker-process crash may not produce `ERROR.txt`. If `error_file`
is empty, inspect the summary's `error` column and `sssep_batch_processing.log`
in the same run folder.

## Results Are In A New Folder After Each Run

This is intentional. A batch creates a unique
`run_YYYYMMDD_HHMMSS_<unique>` folder under the output root you selected. It
keeps earlier summaries, plots, and errors separate from new results.

`View Output` opens the completed run folder; the saved default continues to
point to the parent output root. Do not copy old condition files into the new
run. Direct calls to the per-file processor also reject an existing result
folder; supply a fresh destination rather than deleting previous results.

## The Window Will Not Close During Processing

The launcher blocks closing while its background worker is active so processing
can finish and save its results safely. Wait for completion, then close the
window normally. There is no cancel action. Force-stopping Python or PyCharm
can leave the current run incomplete; check its summaries and logs before using
any partial output.

## The Run Is Slow

Large EEG files can take time and memory.

What to try:

1. Leave `BATCH_WORKERS = 3` on typical 16 GB computers.
2. Lower `BATCH_WORKERS` to `1` or `2` if the computer becomes unresponsive.
3. Close other memory-heavy programs before running a large batch.

The FIR filter now runs at the original recording sampling rate before
downsampling to 256 Hz. This preserves the FPVS method and can be more
expensive than the retired downsample-first pipeline. Do not reorder those
steps as a performance workaround.

## There Are Fewer Plots Than Condition Results

`MAX_INDIVIDUAL_PLOTS = 5` means at most five amplitude PNGs per recording.
Each eligible condition now has one amplitude plot rather than an FFT/Welch
pair. The cap does not limit FFT calculations, summary rows, or spectrum CSVs.
With `SAVE_CSV_SUMMARIES = True`, every usable active condition gets an
amplitude CSV. A condition with no complete epochs cannot produce a spectrum.

## Amplitudes Differ From Old Power Or Welch Results

The method changed intentionally to `fpvs_amplitude_v1`. It filters and
references in the FPVS order, averages repetitions in float64 separately for
each electrode, and computes FFT amplitudes in microvolts without Hann
tapering or detrending. Old `*_power` and `welch_*` fields are retired.

Do not directly compare or pool those old values with new `*_amplitude_uv`
values. Check `processing_method` and `fpvs_reference_commit` in the new event
summary, and rerun recordings with a common method/settings when needed. The
SSSEP onset windows, trigger codes, and expected frequencies remain specific
to this experiment. See [FPVS method and parity checks](fpvs-parity.md).

## A File Finished But Its Report Contains Warnings

Some preprocessing operations retain the FPVS reference's logged
warning-and-continue behavior. A finished file does not prove every step
succeeded. Review the processing report, actual final sampling rate,
`bad_channel_metrics.csv`, and the event summary's `analysis_channels` and
`fft_channels` before interpreting its amplitudes.

Channels still marked bad after interpolation are excluded from the FFT and
ROI summaries; the actual ROI may contain fewer than 16 electrodes. An
`epoch_count_ok` value of `False` means the usable repetition count is
different from the expected count, not necessarily lower. Missing complete
Gap/Break epochs leave baseline comparisons unavailable.

## Saved Folder Defaults Are Wrong

The launcher stores folder defaults in `.sssep_gui_settings.json`.

What to try:

1. Choose the correct folders in the launcher.
2. Leave `Save folders for next time` checked.
   The parent output root is saved after a completed batch, not its run folder.
3. If the saved settings file becomes invalid, delete `.sssep_gui_settings.json`
   and choose folders again.

## Config Edits Cause Setup Errors

The launcher checks obvious `sssep_batch/config.py` mistakes before processing.

What to try:

1. Undo the most recent config edit.
2. Make sure every code in `ACTIVE_EVENT_CODES` has entries in `TRIGGER_LABELS`
   and `TRIGGER_HZ_MAP`.
3. Keep `LOWCUT < HIGHCUT`.
4. Keep `FMIN` and `FMAX` inside the filter range.
