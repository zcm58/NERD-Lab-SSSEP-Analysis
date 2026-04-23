"""Shared data containers."""

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
        Number of events rejected because the analysis window overlapped the
        conservative FIR edge-transient margin near the start or end.
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
    Store one frequency spectrum.

    Attributes
    ----------
    freqs:
        Frequency values in Hz.
    power:
        Average power value at each frequency.
    method:
        Text label describing how the spectrum was computed.
    """

    freqs: np.ndarray
    power: np.ndarray
    method: str
