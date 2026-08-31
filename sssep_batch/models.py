"""Small shared data containers used across the pipeline.

These dataclasses do not perform analysis themselves. They give a clear shape
to data passed between modules: `EpochSet` for repeated time-domain EEG windows
and `Spectrum` for per-electrode FFT amplitudes.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class EpochSet:
    """
    Store repeated EEG windows for one trigger code.

    Attributes
    ----------
    code:
        The trigger code, such as 1 for Think Thumb or 100 for Gap/Break.
    label:
        Human-readable label for the trigger code.
    epochs:
        EEG data with shape (n_epochs, n_channels, n_times).
    skipped_epochs:
        Total number of events that were found but could not be used.
    out_of_bounds_epochs:
        Number of events rejected because the requested analysis window extended
        outside the recording.
    edge_excluded_epochs:
        Legacy report field. The FPVS-aligned path does not apply an additional
        FIR epoch exclusion and records zero here.
    """

    code: int
    label: str
    epochs: np.ndarray
    skipped_epochs: int
    out_of_bounds_epochs: int
    edge_excluded_epochs: int


@dataclass
class Spectrum:
    """
    Store per-electrode FFT amplitudes in microvolts.

    Attributes
    ----------
    freqs:
        Frequency values in Hz.
    amplitude_uv:
        FFT amplitudes with shape (n_channels, n_frequency_bins), in microvolts.
    method:
        Text label describing how the spectrum was computed.
    """

    freqs: np.ndarray
    amplitude_uv: np.ndarray
    method: str
