# Code map

[Home](README.md) · [Student user guide](docs/user-guide.md) · [Task behavior](docs/task-protocol.md) · [Processing method](docs/fpvs-parity.md)

Run `sssep_bdf_batch_processor.py` for both participant tasks and recording
analysis. Keep this entrypoint thin. The PySide6 launcher selects a workflow;
PsychoPy is used only by the fullscreen participant task.

## Find the right file

| If you want to change… | Start here |
| --- | --- |
| The two-tab launcher, task fields, folder choices, or progress messages | [gui.py](sssep_batch/gui.py) |
| Analysis defaults and advanced processing settings | [config.py](sssep_batch/config.py) |
| Task settings and event records | [experiment/models.py](sssep_batch/experiment/models.py) |
| Balanced alternating cue order | [experiment/schedule.py](sssep_batch/experiment/schedule.py) |
| Fullscreen prompts, cue timing, or task CSV log | [experiment/runner.py](sssep_batch/experiment/runner.py) |
| COM-port connection or one-byte BioSemi markers | [experiment/triggers.py](sssep_batch/experiment/triggers.py) |
| Finding BDF files, workers, or analysis run folders | [batch.py](sssep_batch/batch.py) |
| The processing order for one BDF recording | [pipeline.py](sssep_batch/pipeline.py) |
| Reading a BDF file | [loading.py](sssep_batch/loading.py) |
| Electrode types, montage, or references | [preprocess/channels.py](sssep_batch/preprocess/channels.py) |
| Filtering or resampling | [preprocess/filtering.py](sssep_batch/preprocess/filtering.py) |
| Bad-channel detection or interpolation | [preprocess/bad_channels.py](sssep_batch/preprocess/bad_channels.py) |
| Recorded trigger detection or trial windows | [events/](sssep_batch/events/) |
| FFT calculation | [analysis/spectra.py](sssep_batch/analysis/spectra.py) |
| Event codes and durations passed into analysis | [analysis/protocol.py](sssep_batch/analysis/protocol.py) |
| Existing summary values | [analysis/metrics.py](sssep_batch/analysis/metrics.py) |
| Single-electrode graphs or full FFT tables | [analysis/plotting.py](sssep_batch/analysis/plotting.py) |
| Analysis summary CSVs, reports, or error files | [outputs.py](sssep_batch/outputs.py) |

[models.py](sssep_batch/models.py) contains analysis data containers.
[logging_utils.py](sssep_batch/logging_utils.py) supports analysis logs.

## How the parts connect

Participant task:

`entrypoint → gui → experiment settings → schedule → serial preflight → PsychoPy runner → task CSV`

The runner opens the configured serial port before participant screens. After
Space starts the task, it draws each cue and schedules its unique `1..255`
marker with PsychoPy `callOnFlip`, so the one-byte serial write occurs on the
cue's visible display flip. Escape aborts. TENS control stays outside this
program. See [task-protocol.md](docs/task-protocol.md) for the runtime contract.

Recording analysis:

`entrypoint → gui task fields → analysis protocol → batch → pipeline → preprocessing / events / FFT → outputs`

The numerical order is load/montage → EXG reference/drop → filter → resample
→ interpolate → average reference → recorded events → SSSEP epochs → trial
mean → per-electrode amplitude FFT → selected-electrode PNG and full FFT CSV.

`pipeline.py` coordinates analysis stages; low-level work belongs in the
relevant module. Legacy ROI mean fields remain for output compatibility. New
ROI comparisons, hemisphere comparisons, scalp topographies, and statistics
are intentionally left to external analysis.

## Keep these behaviors

- Keep one launcher with separate task and analysis tabs.
- Keep PsychoPy and live serial output inside `experiment/`, separate from BDF
  analysis.
- Open and check the serial port before participant cues; never continue after
  a trigger failure.
- Send each cue's marker on the same display flip that reveals that cue.
- Require an even epoch count and alternate the two cues from a randomized
  starting cue.
- Pass the visible condition, duration, epoch count, and cue codes into each
  analysis batch; do not fall back to unrelated event settings.
- Preserve the validated FPVS analysis method unless a change is authorized.
- Keep full per-electrode FFT CSVs; the launcher's electrode selection changes
  PNGs only (`PLOT_CHANNEL` supplies its default). Skip a PNG without failing
  the recording when its selected electrode is unavailable.
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
