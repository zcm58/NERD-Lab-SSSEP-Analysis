"""Settings for analysis runs. Start with section 1 below.

After editing, save this file. Wait for any running batch to finish, close the
launcher, then run main.py again to apply your changes.
Do not run this settings file directly.
"""

# ---------------------------------------------------------------------------
# 1. Everyday options
# ---------------------------------------------------------------------------

# Number of .bdf files processed at the same time, not workers within one file.
# Start with 3; use 1 to process one file at a time and reduce memory use.
# On typical 16 GB computers, do not go above 3 unless memory use and stability
# have been checked. Each worker holds a recording and intermediate results.
BATCH_WORKERS = 3

# True saves diagnostic amplitude PNG images; False skips those images.
SAVE_PLOTS = True
# Default electrode selected in the launcher's analysis tab. Each run can choose
# another electrode without editing this file.
PLOT_CHANNEL = "Cz"

# True saves consolidated participant and group per-electrode FFT tables.
# Event summary CSVs are always written, even when this is False.
SAVE_CSV_SUMMARIES = True

# Optional starting folders, used only when no saved launcher folders exist.
# Normally, leave these blank and choose folders in the launcher.
INPUT_FOLDER = ""
OUTPUT_ROOT = ""


# ---------------------------------------------------------------------------
# 2. Experiment settings - change only with researcher direction
# ---------------------------------------------------------------------------
# These describe the experiment and how its results are summarized. Keep them
# consistent across recordings that will be compared.

# Trigger codes mark the prompt that appeared at that instant. These fixed codes
# match the disabled fields on the participant-task tab. A GUI analysis uses the
# selected condition's codes so presentation and analysis stay synchronized.
ACTIVE_EVENT_CODES = [11, 12, 21, 22]

# Trigger used for the separately measured Gap/Break baseline.
# Keep its label in TRIGGER_LABELS; it does not need a stimulation frequency.
BASELINE_EVENT_CODE = 100

# Human-readable names for each trigger code. The first word is retained in the
# legacy `condition` CSV column; the remaining words are retained in the legacy
# `finger` column even when the named body site is an ankle.
TRIGGER_LABELS = {
    11: "BothHands Left Hand",
    12: "BothHands Right Hand",
    21: "HandAnkle Right Hand",
    22: "HandAnkle Right Ankle",
    100: "Gap/Break",
}

# Optional stimulation frequency in hertz (Hz). TENS is controlled externally,
# so None avoids guessing. The analysis tab can add the correct value for a run.
STIMULATION_FREQUENCY_HZ = None
TRIGGER_HZ_MAP = {
    11: STIMULATION_FREQUENCY_HZ,
    12: STIMULATION_FREQUENCY_HZ,
    21: STIMULATION_FREQUENCY_HZ,
    22: STIMULATION_FREQUENCY_HZ,
}

# Optional extra reference lines drawn on every diagnostic plot.
FIXED_HZ_LINES = []

# Timing of each analyzed segment, in seconds.
PRE_EVENT_SEC = 0.0
EVENT_DURATION_SEC = 7.5
INCLUDE_POST_STIMULUS = False
POST_EVENT_SEC_IF_INCLUDED = 2.5
# Expected usable repetitions per active trigger; differences are flagged.
EXPECTED_REPETITIONS_PER_TRIGGER = 5

# Electrodes included in the region of interest (ROI) for SSSEP summaries and
# compatibility mean columns in the participant FFT CSV. PNGs use PLOT_CHANNEL.
# The FFT retains every good scalp electrode after the final average reference.
ANALYSIS_CHANNELS = [
    "Pz", "P2", "P4", "P6",
    "CPz", "CP2", "CP4", "CP6",
    "Cz", "C2", "C4", "C6",
    "FCz", "FC2", "FC4", "FC6",
]

# Plot AND peak-search limits in Hz, so changing these can change summary values.
# Consolidated per-electrode FFT CSVs retain every nonnegative FFT bin.
# These limits may extend beyond the filter cutoffs (for example, 0 to 128 Hz).
FMIN = 3.0
FMAX = 50.0
# Frequency bands for local SSSEP amplitude summaries, not FPVS neighboring-bin
# SNR. Change these only as part of the analysis plan.
TARGET_BAND_HALF_WIDTH_HZ = 0.20
LOCAL_NOISE_HALF_WIDTH_HZ = 1.00
LOCAL_NOISE_EXCLUSION_HALF_WIDTH_HZ = 0.20


# ---------------------------------------------------------------------------
# 3. Advanced processing settings - preserve the FPVS method
# ---------------------------------------------------------------------------
# Leave these unchanged for routine runs. Changes can affect results or break
# comparability with the reference method. See docs/fpvs-parity.md.

# BioSemi recording layout and reference electrodes.
SCALP_CHANNEL_COUNT = 64
REFERENCE_CHANNELS = ("EXG1", "EXG2")
STIM_CHANNEL = "Status"
MONTAGE_NAME = "standard_1005"

# Sampling rate after downsampling, in Hz. Use 0 or None to disable this step.
DOWNSAMPLE_RATE = 256

# Filter cutoffs in Hz. LOWCUT: 0/None disables the high-pass;
# HIGHCUT: None disables the low-pass.
LOWCUT = 0.1
HIGHCUT = 50.0

# FIR filter details matched to the FPVS reference.
FIR_LOW_TRANS_BW = 0.1
FIR_HIGH_TRANS_BW = 0.1
FIR_FILTER_LENGTH_POINTS = 8449
FIR_PHASE = "zero-double"
FIR_WINDOW = "hamming"
FIR_DESIGN = "firwin"

# Bad-channel screening settings.
KURTOSIS_REJECT_Z = 5.0
KURTOSIS_TRIM_PROPORTION = 0.10

# Small-number guard used when calculating amplitude ratios.
EPS = 1e-20

# Reference for the implemented preprocessing and per-electrode FFT formula.
FPVS_REFERENCE_COMMIT = "185d803f0056daebee04e5f28cc6b554c47336ce"
PROCESSING_METHOD = "fpvs_amplitude_v1"
