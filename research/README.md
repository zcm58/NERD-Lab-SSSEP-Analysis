# Reproduce the two attention comparisons

Choose the comparison and frequency definition to reproduce. Each entry is an
independent, single-file research script:

| Comparison | Two selected bins: 25.4 and 26.4 Hz | Earlier full band: 25–27 Hz, 11 bins |
| --- | --- | --- |
| Left versus right hand, codes 11/12 | [Two-bin script](reproduce_left_vs_right_hand.py) | [Full-band script](reproduce_left_vs_right_hand_full_band.py) |
| Right hand versus right ankle, codes 21/22 | [Two-bin script](reproduce_right_hand_vs_right_ankle.py) | [Full-band script](reproduce_right_hand_vs_right_ankle_full_band.py) |

Each file contains its own preprocessing, FFTs, statistics and plotting code.
It does not import `sssep_batch`, another research script, or earlier analysis
helpers. The application and its GUI analysis method are unchanged.

## Run in PyCharm

1. Use the project's existing 64-bit Python 3.13 `.venv` interpreter.
2. Right-click the desired script and choose **Run**.
3. Select the original participant BDF folder and a parent results folder outside
   this repository. Every run reserves a new folder and preserves prior results.

Alternatively, set `BDF_FOLDER` and `OUTPUT_PARENT` at the top of the file.
The scripts require the fixed recording protocol: 64 BioSemi scalp channels,
EXG1/EXG2, 30 complete six-second epochs per trigger code, and C4 reconstruction.
An incompatible or failed recording stops group publication and leaves an
error report. They do not silently analyze a smaller participant cohort.

When copied elsewhere, each script needs these packages in its interpreter:

```text
mne==1.9.0
numpy==2.3.1
scipy==1.16.0
matplotlib==3.10.3
pandas==2.3.0
```

Tkinter, included in the standard Windows Python installation, supplies the
folder pickers. No Qt installation or running SSSEP application is needed.

## What is reproduced

Both FFT calculations use the same C4-reconstructed preprocessing snapshot,
final average reference, six-second epochs and final-five-second FFT window
(1280 samples at 256 Hz):

- **Canonical:** average same-cue waveforms first, then calculate electrode FFT amplitudes.
- **Diagnostic:** calculate electrode FFT amplitudes for every trial first,
  then average their magnitudes. This also retains non-phase-locked signal and noise.

Each version uses its fixed signal frequencies for every person and cue:

- **Two-bin signal:** the arithmetic mean of the two saved FFT amplitudes at **25.4 Hz and
  26.4 Hz**: `(amplitude_25.4 + amplitude_26.4) / 2`. Other bins, including
  those between these frequencies, do not enter the primary response.
- **Full-band signal:** the arithmetic mean of all **11 saved FFT amplitudes in
  25–27 Hz**, inclusive, in 0.2 Hz steps. Use the `_full_band.py` scripts to
  reproduce the earlier full-band analysis.
- Spectral background: mean amplitude in **23–24.4 Hz and 27.6–29 Hz**, inclusive:
  the same 16 background bins for both versions.
- Corrected response: signal mean minus background mean, in microvolts.
  Negative corrected values are retained. Multiplying by the number of signal
  bins (2 or 11) gives an equivalent amplitude sum; it leaves paired t
  statistics unchanged.

This is frequency-domain background subtraction. It is not a TENS-off/resting
baseline or subtraction of the variable intervals after trigger code 100.
The right-hand unit's frequency remains unknown; an overlapping stimulation
component could affect either the signal or background bands.

ROI means are calculated within participant before equal-participant group
averaging. Tests compare paired participant values, use two-sided paired t tests
with actual `N-1` degrees of freedom, and report **uncorrected** p-values, 95%
t intervals, paired effect sizes, and secondary Wilcoxon results.

Earlier fixed-bin and participant-specific peak checks are exported separately.
They reproduce the previous analyses but do not define the new pooled response.
The historical nearby-peak search still considers all 11 bins in 25–27 Hz,
using both cues pooled together, never selecting separately for each cue.
ROI sensitivities are retained in the tables; primary plots use
the two prespecified regions. Scalp maps are descriptive, not source localization
or electrode-level statistical tests.

## Reuse the first run's cache

Raw processing captures all four task codes once and saves
`full_task_spectra.npz`. Any of the four scripts can analyze its own condition from
that cache without reading the BDFs again. Set `CACHE_FILE` at the top, or use:

```powershell
.\.venv\Scripts\python.exe research\reproduce_right_hand_vs_right_ankle.py --cache "D:\EEG\Reproductions\first_run\full_task_spectra.npz" --output "D:\EEG\Reproductions"
```

Optional command-line arguments are also available for unattended runs; they
do not change the application's PyCharm/GUI workflow. `--help` lists them.
`--reference-csv` requires exact reproduction of the canonical participant FFT
CSV. `--verify-diagnostic` compares with an earlier compatible full-spectrum
diagnostic NPZ. Older ROI-only files cannot serve as the main input cache.
An older full-electrode cache without method metadata produces an explicit
provenance warning; prefer caches generated by these scripts.

Each result folder contains participant values, pooled and historical statistics,
spectra, paired plots, corrected-amplitude scalp maps, `analysis_results.json`,
`RESULTS.md`, and a `run_manifest.json` recording source/script hashes and package
versions. Raw runs also retain processing-quality reports and the reusable cache.
Numerical verification is recorded in the manifest when references are supplied.

## Find the earlier p ≈ 0.0451 result

Run [reproduce_left_vs_right_hand_full_band.py](reproduce_left_vs_right_hand_full_band.py),
using the original 22 participants or their full-spectrum cache. In the new
run's `paired_statistics_uncorrected.csv`, select this row:

- `method`: `phase_insensitive`
- `metric`: `pooled_raw_amplitude_uv`
- `comparison`: `Spatial interaction`

This reproduces the earlier full-band result, approximately **p = 0.04505**:
the right-minus-left difference between the left-cue and right-cue changes.
It is an uncorrected exploratory test of raw mean single-trial amplitudes.
The background-corrected row and the two-bin scripts use different response
definitions and need not give that p-value.

Keep the two-bin, full-band and selected-peak findings separate. The earlier 4%
left-cue increase and 4.6% ankle-cue increase came from selected-peak analyses;
their reproduction is in the historical tables, not the pooled primary rows.
