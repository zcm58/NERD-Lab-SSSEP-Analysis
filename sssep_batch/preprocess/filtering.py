"""Downsample, clean, and filter EEG data before epoch extraction.

This module owns preprocessing steps that can affect analysis correctness:
event-aware downsampling, finite-value cleanup, bandpass filtering, optional
notch filtering, and the FIR edge margin calculation. The pipeline detects
Status events before downsampling and passes those events here so MNE can keep
their sample positions aligned with the resampled recording.
"""

from typing import Callable

import mne
import numpy as np

from sssep_batch.config import (
    APPLY_NOTCH,
    FIR_DESIGN,
    FIR_FILTER_LENGTH_POINTS,
    FIR_HIGH_TRANS_BW,
    FIR_LOW_TRANS_BW,
    FIR_PHASE,
    FIR_WINDOW,
    HIGHCUT,
    LOWCUT,
    NOTCH_FREQ,
    TRIGGER_HZ_MAP,
)


def validate_filter_settings(sfreq: float) -> None:
    """Stop if configured filter cutoffs would remove target SSSEP frequencies."""
    target_freqs = sorted(set(TRIGGER_HZ_MAP.values()))
    lowest_target = min(target_freqs)
    highest_target = max(target_freqs)
    nyquist = sfreq / 2.0

    if LOWCUT is not None and LOWCUT >= lowest_target:
        raise RuntimeError(
            f"LOWCUT={LOWCUT} Hz is too high because the lowest target is "
            f"{lowest_target} Hz. Lower LOWCUT before processing."
        )

    if HIGHCUT is not None and HIGHCUT <= highest_target:
        raise RuntimeError(
            f"HIGHCUT={HIGHCUT} Hz is too low because the highest target is "
            f"{highest_target} Hz. Raise HIGHCUT before processing."
        )

    if HIGHCUT is not None and HIGHCUT >= nyquist:
        raise RuntimeError(
            f"HIGHCUT={HIGHCUT} Hz must be below Nyquist ({nyquist:.3f} Hz) "
            f"for the current sampling rate ({sfreq:.3f} Hz)."
        )


def downsample_if_needed(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    downsample_rate: int | float | None,
    log_func: Callable[[str], None],
    events: np.ndarray | None = None,
    debug_enabled: bool = False,
) -> np.ndarray | None:
    """
    Downsample the recording if its sampling rate is above the target rate.

    If an event matrix is provided, the event onsets are resampled jointly with
    the raw data and the resampled event matrix is returned.
    """
    resampled_events = events
    if downsample_rate:
        sf = float(raw.info["sfreq"])
        log_func(
            f"Downsample check for {filename_for_log}: "
            f"Curr {sf:.3f} Hz, Tgt {downsample_rate} Hz."
        )
        if sf > downsample_rate:
            try:
                if events is None:
                    raw.resample(
                        downsample_rate,
                        npad="auto",
                        window="hann",
                        verbose=False,
                    )
                else:
                    raw, resampled_events = raw.resample(
                        downsample_rate,
                        npad="auto",
                        window="hann",
                        events=events,
                        verbose=False,
                    )
                new_sf = float(raw.info["sfreq"])
                log_func(f"Resampled {filename_for_log} to {new_sf:.3f} Hz.")
                if debug_enabled:
                    print(f"[DS] {filename_for_log}: sfreq {sf:.3f} -> {new_sf:.3f}")
            except Exception as resample_err:
                log_func(
                    f"Warn: Resampling failed for {filename_for_log}: "
                    f"{resample_err}"
                )
                if debug_enabled:
                    print(
                        f"[DS] {filename_for_log}: RESAMPLE FAILED "
                        f"(sfreq={sf:.3f}, target={downsample_rate})"
                    )
        else:
            log_func(
                f"No downsampling needed for {filename_for_log} "
                f"(sfreq={sf:.3f}, target={downsample_rate})."
            )
            if debug_enabled:
                print(
                    f"[DS] {filename_for_log}: no resample "
                    f"(sfreq={sf:.3f}, target={downsample_rate})"
                )
    else:
        log_func(f"Skip downsample for {filename_for_log}.")
        if debug_enabled:
            print(f"[DS] {filename_for_log}: skip (no downsample_rate set)")
    return resampled_events


