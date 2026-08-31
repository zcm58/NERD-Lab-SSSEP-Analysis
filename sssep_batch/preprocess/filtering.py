"""Apply the FPVS FIR filter, then downsample the continuous recording.

The FIR duration is preserved when filtering at the original sampling rate.
Events are detected by the pipeline after resampling. These helpers follow the
FPVS warning-and-continue behavior for filter and resampling failures.
"""

from typing import Callable

import mne

from sssep_batch.config import (
    DOWNSAMPLE_RATE,
    FIR_DESIGN,
    FIR_FILTER_LENGTH_POINTS,
    FIR_HIGH_TRANS_BW,
    FIR_LOW_TRANS_BW,
    FIR_PHASE,
    FIR_WINDOW,
    HIGHCUT,
    LOWCUT,
)


def validate_filter_settings(sfreq: float) -> None:
    """Reject inverted cutoffs, matching FPVS's pre-processing validation.

    ``sfreq`` remains accepted for existing callers. MNE validates the sampling
    rate and Nyquist constraints when the filter is applied.
    """
    if LOWCUT is not None and HIGHCUT is not None and float(LOWCUT) >= float(HIGHCUT):
        raise ValueError(
            "Invalid filter cutoffs: high-pass must be below low-pass. "
            f"Got LOWCUT={LOWCUT}, HIGHCUT={HIGHCUT}."
        )


def _scaled_filter_length(
    base_length: int,
    *,
    current_sfreq: float,
    downsample_rate: int | float | None,
) -> int:
    """Preserve FPVS's historical FIR duration before downsampling."""
    try:
        target_sfreq = float(downsample_rate)
    except (TypeError, ValueError):
        target_sfreq = 0.0
    if target_sfreq <= 0 or current_sfreq <= target_sfreq:
        return base_length
    scaled = int(round((base_length - 1) * (current_sfreq / target_sfreq))) + 1
    if scaled % 2 == 0:
        scaled += 1
    return max(base_length, scaled)


def apply_basic_fir_filter(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    hp: float | None,
    lp: float | None,
    log_func: Callable[[str], None],
    debug_enabled: bool = False,
) -> dict[str, float]:
    """Apply FPVS's FIR settings and return cutoff metadata for resampling."""
    l_freq = hp if (hp is not None and hp > 0) else None
    h_freq = lp
    filter_info_to_preserve: dict[str, float] = {}
    if not (l_freq or h_freq):
        log_func(f"Skip filter for {filename_for_log}.")
        return filter_info_to_preserve

    try:
        sf_current = float(raw.info.get("sfreq", 0.0))
        filter_length = _scaled_filter_length(
            FIR_FILTER_LENGTH_POINTS,
            current_sfreq=sf_current,
            downsample_rate=DOWNSAMPLE_RATE,
        )
        log_func(
            f"FILTER_SNAPSHOT file={filename_for_log} param_high_pass={hp!r} "
            f"param_low_pass={lp!r} computed_l_freq={l_freq!r} "
            f"computed_h_freq={h_freq!r} sfreq={sf_current} filter_length={filter_length}"
        )
        raw.filter(
            l_freq,
            h_freq,
            method="fir",
            phase=FIR_PHASE,
            fir_window=FIR_WINDOW,
            fir_design=FIR_DESIGN,
            l_trans_bandwidth=FIR_LOW_TRANS_BW,
            h_trans_bandwidth=FIR_HIGH_TRANS_BW,
            filter_length=filter_length,
            skip_by_annotation="edge",
            verbose=False,
        )
        applied_highpass = raw.info.get("highpass")
        applied_lowpass = raw.info.get("lowpass")
        if l_freq is not None and applied_highpass is not None:
            filter_info_to_preserve["highpass"] = float(applied_highpass)
        if h_freq is not None and applied_lowpass is not None:
            filter_info_to_preserve["lowpass"] = float(applied_lowpass)
        log_func(
            f"FILTER_APPLIED file={filename_for_log} "
            f"applied_highpass={applied_highpass!r} applied_lowpass={applied_lowpass!r}"
        )
        log_func(f"Filter OK for {filename_for_log}.")
    except Exception as exc:
        log_func(f"Warn: Filter failed for {filename_for_log}: {exc}")
    return filter_info_to_preserve


def downsample_if_needed(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    downsample_rate: int | float | None,
    log_func: Callable[[str], None],
    debug_enabled: bool = False,
    filter_info_to_preserve: dict[str, float] | None = None,
) -> None:
    """Resample after filtering, preserving FPVS's filter metadata and warnings."""
    if not downsample_rate:
        log_func(f"Skip downsample for {filename_for_log}.")
        return
    sf = float(raw.info["sfreq"])
    if sf <= downsample_rate:
        log_func(
            f"No downsampling needed for {filename_for_log} "
            f"(sfreq={sf:.3f}, target={downsample_rate})."
        )
        return
    try:
        raw.resample(downsample_rate, npad="auto", window="hann", verbose=False)
        if filter_info_to_preserve:
            try:
                with raw.info._unlock():
                    for key, value in filter_info_to_preserve.items():
                        raw.info[key] = value
            except (AttributeError, RuntimeError, TypeError, ValueError):
                log_func(f"Warn: Could not restore filter metadata for {filename_for_log}.")
        log_func(f"Resampled {filename_for_log} to {float(raw.info['sfreq']):.3f} Hz.")
    except Exception as exc:
        log_func(f"Warn: Resampling failed for {filename_for_log}: {exc}")
