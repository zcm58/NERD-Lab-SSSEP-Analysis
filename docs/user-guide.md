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
   Choose whether to **Show countdown timer** and edit participant text if needed,
   then click **Save**. Saved settings return
   when you reopen the app; **Cancel** keeps your previous settings.
3. Connect the BioSemi trigger interface on its fixed `COM3` port and start
   recording. For a practice run without BioSemi, enable **Test mode (no
   BioSemi triggers)** in Settings and confirm **Yes** when starting.
4. Choose **View > SSSEP Task**, click **Start SSSEP Task**, then press **Space**
   on the fullscreen ready screen. A five-second message appears before the
   first prompt starts.
5. Complete **Condition 1: both hands**. When prompted, move the left-hand TENS
   electrodes to the **right ankle**. Press **Space**, then read the confirmation
   and press **Y** to begin **Condition 2: right hand + right ankle**.
6. The final thank-you screen closes automatically after five seconds.

Both conditions run every time, in that order. Each randomizes equal numbers of
its two participant prompts, with no more than two identical prompts in a row. The
handover waits for the administrator and has no countdown.

Trigger codes stay locked: `11`/`12` for both hands and `21`/`22` for hand/ankle.
Every attention epoch begins with its cue code and ends with code `100`; both are
recorded in the task log.
Test mode sends no markers; choosing **No** at its warning returns home.
Its checkbox is remembered, but every test run still asks for confirmation.

Breaks appear between epochs within each condition. Code `100` is synchronized
with the first visible break, handover, or closing frame. The next cue code ends
an ordinary break. Hiding the countdown does not change durations. A marked
handover or closing interval is not automatically a clean analysis baseline.
Process Data lists code `100` in the detected-event audit but excludes these
variable intervals from FFT baseline calculations.

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
For a legacy protocol with a separately measured, full-length Gap/Break baseline,
the overlay uses the same participants as the displayed trigger code's spectrum.
The current task's code-`100` intervals are delimiters and are not baseline FFTs.

## Plot saved FFT results

Use this after processing when you want another electrode, a later ROI, or a
scalp map. The BDF files are not processed again.

1. Choose **View > Generate FFT Plots**. Results load automatically. If a parent
   results folder is selected, its most recently updated run is loaded. Use
   **Browse** to choose a different run; **Reload Results** refreshes it if needed.
2. In **File > Settings > Regions of Interest**, click **Add ROI**. Select one
   or more electrodes, name the ROI, and click **Use ROI**. Repeat for each
   separate electrode or region. **Edit ROI** and **Remove** change the selected
   list entry. Every entry in this list gets its own FFT plot.
3. In Settings' **Analysis** tab, check **TENS Unit Stimulation Frequency (Hz)**
   (default 26 Hz). Click **Save** to apply and remember the ROI list and settings.
4. Choose **Group average** or one participant. Select a trigger code for one
   plot, or **All conditions** for every available attention trigger code.
5. Click **Create FFT Plot(s)** or **Create Scalp Map**. With All conditions
   selected, these become **Create All FFT Plots** and **Create All Scalp Maps**.

The selection map shows the nose at the top and the participant's left on the
left. You can define ROIs before loading results. For separate C3 and C4 plots,
add two entries containing one electrode each; selecting both electrodes in one
entry creates one averaged ROI. The four example ROIs come
from the FPVS website; choose ROIs for your SSSEP analysis plan. Plotting reports
missing electrodes without changing the saved definition. **Cancel** in Settings
keeps the previous ROI list and frequency, but does not undo an explicit **Save
Custom ROI** in the selector. That button stores a reusable definition; use
**Add ROI** to include it in this plotting list. Replacing a saved definition
asks for confirmation. Removing a plotting entry does not delete its reusable
definition. Reusable definitions stay in `.sssep_rois.json`; the plotting list and frequency
stay in `.sssep_gui_settings.json` with the other app settings.

FFT plots mark the Settings frequency with a dashed line labeled **TENS Unit
Stimulation Frequency**. If that setting is blank, each condition uses its
recorded frequency when available. Without either frequency, FFT plots have no
marker; scalp maps require a frequency in Settings. Changing this setting does
not recalculate or modify saved FFT values.

The saved-results view requires the versioned `participant_fft_amplitudes.csv`
created by this workflow. If an older run reports missing provenance columns,
process its original BDF files once with the current version before plotting.
Older folders whose names begin with `run_` can still be loaded.

Each ROI and condition saves a separate FFT PNG directly in
`<selected run>/saved_fft_plots`. FFT filenames use
`Condition_ROI_FFT_Amplitude.png`, for example
`BothHands_Left_Hand_Central_ROI_FFT_Amplitude.png`. Spaces become underscores;
the full condition name distinguishes the two right-hand prompts. Group or
participant identity remains in each plot's title. With **All conditions**, three ROIs normally
create 12 FFT plots: one per ROI for trigger codes 11, 12, 21, and 22. Scalp maps
use the whole scalp and still create only one map per trigger code, regardless
of the ROI list. All conditions excludes baselines and conditions missing from
the selected participant.
If one plot fails, the others continue. The results box identifies each ROI,
trigger code, contributing participants, missing electrodes, and any failures.
Click **View New Plot** to open that folder. Repeated filenames get ` (2)`, ` (3)`,
and so on; earlier plots are preserved. No extra CSV/Excel files or per-plot
subfolders are created. Keep the original participant and group FFT CSVs for
future plotting. Older plot folders and exports remain untouched.
If one selected ROI electrode is missing for a participant, the remaining
selected electrodes are averaged; that participant is omitted only when none
remain. The group curve gives each contributing participant equal weight.

Scalp maps use the nearest saved FFT bin and show the actual bin in the results
box. Their filenames keep the participant/group, trigger code, frequency, and
`scalp_map` suffix. Missing participant/electrode values are omitted, so the participant
count can differ by electrode; the original `group_fft_amplitudes.csv` retains
these counts. Labels with no montage coordinates are listed in the results
box and left off the map; their values remain in the original FFT CSVs. No
missing value is replaced with zero.

Hemisphere comparisons and statistics remain outside this package.

For the processing method, see [FPVS parity](fpvs-parity.md). For code changes,
see the [code map](../architecture.md).