def replace_nonfinite_values(
    raw: mne.io.BaseRaw,
    log_func: Callable[[str], None],
) -> None:
    """Replace NaN or infinite EEG values with zero before filtering."""
    eeg_picks = mne.pick_types(raw.info, eeg=True, stim=False, exclude=[])
    if len(eeg_picks) == 0:
        raise RuntimeError("No EEG channels available for finite-value check.")

    eeg_data = raw.get_data(picks=eeg_picks)
    if np.isfinite(eeg_data).all():
        log_func("Finite-value check passed: no NaN/Inf values found in EEG data.")
        return

    log_func("NaN/Inf values found in EEG data. Replacing them with 0 using MNE apply_function.")

    def _nan_to_num(channel_data: np.ndarray) -> np.ndarray:
        """Return one EEG channel with NaN/Inf values replaced by zero."""
        return np.nan_to_num(channel_data, nan=0.0, posinf=0.0, neginf=0.0)

    raw.apply_function(
        _nan_to_num,
        picks=eeg_picks,
        channel_wise=True,
        verbose=False,
    )


def get_fir_edge_margin_samples(
    sfreq: float,
    l_freq: float | None,
    h_freq: float | None,
) -> int:
    """
    Return a conservative exclusion margin for epochs near FIR-filtered edges.

    A linear-phase FIR filter of length N has an impulse response that spans N
    samples. Near the beginning and end of a finite recording, the filter cannot
    see a full neighborhood of real data, so MNE must rely on padding and
    boundary handling. Even when the final signal length is unchanged and the
    epoch is numerically in-bounds, windows close to the edges can still contain
    startup or shutdown transients caused by the filter using incomplete
    context.

    This script uses a fixed FIR length of 8449 points. For a symmetric FIR, a
    conservative edge margin is half the filter length, i.e. (N - 1) / 2
    samples on each side. Epochs whose full analysis window enters that region
    are excluded so they are not counted as clean repetitions.
    """

    if not ((l_freq is not None and l_freq > 0) or h_freq is not None):
        return 0
    if sfreq <= 0:
        raise RuntimeError(f"Sampling rate must be positive, got {sfreq}.")
    return max(0, (FIR_FILTER_LENGTH_POINTS - 1) // 2)


def apply_basic_fir_filter(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    hp: float | None,
    lp: float | None,
    log_func: Callable[[str], None],
    debug_enabled: bool = False,
) -> None:
    """Apply the fixed FIR bandpass filter used by the reference preprocessing."""
    l_freq = hp if (hp is not None and hp > 0) else None
    h_freq = lp
    if l_freq or h_freq:
        try:
            low_trans_bw = FIR_LOW_TRANS_BW
            high_trans_bw = FIR_HIGH_TRANS_BW
            filter_len_points = FIR_FILTER_LENGTH_POINTS
            effective_l = l_freq if l_freq is not None else "DC"
            effective_h = h_freq if h_freq is not None else "Nyq"
            sf_current = float(raw.info.get("sfreq", 0.0))
            snapshot_payload = (
                f"file={filename_for_log} "
                f"param_high_pass={hp!r} "
                f"param_low_pass={lp!r} "
                f"computed_l_freq={l_freq!r} "
                f"computed_h_freq={h_freq!r} "
                f"sfreq={sf_current}"
            )
            snapshot_message = f"FILTER_SNAPSHOT {snapshot_payload}"
            log_func(snapshot_message)
            if debug_enabled:
                print(f"[FILTER_SNAPSHOT] {snapshot_payload}")
            if h_freq is not None and h_freq > sf_current / 2.0:
                nyquist_warning = (
                    "FILTER_NYQUIST_WARNING "
                    f"file={filename_for_log} "
                    f"computed_h_freq={h_freq!r} "
                    f"sfreq={sf_current}"
                )
                log_func(nyquist_warning)
            if l_freq is not None and h_freq is not None and l_freq >= h_freq:
                range_warning = (
                    "FILTER_RANGE_WARNING "
                    f"file={filename_for_log} "
                    f"computed_l_freq={l_freq!r} "
                    f"computed_h_freq={h_freq!r}"
                )
                log_func(range_warning)
            log_func(
                f"Filtering {filename_for_log} "
                f"({effective_l}-{effective_h} Hz) at sfreq={sf_current:.3f}..."
            )
            if debug_enabled:
                print(
                    f"[FILTER] {filename_for_log}: FIR bandpass "
                    f"l_freq={effective_l} h_freq={effective_h} "
                    f"sfreq={sf_current:.3f}"
                )
            raw.filter(
                l_freq,
                h_freq,
                method="fir",
                phase=FIR_PHASE,
                fir_window=FIR_WINDOW,
                fir_design=FIR_DESIGN,
                l_trans_bandwidth=low_trans_bw,
                h_trans_bandwidth=high_trans_bw,
                filter_length=filter_len_points,
                skip_by_annotation="edge",
                picks="eeg",
                verbose=False,
            )
            applied_highpass = raw.info.get("highpass", None)
            applied_lowpass = raw.info.get("lowpass", None)
            applied_payload = (
                f"file={filename_for_log} "
                f"applied_highpass={applied_highpass!r} "
                f"applied_lowpass={applied_lowpass!r} "
                f"sfreq={sf_current}"
            )
            applied_message = f"FILTER_APPLIED {applied_payload}"
            log_func(applied_message)
            if debug_enabled:
                print(f"[FILTER_APPLIED] {applied_payload}")
            expected_highpass = l_freq if l_freq is not None else 0.0
            expected_lowpass = (
                h_freq
                if h_freq is not None
                else float(raw.info.get("sfreq", 0.0)) / 2.0
            )
            tol = 1e-6
            mismatch = False
            if applied_highpass is None or applied_lowpass is None:
                mismatch = True
            elif (
                abs(applied_highpass - expected_highpass) > tol
                or abs(applied_lowpass - expected_lowpass) > tol
            ):
                mismatch = True
            if mismatch:
                mismatch_warning = (
                    "FILTER_MISMATCH_WARNING "
                    f"file={filename_for_log} "
                    f"expected_highpass={expected_highpass!r} "
                    f"expected_lowpass={expected_lowpass!r} "
                    f"applied_highpass={applied_highpass!r} "
                    f"applied_lowpass={applied_lowpass!r}"
                )
                log_func(mismatch_warning)
            log_func(
                f"DEBUG [raw.info cutoffs {filename_for_log}]: "
                f"highpass={raw.info.get('highpass')} "
                f"lowpass={raw.info.get('lowpass')}"
            )
            log_func(f"Filter OK for {filename_for_log}.")
        except Exception as exc:
            log_func(f"ERROR: Filter failed for {filename_for_log}: {exc}")
            if debug_enabled:
                print(
                    f"[FILTER] {filename_for_log}: FAILED "
                    f"l_freq={l_freq} h_freq={h_freq}"
                )
            raise RuntimeError(f"Basic FIR filtering failed: {exc}") from exc
    else:
        log_func(f"Skip filter for {filename_for_log}.")
        if debug_enabled:
            print(f"[FILTER] {filename_for_log}: skip (no l_freq/h_freq)")


def apply_notch_filter(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    log_func: Callable[[str], None],
) -> None:
    """Apply the optional line-noise notch filter to EEG channels."""
    if not APPLY_NOTCH:
        log_func(f"Skipping notch filter for {filename_for_log} because APPLY_NOTCH=False.")
        return

    try:
        raw.notch_filter(freqs=[NOTCH_FREQ], picks="eeg", verbose=False)
        log_func(f"Applied {NOTCH_FREQ} Hz notch filter to EEG channels.")
    except Exception as exc:
        log_func(f"Warning: notch filter failed for {filename_for_log}: {exc}")
