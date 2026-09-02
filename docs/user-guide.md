# User guide

[Home](../README.md) · [Installation](installation.md) · [Help](troubleshooting.md)

Open the project in PyCharm, right-click `main.py`, and choose **Run**.
The three tabs group related settings into panels. Scroll within a tab on a
smaller screen; actions and status stay at the bottom.

## Run a participant task

TENS stimulation is controlled separately. Set it up before starting the task.

1. Open the **Run Participant Task** tab.
2. Choose **Both hands** or **Right hand + right ankle**.
3. Set the cue duration (15 seconds by default) and break duration (10 seconds
   by default). Edit the cue and break text if needed.
4. Enter an **even** total number of epochs. Each cue will appear the same
   number of times in a freshly shuffled order. Consecutive repeats are allowed.
5. For a normal run, connect and power the BioSemi trigger interface. The task
   always uses `COM3`; there is no port setting in the launcher.
   - To test only the fullscreen prompts, check **Test mode (no BioSemi
     triggers)**. Click **Yes** in the warning to continue without COM3, or
     **No** to return to the setup screen.
6. Confirm the fixed cue codes shown in grey: both hands use `11` for left and
   `12` for right; hand/ankle uses `21` for right hand and `22` for right ankle.
   These codes cannot be changed in the launcher. Code `100` is reserved for
   the Gap/Break baseline.
7. Choose a folder outside the project for the CSV task log.
8. Click **Start Task**. Confirm that the BioSemi recording is running and is
   the one paired with this task log. Then press **Space** on the fullscreen
   ready screen.

Breaks appear between cues, including repeated cues, but not before the first
or after the last cue. The top-center timer counts down each cue and break.
Breaks send no markers and do not supply a Gap/Break baseline for analysis.

The marker write is requested immediately after Qt reports the cue frame's
buffer swap. Confirm physical screen and BioSemi timing before data collection.
Press **Escape** to abort. Keep the task log with the matching BioSemi
recording; an aborted run still needs review before analysis.

## Analyze recordings

1. In **Run Participant Task**, set the condition, duration, and epoch count
   used for these recordings. The selected condition supplies its fixed codes.
2. Open **Analyze Recordings**.
3. Choose the folder directly containing the `.bdf` files. Subfolders are not
   searched. Include one `.bdf` file per participant in the batch. The filename
   without `.bdf` becomes the participant ID in the results.
4. Choose a results folder outside the project.
5. Choose the electrode for the PNG plots.
6. Enter the **TENS Unit Stimulation Frequency (Hz)** if you want it marked and
   summarized. It must be inside the usable plot, filter, and FFT range (3–50 Hz
   by default). Otherwise, leave this field blank; the full FFT is still saved.
7. Click **Process Data** and leave the program open until it finishes.
8. Click **View Output**.

Each analysis run gets a folder named with its date and 24-hour start time, such
as `2026-09-01 @ 10h23`. If another run starts in the same minute, its folder
ends in ` (2)`. Start with `batch_processing_summary.csv`. The run also contains:

- `participant_fft_amplitudes.csv`: every participant, cue, frequency, and
  usable electrode in one table.
- `group_fft_amplitudes.csv`: group mean amplitudes and the number of
  participants contributing to each electrode.
- One participant PNG per usable cue in that participant's `plots` folder.
- One group PNG per usable cue in `group_plots`.
- Each participant folder also keeps its event summary and processing report.

The program writes CSV files, not Excel workbooks. You can still open the CSVs
in Excel. Read warnings even when a recording says `success`.

For each participant and cue, all usable cue epochs are averaged together in
the time domain before the FFT. Before that average, the analysis removes the
first and final 2.5 seconds from every complete epoch. With the default
15-second epoch, the FFT uses the middle 10 seconds. The group result then gives
each participant's amplitude spectrum equal weight, regardless of how many
usable epochs that participant had. Each PNG shows the electrode selected in
the launcher. Changing that selection does not change the full-electrode CSV
data.

If the selected electrode is unusable for one participant, that participant's
PNG is skipped and that participant does not contribute to the group curve for
that electrode. The group CSV reports how many participants contributed. A
Gap/Break line uses the same participants as its cue line and is omitted when
a matching baseline is unavailable.

## Plot saved FFT results

Use this after processing when you want another electrode, a later ROI, or a
scalp map. The BDF files are not processed again.

1. Open **Plot Saved FFT** and choose the earlier analysis results folder.
2. Click **Load Results**.
3. Choose **Group average** or one participant, then choose the cue or event.
4. For an FFT plot, select one electrode or click several electrodes to average
   as an ROI. Enter a short name and click **Create Electrode / ROI FFT Plot**.
5. For a scalp map, enter the **TENS Unit Stimulation Frequency (Hz)** and click
   **Create Scalp Map**.

The saved-results tab requires the versioned `participant_fft_amplitudes.csv`
created by this workflow. If an older run reports missing provenance columns,
process its original BDF files once with the current version before plotting.
Older folders whose names begin with `run_` can still be loaded.

Each action creates `<selected run>/saved_fft_plots/plot_...`. Click **View New
Plot** to open the newest folder. It contains the PNG and CSV source values. An
ROI also saves each participant's curve and the electrodes that contributed to
it. If one selected ROI electrode is missing for a participant, the remaining
selected electrodes are averaged; that participant is omitted only when none
remain. The group curve gives each contributing participant equal weight.

Scalp maps use the nearest saved FFT bin and show the actual bin in the status
message. Missing participant/electrode values are omitted, so the participant
count can differ by electrode. The source CSV reports each count. Labels with
no montage coordinates are listed and left off the map. No missing value is
replaced with zero.

Hemisphere comparisons and statistics remain outside this package.

For the processing method, see [FPVS parity](fpvs-parity.md). For code changes,
see the [code map](../architecture.md).
