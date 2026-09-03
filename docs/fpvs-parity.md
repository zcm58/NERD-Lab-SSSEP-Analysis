# FPVS preprocessing and amplitude FFT parity

## Method and reference

`fpvs_amplitude_epoch_crop_v2` follows the active FPVS Toolbox preprocessing
and per-electrode FFT formula at commit
`185d803f0056daebee04e5f28cc6b554c47336ce`. SSSEP adds its own epoch crop
before the FFT. The Toolbox is a reference for verification, not a runtime
dependency. SSSEP still runs locally from `main.py` in PyCharm.

The reference source files are:

| FPVS source under `src/` | Responsibility |
| --- | --- |
| `Main_App/Shared/load_utils.py` | BDF subset, channel types, montage |
| `Main_App/processing/preprocess.py` | Initial reference through final reference |
| `Main_App/Performance/process_runner.py` | Event detection after preprocessing |
| `Main_App/Shared/post_process.py` | Float64 repetition mean, electrode order, amplitude FFT |

`tests/test_fpvs_reference_parity.py` checks normalized source hashes before
using the reference loader, preprocessor, and FFT expressions. If the source
changes, the test fails rather than silently accepting a different reference.

## Exact numerical processing

1. **Load:** Read the first 64 original BDF channel names plus EXG1/EXG2 and
   `Status`, retaining file order. Selected reference channels are EEG;
   unselected EXG1–EXG8 channels are misc. The source recording is never edited.
   SSSEP loads into RAM; FPVS uses a disk-backed float64 array. Identical loaded
   samples are verified through their complete downstream processing.
2. **Montage:** Apply MNE's `standard_1005` with case-insensitive matching and
   `on_missing="warn"`, before the initial reference. This replaces the previous
   `biosemi64` electrode coordinates for interpolation. The BioSemi name order
   is still used for recognized complete 64-electrode output sets.
3. **Initial reference:** Subtract the mean of EXG1/EXG2 with `projection=False`,
   drop the selected references, and retain the selected scalp channels plus
   `Status`. If references are missing, FPVS logs the skipped operation.
4. **Filter before resampling:** Default high-pass 0.1 Hz and low-pass 50 Hz;
   FIR, `zero-double`, Hamming window, `firwin`, both transition widths 0.1 Hz,
   and `skip_by_annotation="edge"`. The base length is 8449 points at 256 Hz.
   Above the target rate, length is
   `round((8449 - 1) * original_sfreq / target_sfreq) + 1`, increased by one if
   even, and never below 8449. There is no additional notch filter.
5. **Resample:** Downsample to 256 Hz with `npad="auto"`, `window="hann"`.
   No events array is passed to resampling. Preserve the successfully applied
   filter cutoff metadata. This Hann window belongs to resampling, not the
   later amplitude FFT.
6. **Detect and interpolate bad channels:** Use the algorithm below.
7. **Final reference:** Create the average EEG reference projection and apply
   it after interpolation. All retained good EEG electrodes contribute; the
   later plotting ROI does not define this reference.
8. **Events and complete SSSEP epochs:** Find events on the final grid with
   `shortest_event=1` and MNE's other defaults, including its default transition
   rule. No custom trigger mask is added. If Status extraction raises, use
   MNE's default annotation mapping, as the active FPVS runner does. Retain
   complete SSSEP onset windows. As in FPVS, construct MNE `EpochsArray` over
   all retained channels with `baseline=None` and its default projection
   behavior, then select good EEG electrodes. This epoch projection can alter
   the last floating-point bits even after the continuous reference projection
   was applied; it is necessary for exact numerical parity. Do not add an FIR
   edge margin or replace EEG NaNs/infinities with zeros. Require each entire
   configured epoch before retaining it.
9. **SSSEP FFT window:** Remove 2.5 seconds from the start and end of every
   retained epoch. At the 15-second default and 256 Hz, extract 3840 samples,
   retain the stop-exclusive slice `640:3200`, and pass 2560 samples (10
   seconds) to the cue average and FFT. Apply the same crop to cue and baseline
   epochs.
10. **Participant cue average and FFT:** For one participant's cropped
   same-cue epochs shaped trials × electrodes × samples:

   ```python
   avg_data = np.mean(epochs.astype(np.float64), axis=0)
   avg_data_uv = avg_data * 1e6
   num_times = avg_data.shape[1]
   num_fft_bins = num_times // 2 + 1
   frequencies = np.fft.rfftfreq(num_times, d=1.0 / sfreq)
   fft_full_spectrum = np.fft.fft(avg_data_uv, axis=1)
   amplitudes_uv = np.abs(fft_full_spectrum[:, :num_fft_bins]) / num_times * 2
   ```

   The arithmetic order is deliberate. Do not substitute power, Welch, a
   tapered FFT, FFT padding, channel averaging before the FFT, or a differently
   ordered scaling expression. FPVS also doubles DC and Nyquist; this method
   preserves that convention. The preprocessing and formula stay
   FPVS-aligned; the samples supplied to the formula use the SSSEP window in
   step 9.

