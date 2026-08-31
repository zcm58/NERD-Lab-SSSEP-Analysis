# NERD Lab SSSEP Analysis

Analyze BioSemi `.bdf` EEG recordings from the SSSEP study. The program creates
tables and graphs showing the strength of responses at the stimulation frequencies.

## Start here

1. **First time?** Follow the [installation guide](docs/installation.md).
2. **Ready to run?** Follow the [user guide](docs/user-guide.md).
3. **Something went wrong?** See [troubleshooting](docs/troubleshooting.md).

Once set up, right-click [sssep_bdf_batch_processor.py](sssep_bdf_batch_processor.py)
in PyCharm and choose **Run**. You do not need to edit code for a normal run.

## Where things live

| File or folder | What you use it for |
| --- | --- |
| [sssep_bdf_batch_processor.py](sssep_bdf_batch_processor.py) | **Run this file** to open the program. |
| [sssep_batch/config.py](sssep_batch/config.py) | **Edit settings here.** Everyday options are at the top. |
| [docs/](docs/) | Setup, user guide, help, and method details. |
| [sssep_batch/](sssep_batch/) | The processing code, grouped by job. |
| [tests/](tests/) | Checks to run after changing code. |
| [requirements.txt](requirements.txt) | Libraries installed during setup; keep the listed versions. |

Keep EEG data and results **outside this project folder**. Each run saves
results in a new folder, so earlier runs stay intact.

## Editing the project

For settings, start with [Change settings](docs/user-guide.md#change-settings).
For code changes, use the [code map and testing steps](architecture.md).
`AGENTS.md` files contain instructions for coding assistants; students do not
need them for normal use.

The processing method follows the FPVS Toolbox while keeping SSSEP trial
timing. [Method and verification details](docs/fpvs-parity.md) are separate
from the student guides.
