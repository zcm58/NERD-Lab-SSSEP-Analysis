# NERD Lab SSSEP Task and Analysis

Run the SSSEP attention task and analyze its BioSemi `.bdf` recordings from one
simple program. The task shows fullscreen body-part cues and sends cue markers
to BioSemi. For each participant, the analysis averages all usable epochs with
the same cue before the FFT. It creates one graph per cue for the selected
electrode, then creates the same cue-level graphs for the group.

TENS stimulation is controlled outside this program.

## Start here

1. **First time?** Follow the [installation guide](docs/installation.md).
2. **Running the study or analysis?** Follow the [user guide](docs/user-guide.md).
3. **Something went wrong?** See [troubleshooting](docs/troubleshooting.md).

Once set up, right-click [main.py](main.py) in PyCharm and choose **Run**. The
launcher has two tabs:

- **Run Participant Task** presents the cues, sends BioSemi markers through the
  selected serial port, and saves a task log.
- **Analyze Recordings** processes saved `.bdf` files and creates FFT results.

The analysis uses the condition, epoch duration, epoch count, and trigger codes
currently shown in the participant-task tab. Set those fields to match the
recordings before processing them.

Use one `.bdf` file per participant in an analysis batch. Each run saves one
consolidated participant FFT CSV and one group FFT CSV. These are CSV files that
can be opened in Excel; the program does not create Excel workbooks.

## Where things live

| File or folder | What you use it for |
| --- | --- |
| [main.py](main.py) | **Run this file** to open the program. |
| [sssep_bdf_batch_processor.py](sssep_bdf_batch_processor.py) | Compatibility launcher for older PyCharm setups. |
| [sssep_batch/config.py](sssep_batch/config.py) | Advanced analysis settings and launcher defaults. |
| [docs/](docs/) | Setup, user guide, help, and method details. |
| [sssep_batch/](sssep_batch/) | Task and analysis code, grouped by job. |
| [tests/](tests/) | Checks to run after changing code. |

Keep EEG data, task logs, and results **outside this project folder**. Analysis
runs use new result folders so earlier results stay intact.

For code changes, use the [code map and testing steps](architecture.md).
The analysis method follows the FPVS Toolbox while keeping SSSEP trial timing;
see [method and verification details](docs/fpvs-parity.md).