Group output is a later SSSEP reporting step. It gives each participant's
already-computed amplitude spectrum equal weight; usable epoch count does not
change a participant's weight. Participant time-domain signals are never
averaged together across people.

## How FPVS interpolation works

FPVS calculates SciPy excess kurtosis on the continuous, filtered, resampled
signal for each currently good EEG channel (`fisher=True`, `bias=False`). It
replaces nonfinite **kurtosis statistics** with `np.nan_to_num`; it does not
replace nonfinite EEG samples.

Sort those statistics and remove `floor(channel_count * 0.10)` values from each
tail when estimating the mean and population standard deviation. Compute a
z-score for every eligible electrode against that trimmed distribution. Mark
electrodes with `abs(z) > 5` by default, provided the trimmed standard deviation
is greater than `1e-9`. Append them to any already marked bad electrodes.

When a montage is available, FPVS calls:

```python
raw.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)
```

For EEG in MNE 1.9.0 this uses spherical splines and all eligible retained good
EEG electrodes, not a nearest-neighbor average and not the 16-channel SSSEP
plotting ROI. Successful interpolation resets the bad list. A missing montage
or interpolation failure is logged; unresolved bads remain excluded from the
final reference and Epochs FFT. A threshold of `0` or `None` skips both
automatic detection **and interpolation**, including previously marked bads.

No additional FPVS QC workflow, automatic participant exclusion, or artifact
repair has been added. Existing per-file logs and screening CSVs remain.

## SSSEP-specific boundaries

Parity means identical preprocessing and per-electrode amplitude FFT
calculation for identical input data, settings, electrode labels, and samples
supplied to the FFT. These experiment-specific choices remain:

- Both SSSEP conditions supply fixed trigger codes (`11`/`12` and `21`/`22`);
  cue duration remains editable in File > Settings. The default full window is 15
  seconds, or 3840 samples at 256 Hz. Other durations use
  `round(duration * sampling_rate)` samples, with a stop-exclusive slice and no
  extra endpoint. Event indices account for MNE's `raw.first_samp`.
- SSSEP removes 2.5 seconds from both epoch ends before averaging and FFT. This
  fixed onset/offset crop defines the middle analysis window. It is separate
  from FPVS's visual-oddball marker-55 crop, which aligns 1.2 Hz stimulation
  cycles. The FPVS marker crop and its 1.2 Hz exact-bin restrictions do not
  apply here. The reference test executes FPVS's FFT assignments after
  supplying the cropped SSSEP samples; it does not claim an unchanged FPVS
  experiment.
- FFT bin spacing is the reciprocal of the analyzed duration: 0.1 Hz for the
  default middle 10-second window. The optional
  stimulation frequency shown in the launcher defaults to 26 Hz and adds dashed
  FFT markers labeled `TENS Unit Stimulation Frequency`
  and SSSEP summary values. Leaving it blank leaves those target summaries
  unavailable while preserving the full per-electrode FFT.
- Recognized complete 64-channel sets are ordered exactly as FPVS's default
  BioSemi name list. Smaller or unfamiliar sets keep their actual labels.
  SSSEP deliberately does not copy FPVS's fallback that relabels an unfamiliar
  64-channel set with default names.
- When a protocol supplies a separately measured baseline, local amplitude SNR
  and Gap/Break comparisons occur after the FFT. The current participant task
  treats code `100` as an epoch-end/break delimiter and disables that baseline
  FFT. These comparisons are not FPVS's neighboring-bin SNR, BCA, or Z-score
  exports. Existing summary values and CSV mean columns use the configured ROI,
  with actual contributing channels recorded. PNGs display one electrode selected
  in the launcher.
- Each BDF is treated as one participant. A batch must therefore contain one
  BDF per participant. Group spectra average participant amplitude spectra
  equally and remain downstream of the FPVS parity boundary.

For parity, FPVS's logged warning-and-continue behavior is preserved for
reference/filter/resampling/interpolation failures. Successful completion
does not establish that every requested step succeeded: review the report,
warnings, final sampling rate, and channel lists. A recording with no usable
active epochs is reported as failed.

## Outputs and migration

