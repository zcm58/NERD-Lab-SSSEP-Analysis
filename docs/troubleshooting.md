# Troubleshooting

[Home](../README.md) · [Installation](installation.md) · [User guide](user-guide.md)

## The program will not start

Check that PyCharm uses this project's `.venv` and Python 3.13.
If a library is missing, open PyCharm's **Terminal** in the project folder and run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

If `.venv\Scripts\python.exe` cannot be found, finish the
[environment setup](installation.md) first. Keep the package versions unchanged.

## Processing has a problem

| Problem | What to do |
| --- | --- |
| No `.bdf` files found | Choose the folder containing the files themselves, not its parent. |
| Cannot save results | Choose a folder you can write to, such as Documents; check that the drive is connected. |
| Computer is slow | Close other large programs. For the next run, lower `BATCH_WORKERS` to `1` or `2` in `sssep_batch/config.py`. |
| Window will not close | Wait for processing to finish. There is no cancel button; force-stopping can leave incomplete results. |
| Only five graphs appear | This is the default plot limit. To change it, follow [Change settings](user-guide.md#change-settings). |
| Results are in a new folder | This is intentional. Use **View Output** to open the latest run. |
| Saved folders are wrong | Choose the correct folders and leave **Save folders for next time** checked. |
| An edit caused an error | Undo the last change, save, close the launcher, and run it again. |

## A recording failed or has warnings

1. Click **View Output** and open `batch_processing_summary.csv`.
2. Find the recording's row. Read its `error` and `error_file` columns.
3. Open the listed `ERROR.txt`. If none exists, read the batch log
   `sssep_batch_processing.log`.

For completed recordings, read `*_processing_report.txt`. A `success` status
does not mean every condition or processing step was complete. Missing trials,
unresolved bad electrodes, and missing baseline results need review.

If you need help, give your supervisor the error message and report from that
run. Do not upload participant recordings to this repository.

Old power/Welch results use a different method. See
[method details](fpvs-parity.md) before comparing them with new amplitudes.
