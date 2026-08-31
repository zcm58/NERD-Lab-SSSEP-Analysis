# User guide

[Home](../README.md) · [Installation](installation.md) · [Help](troubleshooting.md)

## Run an analysis

1. Open the project in PyCharm.
2. Right-click `sssep_bdf_batch_processor.py` and choose **Run**.
3. In **Input folder**, choose the folder directly containing your `.bdf` files.
   Files inside subfolders are not included.
4. In **Output folder**, choose a results folder outside this project.
5. Click **Process Data**. Leave PyCharm and the launcher open until it finishes.
6. Click **View Output**.

Leave **Save folders for next time** checked to remember your choices.
Each run gets a new `run_...` folder; old results are kept.

## Read the results

CSV files are tables you can open in Excel. PNG files are graphs.

| Open this | What it tells you |
| --- | --- |
| `batch_processing_summary.csv` | Which recordings succeeded or failed. Start here. |
| A recording's `*_sssep_event_summary.csv` | Results for each condition, including trial counts and amplitudes. |
| `*_processing_report.txt` | Settings, warnings, and processing details. |
| `plots/` inside a recording's folder | Amplitude graphs and full FFT tables, grouped by condition. |
| `ERROR.txt`, if present | Why that recording failed. |

Graphs show FFT amplitude in microvolts (µV). By default, each recording gets
at most five graphs; other usable conditions still get results and FFT tables.

Before using results:

- Read warnings even when a recording says `success`.
- `epoch_count_ok = False` means the trial count differs from the expected count.
  Ask your supervisor about missing trials, warnings, or blank baseline results.
- Do not combine these amplitudes with results from the old power/Welch method.

## Change settings

1. Wait for processing to finish, then close the launcher.
2. Open [sssep_batch/config.py](../sssep_batch/config.py).
3. Change an option in **Everyday options**. For example, to allow 15 graphs
   per recording, set:

   ```python
   MAX_INDIVIDUAL_PLOTS = 15
   ```

4. Save the file, then run `sssep_bdf_batch_processor.py` again.

`BATCH_WORKERS` controls how many recordings run at once. Lower it to `1` or
`2` if the computer struggles. Keep spelling, quotation marks, and brackets
unchanged when editing values.

Change experiment or advanced processing settings only as agreed with your
supervisor: these can change the scientific results.

For changes beyond settings, see the [code map](../architecture.md).
