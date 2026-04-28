# Troubleshooting

Use this checklist when the launcher opens but processing does not finish as
expected.

## The Launcher Says A Package Is Missing

The active Python environment does not have everything from `requirements.txt`.

What to try:

1. Open the PyCharm terminal.
2. Confirm the prompt starts with `(.venv)`.
3. Run `pip install -r requirements.txt`.
4. Run `sssep_bdf_batch_processor.py` again.

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

1. Open `batch_processing_summary.csv`.
2. Find the row for the failed file.
3. Open the path listed in the `error_file` column.
4. Read the beginner summary at the top of `ERROR.txt`.

## The Run Is Slow

Large EEG files can take time and memory.

What to try:

1. Leave `BATCH_WORKERS = 3` on typical 16 GB computers.
2. Lower `BATCH_WORKERS` to `1` or `2` if the computer becomes unresponsive.
3. Close other memory-heavy programs before running a large batch.

## Saved Folder Defaults Are Wrong

The launcher stores folder defaults in `.sssep_gui_settings.json`.

What to try:

1. Choose the correct folders in the launcher.
2. Leave `Save folders for next time` checked.
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
