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
| Main launcher, File/View menus, BDF fields, or progress messages | [gui.py](sssep_batch/gui.py) |
| File > Settings dialog, session fields, ROI selection, or participant text | [task_settings_gui.py](sssep_batch/task_settings_gui.py) |
| Persistent preferences, validation, or legacy folder settings | [launcher_settings.py](sssep_batch/launcher_settings.py) |
| Launcher colors, section cards, forms, or scrollable pages | [gui_style.py](sssep_batch/gui_style.py) |
| Saved-results view, its controls, or its background workers | [saved_plots_gui.py](sssep_batch/saved_plots_gui.py) |
| Interactive electrode map, ROI presets, or modal selection | [roi_selection_gui.py](sssep_batch/roi_selection_gui.py) |
| Persistent custom ROI definitions | [roi_settings.py](sssep_batch/roi_settings.py) |
| Analysis defaults and advanced processing settings | [config.py](sssep_batch/config.py) |
| Task settings and event records | [experiment/models.py](sssep_batch/experiment/models.py) |
| Balanced randomized cue order | [experiment/schedule.py](sssep_batch/experiment/schedule.py) |
| Fullscreen prompts, breaks, countdowns, or task CSV log | [experiment/runner.py](sssep_batch/experiment/runner.py) |
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
| Writing later FFT and scalp-map PNGs | [analysis/saved_outputs.py](sssep_batch/analysis/saved_outputs.py) |
| Event codes and durations passed into analysis | [analysis/protocol.py](sssep_batch/analysis/protocol.py) |
| Existing summary values | [analysis/metrics.py](sssep_batch/analysis/metrics.py) |
| FFT/scalp graphs, shared FFT filenames, and exclusive PNG path reservation | [analysis/plotting.py](sssep_batch/analysis/plotting.py) |
| Analysis summary CSVs, reports, or error files | [outputs.py](sssep_batch/outputs.py) |

[models.py](sssep_batch/models.py) contains analysis data containers.
[logging_utils.py](sssep_batch/logging_utils.py) supports analysis logs.

## How the parts connect

Participant task:

`entrypoint → gui → experiment settings → schedule → trigger backend → PySide6 presenter → task CSV`

Normal runs open the fixed `COM3` connection before participant screens. A
checked and confirmed test mode uses a simulated backend and clearly marks the
ready screen and task CSV; it never opens COM3 or sends markers. After
Space starts a five-second lead-in, a main-thread `QOpenGLWindow` draws each cue. Both hands
run first, followed by hand/ankle after untimed Space-then-Y admin screens. Its
matching `frameSwapped` callback immediately requests the cue's unique `1..255`
marker through the selected backend after Qt completes that frame's buffer
swap. A Qt `PreciseTimer` advances between cue and break screens at their
configured deadlines; Settings can hide the top-center countdown without changing
timing. A final thank-you screen stays for five seconds. The first handover and
thank-you swaps each send fixed code `100`; their final epoch rows record the
send time and outcome. Ordinary breaks and countdown redraws send no markers.
Escape aborts. TENS control stays outside this program. See
[task-protocol.md](docs/task-protocol.md) for the runtime contract.

Recording analysis:

`entrypoint → File > Settings → four-code analysis protocol → batch → pipeline → preprocessing / events / FFT → participant outputs → group outputs`

The numerical order is load/montage → EXG reference/drop → filter → resample
→ interpolate → average reference → recorded events → complete SSSEP epochs
→ remove 2.5 seconds from each epoch end → trial mean within each participant
and cue → per-electrode amplitude FFT. The default 15-second epoch therefore
uses its middle 10 seconds for the FFT. After all files finish, the batch
averages participant amplitude spectra with equal participant weight. It writes
consolidated participant and group FFT CSVs plus one selected-electrode PNG per
cue at each level.

Saved-result plotting is separate:

`saved participant FFT CSV → strict reload → participant/electrode/event selection → later ROI mean or scalp-bin values → PNG in saved_fft_plots`

Later ROI means average electrodes within participant before the equal-weight
group mean, retaining participant contributions in memory. Scalp maps use finite
electrodes with coordinates in the
saved `standard_1005` montage; missing or unmapped electrodes are not replaced
with zero. Saved plots are PNGs directly in `saved_fft_plots`, without per-plot
CSV/Excel copies or subfolders. Reserve filenames exclusively and add numbered
suffixes for repeats; on failure remove only that attempt's PNG, never the
shared folder or earlier outputs. The canonical FFT CSVs retain all amplitudes,
provenance, and participant counts. Omission warnings remain in the GUI.
Hemisphere comparisons and statistics remain external.

All FFT spectrum PNGs use `Condition_ROI_FFT_Amplitude.png`. Use the full recorded
trigger label and ROI name (selected electrode for processing plots); replace
spaces with underscores and sanitize Windows-invalid characters. Shared helpers
in `analysis/plotting.py` format names and exclusively reserve numbered paths.
Keep participant/group identity in titles and existing processing folders.
Scalp-map names retain their frequency, and old exports are not renamed.

## Keep these behaviors

