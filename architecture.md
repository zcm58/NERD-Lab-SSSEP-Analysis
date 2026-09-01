# Code map

[Home](README.md) · [Student user guide](docs/user-guide.md) · [Task behavior](docs/task-protocol.md) · [Processing method](docs/fpvs-parity.md)

Run `main.py` for participant tasks, recording analysis, and saved-result
plotting. Keep this entrypoint thin. The PySide6 launcher selects a workflow;
PySide6 also presents the fullscreen participant task.
`sssep_bdf_batch_processor.py` remains a compatibility wrapper.

## Find the right file

| If you want to change… | Start here |
| --- | --- |
| Python environment or pinned libraries | [install.ps1](install.ps1) and [requirements.txt](requirements.txt) |
| Main launcher, participant-task fields, BDF fields, or progress messages | [gui.py](sssep_batch/gui.py) |
| Saved-results tab, its controls, or its background workers | [saved_plots_gui.py](sssep_batch/saved_plots_gui.py) |
| Analysis defaults and advanced processing settings | [config.py](sssep_batch/config.py) |
| Task settings and event records | [experiment/models.py](sssep_batch/experiment/models.py) |
| Balanced alternating cue order | [experiment/schedule.py](sssep_batch/experiment/schedule.py) |
| Fullscreen prompts, cue timing, or task CSV log | [experiment/runner.py](sssep_batch/experiment/runner.py) |
| Fixed COM3 connection or one-byte BioSemi markers | [experiment/triggers.py](sssep_batch/experiment/triggers.py) |
| Finding BDF files, workers, or analysis run folders | [batch.py](sssep_batch/batch.py) |
| The processing order for one BDF recording | [pipeline.py](sssep_batch/pipeline.py) |
| Reading a BDF file | [loading.py](sssep_batch/loading.py) |
| Electrode types, montage, or references | [preprocess/channels.py](sssep_batch/preprocess/channels.py) |
| Filtering or resampling | [preprocess/filtering.py](sssep_batch/preprocess/filtering.py) |
| Bad-channel detection or interpolation | [preprocess/bad_channels.py](sssep_batch/preprocess/bad_channels.py) |
| Recorded trigger detection or trial windows | [events/](sssep_batch/events/) |
| FFT calculation | [analysis/spectra.py](sssep_batch/analysis/spectra.py) |
| Consolidated participant tables and equal-participant group averages | [analysis/grouping.py](sssep_batch/analysis/grouping.py) |
| Reloading saved FFT CSVs, later ROI averaging, and scalp-map values | [analysis/saved_fft.py](sssep_batch/analysis/saved_fft.py) |
| Writing later FFT plots and their exact source-data CSVs | [analysis/saved_outputs.py](sssep_batch/analysis/saved_outputs.py) |
| Event codes and durations passed into analysis | [analysis/protocol.py](sssep_batch/analysis/protocol.py) |
| Existing summary values | [analysis/metrics.py](sssep_batch/analysis/metrics.py) |
| Participant/group electrode or ROI graphs and scalp maps | [analysis/plotting.py](sssep_batch/analysis/plotting.py) |
| Analysis summary CSVs, reports, or error files | [outputs.py](sssep_batch/outputs.py) |

[models.py](sssep_batch/models.py) contains analysis data containers.
[logging_utils.py](sssep_batch/logging_utils.py) supports analysis logs.

## How the parts connect

Participant task:

`entrypoint → gui → experiment settings → schedule → serial preflight → PySide6 presenter → task CSV`

The runner opens the fixed `COM3` connection before participant screens. After
Space starts the task, a main-thread `QOpenGLWindow` draws each cue. Its
matching `frameSwapped` callback immediately requests the cue's unique
`1..255` serial marker after Qt completes that frame's buffer swap. A Qt
`PreciseTimer` requests the next cue at the configured software deadline.
Escape aborts. TENS control stays outside this program. See
[task-protocol.md](docs/task-protocol.md) for the runtime contract.

Recording analysis:

