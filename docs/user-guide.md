# User guide

[Home](../README.md) · [Installation](installation.md) · [Help](troubleshooting.md)

Open the project in PyCharm, right-click `sssep_bdf_batch_processor.py`, and
choose **Run**.

## Run a participant task

TENS stimulation is controlled separately. Set it up before starting the task.

1. Open the **Run Participant Task** tab.
2. Choose **Both hands** or **Right hand + right ankle**.
3. Enter the length of each cue epoch in seconds.
4. Enter an **even** total number of epochs. Each cue will appear the same
   number of times. The cues alternate; the first cue is randomized.
5. Check the serial port. The default is `COM3`.
6. Give each cue a different trigger code from `1` to `255`. Do not use `100`;
   it is reserved for the Gap/Break baseline.
7. Choose a folder outside the project for the CSV task log.
8. Click **Start Task**. Confirm that the BioSemi recording is running and is
   the one paired with this task log. Then press **Space** on the fullscreen
   ready screen.

Each cue marker is sent on the same screen refresh that displays its cue.
Press **Escape** to abort. Keep the task log with the matching BioSemi
recording; an aborted run still needs review before analysis.

## Analyze recordings

1. In **Run Participant Task**, set the condition, duration, epoch count, and
   trigger codes used for these recordings.
2. Open **Analyze Recordings**.
3. Choose the folder directly containing the `.bdf` files. Subfolders are not
   searched.
4. Choose a results folder outside the project.
5. Choose the electrode for the PNG plots.
6. Enter the TENS frequency if you want it marked and summarized. It must be
   inside the usable plot, filter, and FFT range (3–50 Hz by default). Otherwise,
   leave this field blank; the full FFT is still saved.
7. Click **Process Data** and leave the program open until it finishes.
8. Click **View Output**.

Each analysis run gets a new `run_...` folder. Start with
`batch_processing_summary.csv`. Each recording also has an event summary,
processing report, FFT CSV files, and PNG plots. Read warnings even when the
recording says `success`.

FFT CSVs contain all usable electrodes. Each PNG shows the electrode selected
in the launcher. Changing that selection does not change the FFT or CSV data.
If that electrode is unusable in one recording, that recording still gets FFT
CSVs and summaries, but its PNGs are skipped.

Legacy ROI mean columns remain in the CSVs for compatibility. New ROI analyses,
hemisphere comparisons, scalp maps, and statistics are performed outside this
package.

For the processing method, see [FPVS parity](fpvs-parity.md). For code changes,
see the [code map](../architecture.md).
