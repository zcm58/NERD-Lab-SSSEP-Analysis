"""Small shared data containers used across the pipeline.

These dataclasses do not perform analysis themselves. They give a clear shape
to data passed between modules: `AnalysisProtocol` for event settings,
`EpochSet` for repeated time-domain EEG windows, `Spectrum` for per-electrode
FFT amplitudes, and `ParticipantSpectrum` for one participant/event result.
"""

from dataclasses import dataclass
from math import isfinite

import numpy as np

from sssep_batch.config import (
    DOWNSAMPLE_RATE,
    FMAX,
    FMIN,
    FPVS_REFERENCE_COMMIT,
    HIGHCUT,
    LOWCUT,
    MONTAGE_NAME,
)


FFT_EXPORT_SCHEMA_VERSION = 1


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
    analyze_baseline: bool = True

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
        if not isinstance(self.analyze_baseline, bool):
            raise TypeError("analyze_baseline must be True or False.")
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


@dataclass(frozen=True, slots=True)
class ParticipantSpectrum:
    """One participant's already epoch-averaged FFT for one recorded event."""

    participant_id: str
    file_name: str
    event_type: str
    trigger_code: int
    trigger_label: str
    target_hz: float | None
    usable_epochs: int
    channel_names: tuple[str, ...]
    analysis_channels: tuple[str, ...]
    sampling_rate_hz: float
    analysis_window_sec: float
    spectrum: Spectrum
    epoch_window_sec: float | None = None
    fft_crop_start_sec: float = 0.0
    fft_crop_end_sec: float = 0.0
    fpvs_reference_commit: str = FPVS_REFERENCE_COMMIT
    montage_name: str = MONTAGE_NAME
    plot_fmin_hz: float = FMIN
    plot_fmax_hz: float = FMAX
    fft_schema_version: int = FFT_EXPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.participant_id, str) or not self.participant_id.strip():
            raise ValueError("participant_id must be a non-empty string.")
        if not isinstance(self.file_name, str) or not self.file_name.strip():
            raise ValueError("file_name must be a non-empty string.")
        if self.event_type not in {"cue", "baseline"}:
            raise ValueError("The event type must identify a trigger code epoch or baseline.")
        if (
            not isinstance(self.trigger_code, int)
            or isinstance(self.trigger_code, bool)
            or self.trigger_code < 1
        ):
            raise ValueError("trigger_code must be a positive integer.")
        if not isinstance(self.trigger_label, str) or not self.trigger_label.strip():
            raise ValueError("trigger_label must be a non-empty string.")
        if self.target_hz is not None and (
            not isinstance(self.target_hz, (int, float))
            or isinstance(self.target_hz, bool)
            or not isfinite(float(self.target_hz))
            or self.target_hz <= 0
        ):
            raise ValueError("target_hz must be a finite number above zero, or None.")
        if (
            not isinstance(self.usable_epochs, int)
            or isinstance(self.usable_epochs, bool)
            or self.usable_epochs < 1
        ):
            raise ValueError("usable_epochs must be 1 or more.")
        if not isinstance(self.spectrum, Spectrum):
            raise ValueError("spectrum must be a Spectrum value.")

        channel_names = tuple(self.channel_names)
        analysis_channels = tuple(self.analysis_channels)
        if not channel_names or any(
            not isinstance(channel, str) or not channel.strip()
            for channel in channel_names
        ):
            raise ValueError("channel_names must contain non-empty electrode labels.")
        if len(channel_names) != len(set(channel_names)):
            raise ValueError("channel_names must be unique.")
        if not analysis_channels or any(
            not isinstance(channel, str) or not channel.strip()
            for channel in analysis_channels
        ):
            raise ValueError("analysis_channels must contain non-empty electrode labels.")
        if len(analysis_channels) != len(set(analysis_channels)):
            raise ValueError("analysis_channels must be unique.")
        missing_analysis_channels = [
            channel for channel in analysis_channels if channel not in channel_names
        ]
        if missing_analysis_channels:
            raise ValueError(
                "analysis_channels are missing from channel_names: "
                f"{missing_analysis_channels}"
            )

        freqs = np.asarray(self.spectrum.freqs)
        amplitude_uv = np.asarray(self.spectrum.amplitude_uv)
        if freqs.ndim != 1 or freqs.size == 0:
            raise ValueError("spectrum frequencies must be a non-empty one-dimensional array.")
        if amplitude_uv.shape != (len(channel_names), len(freqs)):
            raise ValueError(
                "spectrum amplitudes must match channel_names and frequency bins."
            )
        if not np.isfinite(freqs).all() or not np.isfinite(amplitude_uv).all():
            raise ValueError("spectrum frequencies and amplitudes must all be finite.")
        if np.any(freqs < 0):
            raise ValueError("spectrum frequencies must be nonnegative.")
        if np.any(amplitude_uv < 0):
            raise ValueError("spectrum FFT amplitudes must be nonnegative.")
        if np.any(np.diff(freqs) <= 0):
            raise ValueError("spectrum frequencies must be strictly increasing.")
        if not isinstance(self.spectrum.method, str) or not self.spectrum.method.strip():
            raise ValueError("spectrum method must be a non-empty string.")

        if len(freqs) < 2:
            raise ValueError("spectrum needs at least two frequency bins.")
        sampling_rate_hz = self.sampling_rate_hz
        analysis_window_sec = self.analysis_window_sec
        for value, name in (
            (sampling_rate_hz, "sampling_rate_hz"),
            (analysis_window_sec, "analysis_window_sec"),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(float(value))
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite number above zero.")
        crop_start_sec = self.fft_crop_start_sec
        crop_end_sec = self.fft_crop_end_sec
        for value, name in (
            (crop_start_sec, "fft_crop_start_sec"),
            (crop_end_sec, "fft_crop_end_sec"),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(float(value))
                or value < 0
            ):
                raise ValueError(f"{name} must be a finite nonnegative number.")
        epoch_window_sec = self.epoch_window_sec
        if epoch_window_sec is None:
            epoch_window_sec = (
                float(analysis_window_sec) + float(crop_start_sec) + float(crop_end_sec)
            )
        if (
            not isinstance(epoch_window_sec, (int, float))
            or isinstance(epoch_window_sec, bool)
            or not isfinite(float(epoch_window_sec))
            or epoch_window_sec <= 0
        ):
            raise ValueError("epoch_window_sec must be a finite number above zero.")

        sampling_rate_hz = float(sampling_rate_hz)
        analysis_window_sec = float(analysis_window_sec)
        epoch_window_sec = float(epoch_window_sec)
        crop_start_sec = float(crop_start_sec)
        crop_end_sec = float(crop_end_sec)
        epoch_samples = int(round(epoch_window_sec * sampling_rate_hz))
        crop_start_samples = int(round(crop_start_sec * sampling_rate_hz))
        crop_end_samples = int(round(crop_end_sec * sampling_rate_hz))
        analysis_samples = int(round(analysis_window_sec * sampling_rate_hz))
        if epoch_samples - crop_start_samples - crop_end_samples != analysis_samples:
            raise ValueError(
                "FFT window provenance is inconsistent: the extracted epoch minus "
                "the start and end crops must equal analysis_window_sec at the "
                "recorded sampling rate."
            )
        if (
            not isinstance(self.fpvs_reference_commit, str)
            or not self.fpvs_reference_commit.strip()
        ):
            raise ValueError("fpvs_reference_commit must be a non-empty string.")
        if not isinstance(self.montage_name, str) or not self.montage_name.strip():
            raise ValueError("montage_name must be a non-empty string.")
        if (
            not isinstance(self.plot_fmin_hz, (int, float))
            or isinstance(self.plot_fmin_hz, bool)
            or not isfinite(float(self.plot_fmin_hz))
            or self.plot_fmin_hz < 0
        ):
            raise ValueError("plot_fmin_hz must be a finite nonnegative number.")
        if (
            not isinstance(self.plot_fmax_hz, (int, float))
            or isinstance(self.plot_fmax_hz, bool)
            or not isfinite(float(self.plot_fmax_hz))
            or self.plot_fmax_hz <= self.plot_fmin_hz
        ):
            raise ValueError("plot_fmax_hz must be finite and greater than plot_fmin_hz.")
        if (
            not isinstance(self.fft_schema_version, int)
            or isinstance(self.fft_schema_version, bool)
            or self.fft_schema_version < 1
        ):
            raise ValueError("fft_schema_version must be a positive integer.")

        object.__setattr__(self, "participant_id", self.participant_id.strip())
        object.__setattr__(self, "file_name", self.file_name.strip())
        object.__setattr__(self, "trigger_label", self.trigger_label.strip())
        object.__setattr__(self, "channel_names", channel_names)
        object.__setattr__(self, "analysis_channels", analysis_channels)
        object.__setattr__(
            self, "fpvs_reference_commit", self.fpvs_reference_commit.strip()
        )
        object.__setattr__(self, "montage_name", self.montage_name.strip())
        object.__setattr__(self, "sampling_rate_hz", sampling_rate_hz)
        object.__setattr__(self, "analysis_window_sec", analysis_window_sec)
        object.__setattr__(self, "epoch_window_sec", epoch_window_sec)
        object.__setattr__(self, "fft_crop_start_sec", crop_start_sec)
        object.__setattr__(self, "fft_crop_end_sec", crop_end_sec)
        object.__setattr__(self, "plot_fmin_hz", float(self.plot_fmin_hz))
        object.__setattr__(self, "plot_fmax_hz", float(self.plot_fmax_hz))
        if self.target_hz is not None:
            object.__setattr__(self, "target_hz", float(self.target_hz))
