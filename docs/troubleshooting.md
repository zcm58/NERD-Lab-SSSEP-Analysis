# Troubleshooting

[Home](../README.md) · [Installation](installation.md) · [User guide](user-guide.md)

## The program will not start

Check the Python version in PyCharm's Terminal:

```powershell
.\.venv\Scripts\python.exe --version
```

It must say `Python 3.13`. If it shows another version, rebuild the environment
and install every required library with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Recreate
```

If it already shows Python 3.13, run the same command without `-Recreate`.

## Participant task problems

| Problem | What to do |
| --- | --- |
| `COM3` is missing | Check that the BioSemi trigger interface is connected and powered. If Windows assigned another port, ask the lab supervisor to reassign it to `COM3`; the launcher cannot change ports. |
| `COM3` is busy | Close any program using `COM3`, then restart the launcher. Do not run the task without a working trigger connection. |
| Fullscreen opens on the wrong display | Make the participant display the Windows primary display before starting, then reopen the launcher. |
| The ready screen does not continue | Click the fullscreen task window and press **Space**. |
| I need to stop the task | Press **Escape**. Keep the CSV log and record that the run was aborted. |
| Cues or markers seem late | Stop using that session. Save its log and ask the supervisor to check the display and BioSemi Status channel. |

The software requests a one-byte marker from the callback for the cue's Qt
buffer swap. This does not measure physical screen onset or marker arrival.
Confirm timing with a photodiode and the BioSemi Status channel before collecting
study data.

## Analysis problems

| Problem | What to do |
| --- | --- |
| No `.bdf` files found | Choose the folder containing the files themselves, not its parent. |
| Cannot save results | Choose a writable folder such as Documents and check that the drive is connected. |
| Computer is slow | Close other large programs. Lower `BATCH_WORKERS` in `sssep_batch/config.py` for the next run. |
| The requested plot electrode is missing | The consolidated FFT CSVs and summaries are still saved, but that participant has no PNG for the missing electrode. The group plot uses participants who have that electrode and the group CSV reports their count. |
| Only some graphs appear | Check the participant event summary and processing report. For group plot errors, open `GROUP_PLOT_ERRORS.txt` in the run folder. |
| A recording failed | Open `batch_processing_summary.csv`, then read the listed `ERROR.txt` or the batch log. |
| Group results failed | Open `GROUP_OUTPUT_ERROR.txt`. Participant folders and any CSVs completed before the error are preserved. |

Do not upload participant recordings to this repository. Give your supervisor
the task log, processing report, and exact error message when asking for help.
