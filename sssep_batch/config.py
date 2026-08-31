"""Settings for analysis runs. Start with section 1 below.

After editing, save this file. Wait for any running batch to finish, close the
launcher, then run sssep_bdf_batch_processor.py again to apply your changes.
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
# Maximum amplitude PNGs per recording. This limits images only, not
# calculations, condition summaries, or spectrum CSV files.
MAX_INDIVIDUAL_PLOTS = 5

# True saves per-electrode FFT spectrum CSVs for every usable active condition.
# The main event summary CSV is always written, even when this is False.
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

# Trigger codes mark conditions in the recording. Every active code needs a
# label in TRIGGER_LABELS and a stimulation frequency in TRIGGER_HZ_MAP.
# Active condition triggers to analyze:
ACTIVE_EVENT_CODES = [
    1, 2, 3, 4, 5,
    11, 12, 13, 14, 15,
    21, 22, 23, 24, 25,
]

# Trigger used for the separately measured Gap/Break baseline.
# Keep its label in TRIGGER_LABELS; it does not need a stimulation frequency.
BASELINE_EVENT_CODE = 100

# Human-readable names for each trigger code. Keep BASELINE_EVENT_CODE labeled.
TRIGGER_LABELS = {
    1: "Think Thumb",
    2: "Think Index",
    3: "Think Middle",
    4: "Think Ring",
    5: "Think Pinky",
    11: "Wiggle Thumb",
    12: "Wiggle Index",
    13: "Wiggle Middle",
    14: "Wiggle Ring",
    15: "Wiggle Pinky",
    21: "Touch Thumb",
    22: "Touch Index",
    23: "Touch Middle",
    24: "Touch Ring",
    25: "Touch Pinky",
    100: "Gap/Break",
}

# Expected stimulation frequency in hertz (Hz) for each active trigger code.
TRIGGER_HZ_MAP = {
    1: 10.0,
    2: 17.0,
    3: 23.0,
    4: 34.0,
    5: 45.0,
    11: 10.0,
    12: 17.0,
    13: 23.0,
    14: 34.0,
    15: 45.0,
    21: 10.0,
    22: 17.0,
    23: 23.0,
    24: 34.0,
    25: 45.0,
}

# Frequencies drawn as reference lines in diagnostic plots.
FIXED_HZ_LINES = [10.0, 17.0, 23.0, 34.0, 45.0]

# Timing of each analyzed segment, in seconds.
PRE_EVENT_SEC = 0.0
EVENT_DURATION_SEC = 7.5
INCLUDE_POST_STIMULUS = False
POST_EVENT_SEC_IF_INCLUDED = 2.5
# Expected usable repetitions per active trigger; differences are flagged.
EXPECTED_REPETITIONS_PER_TRIGGER = 5

# Electrodes included in the region of interest (ROI) for SSSEP summaries.
# The FFT retains every good scalp electrode; plots/summaries average amplitudes
# over these channels only, after the full-scalp final average reference.
ANALYSIS_CHANNELS = [
    "Pz", "P2", "P4", "P6",
    "CPz", "CP2", "CP4", "CP6",
    "Cz", "C2", "C4", "C6",
    "FCz", "FC2", "FC4", "FC6",
]

# Plot AND peak-search limits in Hz, so changing these can change summary values.
# Full per-electrode spectrum CSVs still retain every nonnegative FFT bin.
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
