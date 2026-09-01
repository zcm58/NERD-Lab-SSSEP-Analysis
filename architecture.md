# Code map

[Home](README.md) · [Student user guide](docs/user-guide.md) · [Task behavior](docs/task-protocol.md) · [Processing method](docs/fpvs-parity.md)

Run `main.py` for both participant tasks and recording analysis. Keep this
entrypoint thin. The PySide6 launcher selects a workflow; PsychoPy is used only
by the fullscreen participant task. `sssep_bdf_batch_processor.py` remains a
compatibility wrapper.

## Find the right file

| If you want to change… | Start here |
| --- | --- |
| The two-tab launcher, task fields, folder choices, or progress messages | [gui.py](sssep_batch/gui.py) |
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
| Event codes and durations passed into analysis | [analysis/protocol.py](sssep_batch/analysis/protocol.py) |
| Existing summary values | [analysis/metrics.py](sssep_batch/analysis/metrics.py) |
| Participant and group single-electrode graphs | [analysis/plotting.py](sssep_batch/analysis/plotting.py) |
| Analysis summary CSVs, reports, or error files | [outputs.py](sssep_batch/outputs.py) |

[models.py](sssep_batch/models.py) contains analysis data containers.
[logging_utils.py](sssep_batch/logging_utils.py) supports analysis logs.

## How the parts connect

Participant task:

`entrypoint → gui → experiment settings → schedule → serial preflight → PsychoPy runner → task CSV`

The runner opens the fixed `COM3` connection before participant screens. After
Space starts the task, it draws each cue and schedules its unique `1..255`
marker with PsychoPy `callOnFlip`, so the one-byte serial write occurs on the
cue's visible display flip. Escape aborts. TENS control stays outside this
program. See [task-protocol.md](docs/task-protocol.md) for the runtime contract.

Recording analysis:

`entrypoint → gui task fields → analysis protocol → batch → pipeline → preprocessing / events / FFT → participant outputs → group outputs`

The numerical order is load/montage → EXG reference/drop → filter → resample
→ interpolate → average reference → recorded events → SSSEP epochs → trial
mean within each participant and cue → per-electrode amplitude FFT. After all
files finish, the batch averages participant amplitude spectra with equal
participant weight. It writes consolidated participant and group FFT CSVs plus
one selected-electrode PNG per cue at each level.

`pipeline.py` coordinates analysis stages; low-level work belongs in the
relevant module. Legacy ROI mean fields remain for output compatibility. New
ROI comparisons, hemisphere comparisons, scalp topographies, and statistics
are intentionally left to external analysis.

## Keep these behaviors

- Keep one launcher with separate task and analysis tabs.
- Keep PsychoPy and live serial output inside `experiment/`, separate from BDF
  analysis.
- Keep `COM3` fixed and absent from the GUI. Open and check it before participant
  cues; never continue after a trigger failure.
- Send each cue's marker on the same display flip that reveals that cue.
- Require an even epoch count and alternate the two cues from a randomized
  starting cue.
- Pass the visible condition, duration, epoch count, and that condition's fixed
  cue codes into each analysis batch; do not fall back to unrelated settings.
- Preserve the validated FPVS analysis method unless a change is authorized.
- Treat one BDF as one participant. Average all same-cue epochs in the time
  domain before that participant's FFT; never average epoch FFT amplitudes.
- At the group level, average participant amplitude spectra equally rather than
  weighting participants by their usable epoch counts.
- Overlay a group baseline only from the same selected-electrode participants
  as that cue; omit it when a matching baseline is unavailable.
- Keep full per-electrode data in `participant_fft_amplitudes.csv` and
  `group_fft_amplitudes.csv`. The launcher's electrode selection changes PNGs
  only (`PLOT_CHANNEL` supplies its default).
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

Use Python 3.11 and the existing dependency pins. Synthetic tests do not prove
hardware timing. Before data collection, verify the sent codes and timing on a
real BioSemi Status channel. For numerical changes, also use the optional
[FPVS reference checks](docs/fpvs-parity.md#verification-and-reproducibility)
and a known recording when available.
