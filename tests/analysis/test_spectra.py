"""Numerical checks for the FPVS amplitude FFT contract."""

import numpy as np
import pytest

from sssep_batch.analysis.spectra import compute_sssep_fft_from_averaged_epochs
from sssep_batch.config import PROCESSING_METHOD


def test_fft_preserves_each_electrodes_microvolt_amplitude_without_taper():
    times = np.arange(256) / 256.0
    signal = np.sin(2 * np.pi * 10 * times)
    one_epoch = np.array([2e-6 * signal, 5e-6 * signal])
    epochs = np.stack([one_epoch] * 5)

    spectrum = compute_sssep_fft_from_averaged_epochs(epochs, sfreq=256.0)

    assert spectrum.amplitude_uv.shape == (2, 129)
    np.testing.assert_array_equal(spectrum.freqs, np.arange(129))
    np.testing.assert_allclose(spectrum.amplitude_uv[:, 10], [2.0, 5.0], atol=1e-12)
    assert np.max(spectrum.amplitude_uv[:, [9, 11]]) < 1e-12
    assert spectrum.method == PROCESSING_METHOD


def test_fft_matches_fpvs_doubling_of_dc_and_nyquist_without_demeaning():
    samples = np.arange(8)
    epoch = (3e-6 + 4e-6 * (-1.0) ** samples)[None, :]

    spectrum = compute_sssep_fft_from_averaged_epochs(epoch[None, :, :], sfreq=8.0)

    np.testing.assert_allclose(spectrum.amplitude_uv[0], [6, 0, 0, 0, 8], atol=1e-12)


def test_fft_does_not_pad_odd_sample_counts():
    n_times = 255
    signal = 3e-6 * np.cos(2 * np.pi * 16 * np.arange(n_times) / n_times)

    spectrum = compute_sssep_fft_from_averaged_epochs(signal[None, None, :], sfreq=256.0)

    assert spectrum.amplitude_uv.shape == (1, 128)
    assert spectrum.freqs[-1] == pytest.approx(127 * 256 / 255)
    assert spectrum.amplitude_uv[0, 16] == pytest.approx(3.0)
    other_bins = np.delete(spectrum.amplitude_uv[0], 16)
    assert np.max(other_bins) < 1e-12


def test_trial_averaging_precedes_fft_and_cancels_opposite_phases():
    signal = 2e-6 * np.sin(2 * np.pi * 10 * np.arange(256) / 256)
    epochs = np.stack([signal, -signal])[:, None, :]

    spectrum = compute_sssep_fft_from_averaged_epochs(epochs, sfreq=256.0)

    np.testing.assert_array_equal(spectrum.amplitude_uv, np.zeros((1, 129)))


def test_float32_epochs_are_promoted_before_trial_averaging():
    # A float32 trial mean loses the small middle trial during cancellation.
    epochs = np.repeat(np.array([1.0, 1e-8, -1.0], dtype=np.float32)[:, None, None], 8, axis=2)
    expected_dc_uv = (1.0 + float(epochs[1, 0, 0]) - 1.0) / 3.0 * 1e6 * 2

    spectrum = compute_sssep_fft_from_averaged_epochs(epochs, sfreq=8.0)

    assert spectrum.amplitude_uv.dtype == np.float64
    assert spectrum.amplitude_uv[0, 0] == pytest.approx(expected_dc_uv, abs=1e-14)
    assert spectrum.amplitude_uv[0, 0] > 0


def test_output_frequency_selection_does_not_change_amplitudes():
    epochs = np.random.default_rng(63).normal(scale=1e-6, size=(3, 2, 255))
    full = compute_sssep_fft_from_averaged_epochs(epochs, sfreq=256.0)
    selected = compute_sssep_fft_from_averaged_epochs(epochs, sfreq=256.0, fmin=5.0, fmax=15.0)
    keep = (full.freqs >= 5.0) & (full.freqs <= 15.0)

    np.testing.assert_array_equal(selected.freqs, full.freqs[keep])
    np.testing.assert_array_equal(selected.amplitude_uv, full.amplitude_uv[:, keep])


def test_nonfinite_epoch_values_are_not_silently_replaced():
    epochs = np.ones((1, 1, 8))
    epochs[0, 0, 2] = np.nan

    spectrum = compute_sssep_fft_from_averaged_epochs(epochs, sfreq=8.0)

    assert np.isnan(spectrum.amplitude_uv).all()


@pytest.mark.parametrize("shape", [(0, 2, 256), (1, 0, 256), (1, 2, 0), (2, 256)])
def test_fft_rejects_missing_epoch_dimensions(shape):
    with pytest.raises(ValueError, match="at least one epoch"):
        compute_sssep_fft_from_averaged_epochs(np.empty(shape), sfreq=256.0)