- Every batch creates a fresh `YYYY-MM-DD @ HHhMM` folder. A same-minute
  collision adds ` (2)`, ` (3)`, and so on. Older reports, errors, and plots
  cannot leak into a rerun. The GUI keeps the chosen parent folder as its
  default; View Output opens the completed run.
- `participant_fft_amplitudes.csv` consolidates all participants, cues, the
  baseline, retained EEG electrodes, and the full nonnegative spectrum
  (0–128 Hz with default settings). The baseline is stored once per participant
  rather than repeated in every cue table. The reusable table also records its
  export-schema version, FPVS reference commit, montage, actual sampling rate,
  analysis-window duration, and plot-frequency range.
- `group_fft_amplitudes.csv` contains equal-participant group means and the
  contributing participant count for each electrode. Both exports are CSV
  files that can be opened in Excel.
- The group CSV's baseline row uses all available participant baselines. A cue
  plot instead uses a cue-matched baseline cohort and omits the baseline line
  if any cue contributor lacks matching selected-electrode data.
- Each participant folder contains one selected-electrode amplitude PNG per
  usable cue under `plots/`. `group_plots/` contains the group equivalents.
  FFT PNGs use `Condition_ROI_FFT_Amplitude.png`, with the full condition label
  and selected electrode as the ROI; spaces become underscores and repeated
  names receive numbered suffixes. If the selected electrode
  is unavailable, only the affected plot is skipped; spectra and participant
  counts remain available.
- **View > Generate FFT Plots** reloads `participant_fft_amplitudes.csv` after the
  parity-checked FFT is complete. Electrode/ROI curves and raw-amplitude scalp
  maps are downstream displays: they do not alter preprocessing or FFT values.
  Later ROI group curves average electrodes within participant first. A scalp
  map uses the nearest saved FFT bin, reports that actual bin, and does not fill
  missing electrodes with zero. Later plot exports save only PNGs directly in
  `saved_fft_plots`, with numbered filenames for repeated plots. No per-plot
  CSV/Excel copies or subfolders are created. The canonical FFT CSVs retain
  all values, provenance, and per-electrode participant counts; the GUI reports
  labels omitted for missing montage coordinates.
- New summary fields use explicit `*_amplitude_uv` names. Amplitude ratios use
  `20 * log10(ratio)`. Missing active/baseline measurements remain unavailable.
- Old power and Welch outputs are retired. Do not combine them with the new
  amplitudes. Rerun recordings under the same new settings for comparisons.

## Verification and reproducibility

The numerical parity environment uses Python 3.13.5 on Windows with
MNE 1.9.0, NumPy 2.3.1, SciPy 1.16.0, pandas 2.3.0, matplotlib 3.10.3, and
PySide6 6.9.1. A clean Python 3.13.5 installation accepted every pin in
`requirements.txt`, including pyserial 3.5. Different versions or platforms
are not assumed to be bitwise identical.

The automated checks include direct FPVS source comparisons, consolidated
participant/group output checks, and isolated Qt launcher checks. The optional
participant-recording test skips when no external BDF is selected. PySide6
presentation and COM3 marker timing still require the hardware check described
below.

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
$env:FPVS_REFERENCE_ROOT = "C:\Projects\FPVS Toolbox Repo"
.\.venv\Scripts\python.exe -m pytest -q
```

The source comparison directly exercises the reference loader/preprocessor
on deterministic 67-channel BDFs at 256, 512, and 2048 Hz. Four cases cover
clean data, automatic bad-channel detection/interpolation, a pre-marked bad
channel, and disabled interpolation. Assertions require exact array equality
for final continuous samples, events, epochs, and participant FFT amplitudes.
No numerical tolerance is used for those source-parity comparisons. Separate
end-to-end tests check the consolidated participant and group CSV values.

Other tests exercise BDF calibration and digital triggers, two real process
workers, complete amplitude outputs/PNGs, fresh rerun folders, per-electrode
phase preservation, FFT DC/Nyquist scaling, and real SSSEP Qt runner lifetime.

No participant recording was supplied for this verification. Synthetic tests
establish the implemented numerical contract but cannot validate a study's
recording labels, trigger protocol, or artifacts. An additional real-recording
smoke test is available:

```powershell
$env:SSSEP_TEST_BDF = "C:\Data\SSSEP\recording.bdf"
.\.venv\Scripts\python.exe -m pytest -q tests/test_regression_external_bdf.py
```

This external smoke test checks successful processing and output structure;
it is not a second independent FPVS comparison. Neither reference source nor
participant BDFs are bundled with SSSEP.
