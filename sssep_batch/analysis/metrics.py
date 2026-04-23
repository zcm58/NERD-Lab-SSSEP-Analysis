"""Spectrum-derived metrics."""

import numpy as np

from sssep_batch.config import (
    EPS,
    LOCAL_NOISE_EXCLUSION_HALF_WIDTH_HZ,
    LOCAL_NOISE_HALF_WIDTH_HZ,
    TARGET_BAND_HALF_WIDTH_HZ,
)
from sssep_batch.models import Spectrum


def safe_ratio(numerator: float, denominator: float) -> float:
    """Divide two numbers while protecting against divide-by-zero errors."""
    if not np.isfinite(denominator) or abs(denominator) < EPS:
        return float("nan")
    return float(numerator / denominator)


def ratio_to_db(ratio: float) -> float:
    """Convert a power ratio to decibels."""
    if not np.isfinite(ratio) or ratio <= 0:
        return float("nan")
    return float(10.0 * np.log10(ratio))


def extract_target_metrics(
    spectrum: Spectrum,
    target_hz: float,
) -> dict[str, float]:
    """
    Measure power at and around the expected target frequency.
    """

    freqs = spectrum.freqs
    power = spectrum.power

    nearest_idx = int(np.argmin(np.abs(freqs - target_hz)))
    nearest_freq = float(freqs[nearest_idx])
    nearest_power = float(power[nearest_idx])

    target_band = np.abs(freqs - target_hz) <= TARGET_BAND_HALF_WIDTH_HZ
    if np.any(target_band):
        band_mean_power = float(np.mean(power[target_band]))
        band_sum_power = float(np.sum(power[target_band]))
    else:
        band_mean_power = float("nan")
        band_sum_power = float("nan")

    local_noise_band = (
        (np.abs(freqs - target_hz) <= LOCAL_NOISE_HALF_WIDTH_HZ)
        & (np.abs(freqs - target_hz) > LOCAL_NOISE_EXCLUSION_HALF_WIDTH_HZ)
    )
    if np.any(local_noise_band):
        local_noise_floor = float(np.mean(power[local_noise_band]))
    else:
        local_noise_floor = float("nan")

    snr = safe_ratio(nearest_power, local_noise_floor)
    snr_db = ratio_to_db(snr)

    peak_idx = int(np.argmax(power))

    return {
        "nearest_freq_hz": nearest_freq,
        "nearest_power": nearest_power,
        "target_band_half_width_hz": TARGET_BAND_HALF_WIDTH_HZ,
        "target_band_mean_power": band_mean_power,
        "target_band_sum_power": band_sum_power,
        "local_noise_half_width_hz": LOCAL_NOISE_HALF_WIDTH_HZ,
        "local_noise_exclusion_half_width_hz": LOCAL_NOISE_EXCLUSION_HALF_WIDTH_HZ,
        "local_noise_floor": local_noise_floor,
        "snr": snr,
        "snr_db": snr_db,
        "peak_frequency_hz": float(freqs[peak_idx]),
        "peak_power": float(power[peak_idx]),
    }


def add_baseline_comparison(
    row: dict[str, object],
    active_prefix: str,
    baseline_metrics: dict[str, float] | None,
) -> None:
    """
    Add baseline comparison values to a summary row.
    """

    active_power = row.get(f"{active_prefix}_nearest_power", float("nan"))
    active_band_sum = row.get(f"{active_prefix}_target_band_sum_power", float("nan"))

    if baseline_metrics is None:
        row[f"baseline_{active_prefix}_nearest_power"] = float("nan")
        row[f"baseline_{active_prefix}_target_band_sum_power"] = float("nan")
        row[f"{active_prefix}_active_vs_baseline_ratio"] = float("nan")
        row[f"{active_prefix}_active_vs_baseline_db"] = float("nan")
        row[f"{active_prefix}_band_sum_active_vs_baseline_ratio"] = float("nan")
        row[f"{active_prefix}_band_sum_active_vs_baseline_db"] = float("nan")
        return

    baseline_power = baseline_metrics["nearest_power"]
    baseline_band_sum = baseline_metrics["target_band_sum_power"]

    nearest_ratio = safe_ratio(float(active_power), baseline_power)
    band_sum_ratio = safe_ratio(float(active_band_sum), baseline_band_sum)

    row[f"baseline_{active_prefix}_nearest_power"] = baseline_power
    row[f"baseline_{active_prefix}_target_band_sum_power"] = baseline_band_sum
    row[f"{active_prefix}_active_vs_baseline_ratio"] = nearest_ratio
    row[f"{active_prefix}_active_vs_baseline_db"] = ratio_to_db(nearest_ratio)
    row[f"{active_prefix}_band_sum_active_vs_baseline_ratio"] = band_sum_ratio
    row[f"{active_prefix}_band_sum_active_vs_baseline_db"] = ratio_to_db(band_sum_ratio)
