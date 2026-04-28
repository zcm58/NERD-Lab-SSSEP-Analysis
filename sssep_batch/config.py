"""Project settings and experiment constants.

Beginner note:
    Most users should only edit the folder defaults, BATCH_WORKERS, trigger
    labels, trigger frequencies, and output toggles. The filtering, epoch, and
    metric settings affect analysis results; change those only when the analysis
    plan intentionally changes.
"""

# Optional fallback folders used only when no saved GUI folders exist.
# Normal use: choose folders in the launcher. Leave these blank unless you want
# the launcher to start with fixed default folders on this computer.
INPUT_FOLDER = ""
OUTPUT_ROOT = ""

# Number of .bdf files to process at the same time.
# This is file-level parallelism across separate recordings. It does not split
# filtering, FFT, plotting, or any other work inside a single file across
# multiple workers.
#
# Start with 3. On typical 16 GB systems, 3 workers is the recommended maximum
# because each worker may hold a full raw recording plus intermediate arrays for
# filtering, interpolation, FFT/Welch, plotting, and report generation.
# Increasing above 3 is possible, but it is not recommended on typical 16 GB
# machines unless you have tested memory headroom and stability.
BATCH_WORKERS = 3

# Advanced recording layout settings. Do not change these unless the BioSemi
# channel layout or reference setup changed.
SCALP_CHANNEL_COUNT = 64
REFERENCE_CHANNELS = ("EXG1", "EXG2")
STIM_CHANNEL = "Status"
MONTAGE_NAME = "biosemi64"

# Advanced analysis settings. These values affect math and should stay aligned
# with the experiment plan.
DOWNSAMPLE_RATE = 256

LOWCUT = 3.0
HIGHCUT = 50.0
APPLY_NOTCH = True
NOTCH_FREQ = 60.0

FIR_LOW_TRANS_BW = 0.1
FIR_HIGH_TRANS_BW = 0.1
FIR_FILTER_LENGTH_POINTS = 8449
FIR_PHASE = "zero-double"
FIR_WINDOW = "hamming"
FIR_DESIGN = "firwin"

PRE_EVENT_SEC = 0.0
EVENT_DURATION_SEC = 7.5
INCLUDE_POST_STIMULUS = False
POST_EVENT_SEC_IF_INCLUDED = 2.5
EXPECTED_REPETITIONS_PER_TRIGGER = 5

BASELINE_EVENT_CODE = 100
TRIGGER_MASK = 0xFF

# Frequency-domain metric settings.
FMIN = 3.0
FMAX = 50.0
TARGET_BAND_HALF_WIDTH_HZ = 0.20
LOCAL_NOISE_HALF_WIDTH_HZ = 1.00
LOCAL_NOISE_EXCLUSION_HALF_WIDTH_HZ = 0.20
EPS = 1e-20

N_PER_SEG_SEC = 2.0
N_OVERLAP_FRAC = 0.5

KURTOSIS_REJECT_Z = 5.0
KURTOSIS_TRIM_PROPORTION = 0.10

SAVE_CSV_SUMMARIES = True
SAVE_PLOTS = True
# Limits plot creation only. It must not limit metrics or CSV summaries.
MAX_INDIVIDUAL_PLOTS = 5

# Channels included in SSSEP metric calculations after preprocessing.
ANALYSIS_CHANNELS = [
    "Pz", "P2", "P4", "P6",
    "CPz", "CP2", "CP4", "CP6",
    "Cz", "C2", "C4", "C6",
    "FCz", "FC2", "FC4", "FC6",
]

# Active condition triggers to analyze. Every code here needs a label in
# TRIGGER_LABELS and a stimulation frequency in TRIGGER_HZ_MAP.
ACTIVE_EVENT_CODES = [
    1, 2, 3, 4, 5,
    11, 12, 13, 14, 15,
    21, 22, 23, 24, 25,
]

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

# Expected stimulation frequency for each active trigger code.
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
