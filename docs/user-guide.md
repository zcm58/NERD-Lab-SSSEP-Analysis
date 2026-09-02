# User guide

[Home](../README.md) · [Installation](installation.md) · [Help](troubleshooting.md)

Open the project in PyCharm, right-click `main.py`, and choose **Run**.
Use **File > Settings** to edit the experiment. Use **View** to choose
**SSSEP Task**, **Process Data**, or **Generate FFT Plots**.

## Run a participant task

TENS stimulation is controlled separately. Set it up before starting the task.

1. Open **File > Settings**. Choose a task log folder outside the project.
2. Check the epoch duration (default 15 seconds), break duration (10 seconds),
   and **epochs per condition** (10, giving 20 overall). The count must be even.
   Edit participant text if needed, then click **Save**. Saved settings return
   when you reopen the app; **Cancel** keeps your previous settings.
3. Connect the BioSemi trigger interface on its fixed `COM3` port and start
   recording. For a practice run without BioSemi, enable **Test mode (no
   BioSemi triggers)** in Settings and confirm **Yes** when starting.
4. Choose **View > SSSEP Task**, click **Start SSSEP Task**, then press **Space**
   on the fullscreen ready screen.
5. Complete **Condition 1: both hands**. When prompted, move the left-hand TENS
   electrodes to the **right ankle**. Press **Space**, then read the confirmation
   and press **Y** to begin **Condition 2: right hand + right ankle**.

Both conditions run every time, in that order. Each freshly shuffles equal
numbers of its two participant prompts; consecutive repeats are allowed. The
handover waits for the administrator and has no countdown.

Trigger codes stay locked: `11`/`12` for both hands and `21`/`22` for hand/ankle.
Test mode sends no markers; choosing **No** at its warning returns home.
Its checkbox is remembered, but every test run still asks for confirmation.

Breaks appear between epochs within each condition. The top-center timer counts
down each epoch and break.
Breaks send no markers and do not supply a Gap/Break baseline for analysis.

The trigger code write is requested immediately after the participant prompt
frame's Qt buffer swap. Confirm physical screen and BioSemi timing before data collection.
Press **Escape** to abort. Keep the task log with the matching BioSemi
recording; an aborted run still needs review before analysis.

## Analyze recordings

1. In **File > Settings**, match the epoch duration and per-condition count to
   the recordings. Choose the plot electrode and optional **TENS Unit
   Stimulation Frequency (Hz)**, then save. The default is **26 Hz**; change it
   to match the TENS unit, or leave it blank if unknown.
2. Choose **View > Process Data**.
3. Choose the folder directly containing the `.bdf` files. Subfolders are not
   searched. Include one `.bdf` file per participant in the batch. The filename
   without `.bdf` becomes the participant ID in the results.
4. Choose a results folder outside the project.
5. Click **Process Data** and leave the program open until it finishes.
6. Click **View Output**.

Analysis includes all four trigger codes from both conditions. The optional
stimulation frequency must be inside the usable plot, filter, and FFT range
(3–50 Hz by default). The full FFT is saved even when frequency is blank.

Each analysis run gets a folder named with its date and 24-hour start time, such
as `2026-09-01 @ 10h23`. If another run starts in the same minute, its folder
ends in ` (2)`. Start with `batch_processing_summary.csv`. The run also contains:

- `participant_fft_amplitudes.csv`: every participant, trigger code, frequency, and
  usable electrode in one table.
- `group_fft_amplitudes.csv`: group mean amplitudes and the number of
  participants contributing to each electrode.
- One participant PNG per usable trigger code in that participant's `plots` folder.
- One group PNG per usable trigger code in `group_plots`.
- Each participant folder also keeps its event summary and processing report.

Recording analysis writes CSV files that you can open in Excel. Read warnings
even when a recording says `success`.

For each participant, all usable epochs with the same trigger code are averaged
together in the time domain before the FFT. Before that average, the analysis
removes the first and final 2.5 seconds from every complete epoch. With the default
15-second epoch, the FFT uses the middle 10 seconds. The group result then gives
each participant's amplitude spectrum equal weight, regardless of how many
usable epochs that participant had. Each PNG shows the electrode selected in
the launcher. Changing that selection does not change the full-electrode CSV
data.

If the selected electrode is unusable for one participant, that participant's
PNG is skipped and that participant does not contribute to the group curve for
that electrode. The group CSV reports how many participants contributed. A
Gap/Break baseline uses the same participants as the displayed trigger code's
spectrum and is omitted when a matching baseline is unavailable.

## Plot saved FFT results

Use this after processing when you want another electrode, a later ROI, or a
scalp map. The BDF files are not processed again.

1. Choose **View > Generate FFT Plots**. Results load automatically. If a parent
   results folder is selected, its most recently updated run is loaded. Use
   **Browse** to choose a different run; **Reload Results** refreshes it if needed.
2. Choose **Group average** or one participant, then choose the trigger code.
3. Check **TENS Unit Stimulation Frequency (Hz)**. It starts at the recorded
   frequency when available, otherwise 26 Hz. FFT plots mark this frequency with
   a dashed vertical line labeled **TENS Unit Stimulation Frequency**.
4. For an FFT plot, click **Choose Electrodes / Define ROI...**. In the larger
   dialog, click one or more electrodes, or start with an example ROI. Give
   your selection a name. **Save Custom ROI** keeps it for future sessions;
   choose it later under **Saved custom ROIs**. Click **Use ROI**, then
   **Create Electrode / ROI FFT Plot**.
5. For a scalp map, enter the **TENS Unit Stimulation Frequency (Hz)** and click
   **Create Scalp Map**.

The selection map shows the nose at the top and the participant's left on the
left. Greyed-out electrodes are unavailable in the loaded results. The four
example ROIs come from the FPVS website; choose ROIs for your SSSEP analysis
plan. A saved ROI may contain a single electrode or several. Missing electrodes
are listed when you load an ROI from another dataset; its saved definition stays
unchanged. **Cancel** keeps the previous plot selection, but does not undo an
explicit **Save Custom ROI**. Replacing a saved definition asks for confirmation.
Saved ROIs stay with this installation in `.sssep_rois.json`, not in individual
results folders.

The saved-results view requires the versioned `participant_fft_amplitudes.csv`
created by this workflow. If an older run reports missing provenance columns,
process its original BDF files once with the current version before plotting.
Older folders whose names begin with `run_` can still be loaded.

Each action saves a PNG directly in `<selected run>/saved_fft_plots`. Click
**View New Plot** to open that folder. Repeated filenames get ` (2)`, ` (3)`,
and so on; earlier plots are preserved. No extra CSV/Excel files or per-plot
subfolders are created. Keep the original participant and group FFT CSVs for
future plotting. Older plot folders and exports remain untouched.
If one selected ROI electrode is missing for a participant, the remaining
selected electrodes are averaged; that participant is omitted only when none
remain. The group curve gives each contributing participant equal weight.

Scalp maps use the nearest saved FFT bin and show the actual bin in the status
message. Missing participant/electrode values are omitted, so the participant
count can differ by electrode; the original `group_fft_amplitudes.csv` retains
these counts. Labels with no montage coordinates are listed in the status
message and left off the map; their values remain in the original FFT CSVs. No
missing value is replaced with zero.

Hemisphere comparisons and statistics remain outside this package.

For the processing method, see [FPVS parity](fpvs-parity.md). For code changes,
see the [code map](../architecture.md).
