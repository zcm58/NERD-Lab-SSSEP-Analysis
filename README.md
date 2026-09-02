# NERD Lab SSSEP Task and Analysis

Run the SSSEP attention task and analyze its BioSemi `.bdf` recordings from one
simple program. The task shows fullscreen body-part prompts and sends trigger
codes to BioSemi. For each participant, the analysis averages all usable epochs
with the same trigger code before the FFT. The default epoch is 15 seconds;
the FFT uses only its middle 10 seconds after removing 2.5 seconds from each end. The program
creates one graph per trigger code for the selected electrode, then creates
the same graphs for the group.

TENS stimulation is controlled outside this program.

## Start here

1. **First time?** Follow the [installation guide](docs/installation.md).
2. **Running the study or analysis?** Follow the [user guide](docs/user-guide.md).
3. **Something went wrong?** See [troubleshooting](docs/troubleshooting.md).

Once set up, right-click [main.py](main.py) in PyCharm and choose **Run**. The
launcher opens the task home. Use **View** to switch workflows:

- **SSSEP Task** has one **Start SSSEP Task** button. Each experiment
  runs both hands first, then right hand/right ankle after an administrator
  handover and confirmation. Participant prompts are balanced and shuffled,
  with breaks and countdowns. BioSemi markers use fixed `COM3`; confirmed test
  mode skips them.
- **Process Data** processes saved `.bdf` files and creates FFT results.
- **Generate FFT Plots** reopens an earlier FFT CSV to make participant/group
  electrode or ROI plots and scalp maps without processing the BDF files again.

Edit session settings, participant text, and analysis options under **File >
Settings**. Click **Save** to keep changes after closing the app. The default
is 10 epochs per condition, or 20 overall. Analysis uses
both conditions' fixed codes; match the duration and count to your recordings.

Use one `.bdf` file per participant in an analysis batch. Each run saves one
consolidated participant FFT CSV and one group FFT CSV, both readable in Excel.
Later plot exports save only PNG images directly in `saved_fft_plots`.
`participant_fft_amplitudes.csv` is the reusable source for later plots.
It keeps the pipeline version and settings needed to validate a later reload.
**Generate FFT Plots** loads the selected results automatically. The TENS
frequency defaults to **26 Hz** and is marked by a labeled dashed line on FFT plots.

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