- Keep one launcher with **View > SSSEP Task / Process Data / Generate FFT
  Plots** and a `QStackedWidget`, not main workflow tabs. The home shows only
  its NERD Lab SSSEP Task title, Start SSSEP Task button, and settings hint.
  Experiment fields and analysis defaults live in File > Settings. Save
  validates and atomically writes the draft to ignored `.sssep_gui_settings.json`
  before applying it; Cancel changes neither disk nor current preferences.
  Preserve fixed hardware codes and fresh randomization outside saved settings.
  Retain the old folder-only JSON format on load and merge folder updates without
  discarding session preferences. Invalid saved settings require visible review
  and Save before task/analysis use; never silently overwrite the bad file.
  Disable Settings and View actions while a task or worker is active.
- Keep launcher styling in `gui_style.py`: FPVS Studio's light/dark colors,
  section cards, and action hierarchy. Theme selection follows the system palette
  at launch. Size Settings to show Session controls without scrolling where
  desktop space permits; retain scrolling on small displays and visible Save/
  Cancel buttons. Do not style the fullscreen
  participant task or change processing to match launcher appearance.
- Keep saved-result plotting separate from BDF processing so one FFT calculation
  can support many later plots. Opening Generate FFT Plots loads the selected
  source in a worker; a parent results folder selects its most recently updated
  immediate run. Browse or finished path edits also load automatically. Reuse
  unchanged loaded data and keep Reload Results as an explicit refresh. Source
  changes invalidate loaded data and event selections; load failures must not
  leave stale data usable. Keep the configured ROI list and frequency.
- Keep electrode/ROI editing in the modal scalp-map selector. Apply only on
  Use ROI to return a draft to File > Settings > Regions of Interest; outer
  Save applies and persists the named `plot_rois` collection and frequency.
  Settings supports Add/Edit/Remove for separate singleton or multi-electrode
  entries; every listed ROI is plotted independently. Cancel preserves the
  previous collection. Migrate legacy active-ROI or plot-electrode settings to
  one entry on read; write only the collection schema. Empty collections allow
  scalp-only use and require adding an ROI before FFT plotting.
  Keep one map with four common example ROIs and no view
  tabs. Allow definition before results are loaded, retaining access to loaded
  non-BioSemi labels and saved selections. The
  BioSemi diagram is a selection aid, not a replacement for the processing or
  scalp-map `standard_1005` montage. Presets are FPVS examples, not validated
  SSSEP regions. Save Custom ROI explicitly persists one or more electrodes in
  ignored `.sssep_rois.json`, separate from experiment settings and analysis
  results. Use atomic writes, confirm replaced definitions, and report malformed
  files without overwriting them. Cancel does not undo an explicit save. Loading
  a saved ROI with missing electrodes must show omissions without changing its
  stored definition. Tests must inject temporary ROI storage paths.
- Generate FFT Plots contains only Saved results and Data selection cards;
  its ROI/frequency summary is read-only. File > Settings is their editor.
  Source changes do not reset these preferences. All conditions creates separate
  FFT PNGs for each named ROI and available attention trigger code at the selected
  group/participant level, excluding baselines. Scalp maps run once per event,
  independent of the ROI list. One retained worker renders sequentially, reports
  progress, and keeps successful plots when another fails. Show the complete
  failure report only after releasing the worker. Keep the footer summary short
  and all per-plot details in the scrollable results box. Settings and window
  close remain blocked for the whole batch. Report missing configured electrodes
  separately for each ROI while using its available subset; never combine ROI
  entries or rewrite saved definitions.
- The default TENS frequency is 26 Hz. Preserve saved operator preferences and
  recorded target frequencies. FFT PNGs show the selected target with a dashed
  vertical line labeled TENS Unit Stimulation Frequency. A saved-plot frequency
  Settings frequency changes only plot markers/scalp-bin selection, never the
  canonical FFT data or metadata. A blank setting uses each event's recorded
  frequency; without either, an FFT omits the marker and a scalp map fails with
  a request to set the frequency. Reject unsupported frequencies without clamping.
- Keep PySide6 presentation and live serial output inside `experiment/`,
  separate from BDF analysis.
- Keep `COM3` fixed and absent from the GUI. Open and check it before participant
  cues in normal runs; never continue after a trigger failure. Test mode must
  require explicit confirmation and must be recorded in the task CSV.
- Request each cue's marker immediately from the callback for its matching Qt
  buffer swap.
- Require an even epoch count per condition and freshly randomize balanced cues
  within each block, with at most two identical cues in a row. Always run both
  hands then hand/ankle. Timed breaks only
  separate cues within a block; the handover waits for Space and then Y on its
  separately visible confirmation screen. Held-key repeats cannot advance it.
- Keep cue/break text editable without changing cue identities or marker codes.
  Short breaks are not marked as code `100` baselines. Condition-end screens
  send `100`, but a marker alone does not establish a clean full baseline window.
- Pass both conditions' four fixed cue codes, the configured duration, and half
  the per-condition epoch count as expected repetitions into each analysis
  batch; do not fall back to unrelated settings.
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

3. Run the PyCharm entrypoint and check the affected view.
4. Update the relevant guide when a setting, output, or workflow changes.

Use Python 3.13 and the existing dependency pins. Synthetic tests do not prove
hardware timing. Before data collection, verify the sent codes and timing on a
real BioSemi Status channel. For numerical changes, also use the optional
[FPVS reference checks](docs/fpvs-parity.md#verification-and-reproducibility)
and a known recording when available.
