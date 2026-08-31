"""Checks for amplitude summaries, ratios, and stable missing-data columns."""

import math

import numpy as np
import pytest

from sssep_batch.analysis.metrics import (
    add_baseline_comparison,
    extract_target_metrics,
    ratio_to_db,
    safe_ratio,
)
from sssep_batch.models import Spectrum


def test_amplitude_ratio_decibels_and_invalid_inputs():
    assert math.isnan(safe_ratio(1.0, 0.0))
    assert math.isnan(safe_ratio(float("inf"), 1.0))
    assert math.isnan(ratio_to_db(0.0))
    assert ratio_to_db(10.0) == pytest.approx(20.0)
    assert ratio_to_db(2.0) == pytest.approx(6.020599913)


def make_spectrum():
    return Spectrum(
        freqs=np.array([0.0, 9.0, 9.8, 10.0, 10.2, 11.0, 128.0]),
        amplitude_uv=np.array([
            [1000.0, 2.0, 4.0, 10.0, 6.0, 8.0, 2000.0],
            [3000.0, 6.0, 12.0, 30.0, 18.0, 24.0, 6000.0],
        ]),
        method="test",
    )


def test_metrics_use_mean_selected_amplitudes_and_sssep_noise_band():
    metrics = extract_target_metrics(make_spectrum(), target_hz=10.0)

    assert metrics["nearest_freq_hz"] == 10.0
    assert metrics["nearest_amplitude_uv"] == 20.0
    assert metrics["target_band_mean_amplitude_uv"] == pytest.approx(40 / 3)
    assert metrics["target_band_sum_amplitude_uv"] == 40.0
    assert metrics["local_noise_mean_amplitude_uv"] == 10.0
    assert metrics["local_amplitude_snr"] == 2.0
    assert metrics["local_amplitude_snr_db"] == pytest.approx(6.020599913)
    assert metrics["peak_frequency_hz"] == 10.0
    assert metrics["peak_amplitude_uv"] == 20.0
    assert not any("power" in name for name in metrics)


def test_metrics_can_select_one_electrode_without_averaging_other_channels():
    metrics = extract_target_metrics(make_spectrum(), target_hz=10.0, channel_indices=[0])
    assert metrics["nearest_amplitude_uv"] == 10.0
    assert metrics["target_band_sum_amplitude_uv"] == 20.0
    with pytest.raises(ValueError, match="at least one channel"):
        extract_target_metrics(make_spectrum(), target_hz=10.0, channel_indices=[])


def test_absent_spectrum_has_the_same_complete_schema():
    missing = extract_target_metrics(None, target_hz=10.0)
    present = extract_target_metrics(make_spectrum(), target_hz=10.0)
    assert missing.keys() == present.keys()
    assert all(math.isnan(value) for value in missing.values())


def test_blank_external_stimulation_frequency_keeps_stable_missing_metrics():
    metrics = extract_target_metrics(make_spectrum(), target_hz=None)

    assert all(math.isnan(value) for value in metrics.values())


def test_target_frequency_must_exist_in_the_recording_fft():
    with pytest.raises(ValueError, match=r"outside this recording's FFT range"):
        extract_target_metrics(make_spectrum(), target_hz=150.0)


def test_baseline_comparison_uses_amplitude_ratios_and_twenty_log10():
    row = {"sssep_fft_nearest_amplitude_uv": 8.0, "sssep_fft_target_band_sum_amplitude_uv": 20.0}
    baseline = {"nearest_amplitude_uv": 2.0, "target_band_sum_amplitude_uv": 4.0}

    add_baseline_comparison(row, "sssep_fft", baseline)

    assert row["baseline_sssep_fft_nearest_amplitude_uv"] == 2.0
    assert row["sssep_fft_active_vs_baseline_amplitude_ratio"] == 4.0
    assert row["sssep_fft_active_vs_baseline_amplitude_db"] == pytest.approx(12.041199826)
    assert row["sssep_fft_band_sum_active_vs_baseline_amplitude_ratio"] == 5.0
    assert row["sssep_fft_band_sum_active_vs_baseline_amplitude_db"] == pytest.approx(13.979400087)

    no_baseline_row = {"sssep_fft_nearest_amplitude_uv": 8.0, "sssep_fft_target_band_sum_amplitude_uv": 20.0}
    add_baseline_comparison(no_baseline_row, "sssep_fft", None)
    assert row.keys() == no_baseline_row.keys()
    comparison_names = set(row) - {"sssep_fft_nearest_amplitude_uv", "sssep_fft_target_band_sum_amplitude_uv"}
    assert len(comparison_names) == 6
    assert all(math.isnan(no_baseline_row[name]) for name in comparison_names)
