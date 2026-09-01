# User guide

[Home](../README.md) · [Installation](installation.md) · [Help](troubleshooting.md)

Open the project in PyCharm, right-click `main.py`, and choose **Run**.

## Run a participant task

TENS stimulation is controlled separately. Set it up before starting the task.

1. Open the **Run Participant Task** tab.
2. Choose **Both hands** or **Right hand + right ankle**.
3. Enter the length of each cue epoch in seconds.
4. Enter an **even** total number of epochs. Each cue will appear the same
   number of times. The cues alternate; the first cue is randomized.
5. Connect and power the BioSemi trigger interface. The task always uses
   `COM3`; there is no port setting in the launcher.
6. Confirm the fixed cue codes shown in grey: both hands use `11` for left and
   `12` for right; hand/ankle uses `21` for right hand and `22` for right ankle.
   These codes cannot be changed in the launcher. Code `100` is reserved for
   the Gap/Break baseline.
7. Choose a folder outside the project for the CSV task log.
8. Click **Start Task**. Confirm that the BioSemi recording is running and is
   the one paired with this task log. Then press **Space** on the fullscreen
   ready screen.

Each cue marker is sent on the same screen refresh that displays its cue.
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
6. Enter the TENS frequency if you want it marked and summarized. It must be
   inside the usable plot, filter, and FFT range (3–50 Hz by default). Otherwise,
   leave this field blank; the full FFT is still saved.
7. Click **Process Data** and leave the program open until it finishes.
8. Click **View Output**.

Each analysis run gets a new `run_...` folder. Start with
`batch_processing_summary.csv`. The run also contains:

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
the time domain before the FFT. The group result then gives each participant's
amplitude spectrum equal weight, regardless of how many usable epochs that
participant had. Each PNG shows the electrode selected in the launcher.
Changing that selection does not change the full-electrode CSV data.

If the selected electrode is unusable for one participant, that participant's
PNG is skipped and that participant does not contribute to the group curve for
that electrode. The group CSV reports how many participants contributed. A
Gap/Break line uses the same participants as its cue line and is omitted when
a matching baseline is unavailable.

Legacy ROI mean columns remain in the CSVs for compatibility. New ROI analyses,
hemisphere comparisons, scalp maps, and statistics are performed outside this
package.

For the processing method, see [FPVS parity](fpvs-parity.md). For code changes,
see the [code map](../architecture.md).