`entrypoint → gui task fields → analysis protocol → batch → pipeline → preprocessing / events / FFT → participant outputs → group outputs`

The numerical order is load/montage → EXG reference/drop → filter → resample
→ interpolate → average reference → recorded events → complete SSSEP epochs
→ remove 2.5 seconds from each epoch end → trial mean within each participant
and cue → per-electrode amplitude FFT. The default 15-second epoch therefore
uses its middle 10 seconds for the FFT. After all files finish, the batch
averages participant amplitude spectra with equal participant weight. It writes
consolidated participant and group FFT CSVs plus one selected-electrode PNG per
cue at each level.

Saved-result plotting is separate:

`saved participant FFT CSV → strict reload → participant/electrode/event selection → later ROI mean or scalp-bin values → PNG plus plotted-value CSV`

Later ROI means average electrodes within participant before the equal-weight
group mean. Their source exports retain every participant curve and its actual
electrode membership. Scalp maps use finite electrodes with coordinates in the
saved `standard_1005` montage; missing or unmapped electrodes are not replaced
with zero. Hemisphere comparisons and statistics remain external.

## Keep these behaviors

- Keep one launcher with separate participant-task, BDF-processing, and saved
  FFT plotting tabs.
- Keep saved-result plotting separate from BDF processing so one FFT calculation
  can support many later plots.
- Keep PySide6 presentation and live serial output inside `experiment/`,
  separate from BDF analysis.
- Keep `COM3` fixed and absent from the GUI. Open and check it before participant
  cues; never continue after a trigger failure.
- Request each cue's marker immediately from the callback for its matching Qt
  buffer swap.
- Require an even epoch count and alternate the two cues from a randomized
  starting cue.
- Pass the visible condition, duration, epoch count, and that condition's fixed
  cue codes into each analysis batch; do not fall back to unrelated settings.
- Preserve the validated FPVS analysis method unless a change is authorized.
- Require a complete configured epoch, then remove 2.5 seconds from its start
  and end before cue averaging and FFT calculation. This SSSEP analysis window
  is separate from FPVS's visual-oddball marker crop.
- Treat one BDF as one participant. Average all same-cue epochs in the time
  domain before that participant's FFT; never average epoch FFT amplitudes.
- At the group level, average participant amplitude spectra equally rather than
  weighting participants by their usable epoch counts.
- Overlay a group baseline only from the same selected-electrode participants
  as that cue; omit it when a matching baseline is unavailable.
- Keep full per-electrode data in `participant_fft_amplitudes.csv` and
  `group_fft_amplitudes.csv`. The launcher's electrode selection changes PNGs
  only (`PLOT_CHANNEL` supplies its default).
- Keep the FFT export schema version, FPVS reference commit, montage, actual
  sampling rate, extracted epoch duration, crop durations, FFT analysis-window
  duration, and saved plot range with every reusable spectrum.
- Validate the complete saved participant table before plotting. Use its
  participant identities for later ROI/group calculations rather than pooling
  rows or relying on the already-averaged group CSV.
- Create one participant PNG and one group PNG per usable cue. If the selected
  electrode is unavailable, skip only the affected plot and report the actual
  participant count in group outputs.
- Keep data outside the repo and each analysis batch in a fresh run folder.
- Parallelize across recordings; cap native threads at one per worker.
- Keep warnings and failures visible; do not add silent fallbacks.

## After changing code

1. Change one thing at a time and inspect the diff.
2. Install test libraries once, then run:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
   .\.venv\Scripts\python.exe -m pytest -q
   ```

3. Run the PyCharm entrypoint and check the affected tab.
4. Update the relevant guide when a setting, output, or workflow changes.

Use Python 3.13 and the existing dependency pins. Synthetic tests do not prove
hardware timing. Before data collection, verify the sent codes and timing on a
real BioSemi Status channel. For numerical changes, also use the optional
[FPVS reference checks](docs/fpvs-parity.md#verification-and-reproducibility)
and a known recording when available.
