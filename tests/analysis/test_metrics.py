"""Tests for converting spectra into SSSEP metric values.

These tests use tiny hand-built spectra so the expected values can be checked
directly. That makes the math behavior easier to understand and protects the
CSV metric contract.
"""

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


def test_safe_ratio_and_ratio_to_db_handle_invalid_inputs():
    """Invalid ratios should become NaN instead of crashing or returning infinity."""
    assert math.isnan(safe_ratio(1.0, 0.0))
    assert math.isnan(ratio_to_db(0.0))
    assert ratio_to_db(10.0) == pytest.approx(10.0)


def test_extract_target_metrics_uses_target_band_and_local_noise_floor():
    """Target metrics should use the configured target and local-noise bands."""
    spectrum = Spectrum(
        freqs=np.array([9.0, 9.8, 10.0, 10.2, 11.0]),
        power=np.array([2.0, 4.0, 10.0, 6.0, 8.0]),
        method="test",
    )

    metrics = extract_target_metrics(spectrum, target_hz=10.0)

    assert metrics["nearest_freq_hz"] == 10.0
    assert metrics["nearest_power"] == 10.0
    assert metrics["target_band_mean_power"] == np.mean([4.0, 10.0, 6.0])
    assert metrics["target_band_sum_power"] == 20.0
    assert metrics["local_noise_floor"] == np.mean([2.0, 8.0])
    assert metrics["snr"] == 2.0
    assert metrics["peak_frequency_hz"] == 10.0
    assert metrics["peak_power"] == 10.0


def test_add_baseline_comparison_populates_ratios_and_nan_defaults():
    """Baseline comparison columns should be filled or set to NaN when absent."""
    row = {
        "sssep_fft_nearest_power": 8.0,
        "sssep_fft_target_band_sum_power": 20.0,
    }
    baseline_metrics = {
        "nearest_power": 2.0,
        "target_band_sum_power": 4.0,
    }

    add_baseline_comparison(row, "sssep_fft", baseline_metrics)

    assert row["baseline_sssep_fft_nearest_power"] == 2.0
    assert row["sssep_fft_active_vs_baseline_ratio"] == 4.0
    assert row["sssep_fft_band_sum_active_vs_baseline_ratio"] == 5.0
    assert row["sssep_fft_active_vs_baseline_db"] == pytest.approx(6.0205999)

    no_baseline_row = {
        "welch_nearest_power": 3.0,
        "welch_target_band_sum_power": 9.0,
    }
    add_baseline_comparison(no_baseline_row, "welch", None)

    assert math.isnan(no_baseline_row["baseline_welch_nearest_power"])
    assert math.isnan(no_baseline_row["welch_active_vs_baseline_ratio"])
