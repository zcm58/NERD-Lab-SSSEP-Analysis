"""Summarize SSSEP electrode amplitudes and gap/break comparisons.

These summaries average the selected electrodes' amplitudes after FFT. The
local amplitude SNR uses the SSSEP frequency bands below; it is not the FPVS
Toolbox's neighboring-bin SNR method. These calculations do not change the
per-electrode amplitude spectra.
"""

import numpy as np

from sssep_batch.config import (
    EPS,
    FMAX,
    FMIN,
    LOCAL_NOISE_EXCLUSION_HALF_WIDTH_HZ,
    LOCAL_NOISE_HALF_WIDTH_HZ,
    TARGET_BAND_HALF_WIDTH_HZ,
)
from sssep_batch.models import Spectrum


AMPLITUDE_METRIC_FIELDS = (
    "nearest_freq_hz", "nearest_amplitude_uv", "target_band_half_width_hz",
    "target_band_mean_amplitude_uv", "target_band_sum_amplitude_uv",
    "local_noise_half_width_hz", "local_noise_exclusion_half_width_hz",
    "local_noise_mean_amplitude_uv", "local_amplitude_snr",
    "local_amplitude_snr_db", "peak_frequency_hz", "peak_amplitude_uv",
)


def safe_ratio(numerator: float, denominator: float) -> float:
    """Divide finite values, returning NaN when the denominator is near zero."""
    if not np.isfinite(numerator) or not np.isfinite(denominator) or abs(denominator) < EPS:
        return float("nan")
    return float(numerator / denominator)


def ratio_to_db(ratio: float) -> float:
    """Convert a positive amplitude ratio to decibels using 20 log10."""
    if not np.isfinite(ratio) or ratio <= 0:
        return float("nan")
    return float(20.0 * np.log10(ratio))


def extract_target_metrics(
    spectrum: Spectrum | None,
    target_hz: float,
    channel_indices: list[int] | None = None,
) -> dict[str, float]:
    """Summarize mean electrode amplitude near the expected SSSEP frequency.

    The peak search stays inside FMIN/FMAX, as in the original summary. The
    input spectrum may retain the entire nonnegative FFT frequency range.
    A missing spectrum returns the same fields with NaN values.
    """
    if spectrum is None:
        return {field: float("nan") for field in AMPLITUDE_METRIC_FIELDS}
    freqs = spectrum.freqs
    amplitudes = spectrum.amplitude_uv
    if channel_indices is not None:
        if len(channel_indices) == 0:
            raise ValueError("Select at least one channel for amplitude summaries.")
        amplitudes = amplitudes[channel_indices]
    amplitude_uv = np.mean(amplitudes, axis=0)

    nearest_idx = int(np.argmin(np.abs(freqs - target_hz)))
    nearest_amplitude = float(amplitude_uv[nearest_idx])
    target_band = np.abs(freqs - target_hz) <= TARGET_BAND_HALF_WIDTH_HZ
    if np.any(target_band):
        band_mean_amplitude = float(np.mean(amplitude_uv[target_band]))
        band_sum_amplitude = float(np.sum(amplitude_uv[target_band]))
    else:
        band_mean_amplitude = float("nan")
        band_sum_amplitude = float("nan")

    local_noise_band = (
        (np.abs(freqs - target_hz) <= LOCAL_NOISE_HALF_WIDTH_HZ)
        & (np.abs(freqs - target_hz) > LOCAL_NOISE_EXCLUSION_HALF_WIDTH_HZ)
    )
    local_noise_amplitude = (
        float(np.mean(amplitude_uv[local_noise_band]))
        if np.any(local_noise_band) else float("nan")
    )
    amplitude_snr = safe_ratio(nearest_amplitude, local_noise_amplitude)

    peak_bins = np.flatnonzero((freqs >= FMIN) & (freqs <= FMAX))
    if not len(peak_bins):
        raise ValueError("The spectrum contains no bins in the summary frequency range.")
    peak_idx = int(peak_bins[np.argmax(amplitude_uv[peak_bins])])

    return {
        "nearest_freq_hz": float(freqs[nearest_idx]),
        "nearest_amplitude_uv": nearest_amplitude,
        "target_band_half_width_hz": TARGET_BAND_HALF_WIDTH_HZ,
        "target_band_mean_amplitude_uv": band_mean_amplitude,
        "target_band_sum_amplitude_uv": band_sum_amplitude,
        "local_noise_half_width_hz": LOCAL_NOISE_HALF_WIDTH_HZ,
        "local_noise_exclusion_half_width_hz": LOCAL_NOISE_EXCLUSION_HALF_WIDTH_HZ,
        "local_noise_mean_amplitude_uv": local_noise_amplitude,
        "local_amplitude_snr": amplitude_snr,
        "local_amplitude_snr_db": ratio_to_db(amplitude_snr),
        "peak_frequency_hz": float(freqs[peak_idx]),
        "peak_amplitude_uv": float(amplitude_uv[peak_idx]),
    }


def add_baseline_comparison(
    row: dict[str, object],
    active_prefix: str,
    baseline_metrics: dict[str, float] | None,
) -> None:
    """Add amplitude ratios to the separately measured gap/break baseline.

    Missing baseline values remain NaN. Both nearest-bin and band-sum ratios
    use amplitude units, so their decibel conversion is 20 log10.
    """
    for metric, ratio_label in (
        ("nearest_amplitude_uv", "active_vs_baseline"),
        ("target_band_sum_amplitude_uv", "band_sum_active_vs_baseline"),
    ):
        active_value = float(row.get(f"{active_prefix}_{metric}", float("nan")))
        baseline_value = (
            baseline_metrics[metric] if baseline_metrics is not None else float("nan")
        )
        ratio = safe_ratio(active_value, baseline_value)
        row[f"baseline_{active_prefix}_{metric}"] = baseline_value
        row[f"{active_prefix}_{ratio_label}_amplitude_ratio"] = ratio
        row[f"{active_prefix}_{ratio_label}_amplitude_db"] = ratio_to_db(ratio)
