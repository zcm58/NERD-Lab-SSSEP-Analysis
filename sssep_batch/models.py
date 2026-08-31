"""Small shared data containers used across the pipeline.

These dataclasses do not perform analysis themselves. They give a clear shape
to data passed between modules: `AnalysisProtocol` for event settings,
`EpochSet` for repeated time-domain EEG windows, and `Spectrum` for
per-electrode FFT amplitudes.
"""

from dataclasses import dataclass
from math import isfinite

import numpy as np

from sssep_batch.config import DOWNSAMPLE_RATE, FMAX, FMIN, HIGHCUT, LOWCUT


def _target_frequency_bounds() -> tuple[float, float]:
    """Return the range retained by the configured plot, filter, and resampling."""

    lower_bound = float(FMIN)
    if LOWCUT is not None and LOWCUT > 0:
        lower_bound = max(lower_bound, float(LOWCUT))

    upper_bound = float(FMAX)
    if HIGHCUT is not None:
        upper_bound = min(upper_bound, float(HIGHCUT))
    if DOWNSAMPLE_RATE is not None and DOWNSAMPLE_RATE > 0:
        upper_bound = min(upper_bound, float(DOWNSAMPLE_RATE) / 2.0)
    return lower_bound, upper_bound


@dataclass(frozen=True, slots=True)
class AnalysisTrigger:
    """One active BioSemi event used to cut and label FFT epochs."""

    code: int
    label: str
    target_hz: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, int) or isinstance(self.code, bool) or self.code < 1:
            raise ValueError("Analysis trigger codes must be positive integers.")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Each analysis trigger needs a non-empty label.")
        if self.target_hz is not None and (
            not isinstance(self.target_hz, (int, float))
            or isinstance(self.target_hz, bool)
            or not isfinite(float(self.target_hz))
            or self.target_hz <= 0
        ):
            raise ValueError("A target frequency must be a finite number above zero, or None.")
        if self.target_hz is not None:
            lower_bound, upper_bound = _target_frequency_bounds()
            if not lower_bound <= float(self.target_hz) <= upper_bound:
                raise ValueError(
                    f"A target frequency must be between {lower_bound:g} and "
                    f"{upper_bound:g} Hz so it remains inside the configured "
                    "plot, filter, and FFT ranges."
                )
        object.__setattr__(self, "label", self.label.strip())
        if self.target_hz is not None:
            object.__setattr__(self, "target_hz", float(self.target_hz))


@dataclass(frozen=True, slots=True)
class AnalysisProtocol:
    """Event definitions and timing used for one recording-analysis batch."""

    active_triggers: tuple[AnalysisTrigger, ...]
    event_duration_sec: float
    expected_repetitions_per_trigger: int
    baseline_event_code: int
    baseline_label: str = "Gap/Break"

    def __post_init__(self) -> None:
        if not self.active_triggers or not all(
            isinstance(trigger, AnalysisTrigger) for trigger in self.active_triggers
        ):
            raise ValueError("AnalysisProtocol needs at least one AnalysisTrigger.")
        codes = [trigger.code for trigger in self.active_triggers]
        if len(codes) != len(set(codes)):
            raise ValueError("Analysis trigger codes must be unique.")
        if (
            not isinstance(self.event_duration_sec, (int, float))
            or isinstance(self.event_duration_sec, bool)
            or not isfinite(float(self.event_duration_sec))
            or self.event_duration_sec <= 0
        ):
            raise ValueError("event_duration_sec must be a finite number above zero.")
        if (
            not isinstance(self.expected_repetitions_per_trigger, int)
            or isinstance(self.expected_repetitions_per_trigger, bool)
            or self.expected_repetitions_per_trigger < 1
        ):
            raise ValueError("expected_repetitions_per_trigger must be 1 or more.")
        if (
            not isinstance(self.baseline_event_code, int)
            or isinstance(self.baseline_event_code, bool)
            or self.baseline_event_code < 1
            or self.baseline_event_code in codes
        ):
            raise ValueError(
                "baseline_event_code must be a positive integer distinct from active codes."
            )
        if not isinstance(self.baseline_label, str) or not self.baseline_label.strip():
            raise ValueError("baseline_label must be non-empty.")
        object.__setattr__(self, "event_duration_sec", float(self.event_duration_sec))
        object.__setattr__(self, "baseline_label", self.baseline_label.strip())

    @property
    def active_event_codes(self) -> tuple[int, ...]:
        """Return active codes in the order used for output rows and plots."""

        return tuple(trigger.code for trigger in self.active_triggers)


@dataclass
class EpochSet:
    """
    Store repeated EEG windows for one trigger code.

    Attributes
    ----------
    code:
        The trigger code, such as 11 for a cue or 100 for Gap/Break.
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
