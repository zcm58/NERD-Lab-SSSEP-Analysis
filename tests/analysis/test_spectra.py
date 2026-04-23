import numpy as np
import pytest

from sssep_batch.analysis.spectra import (
    compute_sssep_fft_from_averaged_epochs,
    compute_welch_psd_average,
)


def make_sine_epochs(
    *,
    n_epochs: int = 3,
    n_channels: int = 2,
    sfreq: float = 256.0,
    seconds: float = 1.0,
    target_hz: float = 10.0,
) -> np.ndarray:
    times = np.arange(int(sfreq * seconds)) / sfreq
    channel = np.sin(2 * np.pi * target_hz * times)
    epoch = np.tile(channel, (n_channels, 1))
    return np.stack([epoch] * n_epochs, axis=0)


def test_compute_sssep_fft_from_averaged_epochs_returns_bounded_spectrum():
    epochs = make_sine_epochs()

    spectrum = compute_sssep_fft_from_averaged_epochs(epochs, sfreq=256.0, fmin=5.0, fmax=15.0)

    assert spectrum.method == "SSSEP FFT after averaging repeated epochs"
    assert spectrum.freqs.min() >= 5.0
    assert spectrum.freqs.max() <= 15.0
    assert spectrum.freqs[np.argmax(spectrum.power)] == pytest.approx(10.0)


def test_compute_welch_psd_average_returns_bounded_spectrum():
    epochs = make_sine_epochs(seconds=2.0)

    spectrum = compute_welch_psd_average(epochs, sfreq=256.0, fmin=5.0, fmax=15.0)

    assert spectrum.method == "Welch PSD averaged across epochs and channels"
    assert spectrum.freqs.min() >= 5.0
    assert spectrum.freqs.max() <= 15.0
    assert spectrum.freqs[np.argmax(spectrum.power)] == pytest.approx(10.0, abs=0.5)


@pytest.mark.parametrize(
    "func",
    [compute_sssep_fft_from_averaged_epochs, compute_welch_psd_average],
)
def test_spectrum_functions_reject_empty_epoch_sets(func):
    empty_epochs = np.empty((0, 2, 256), dtype=float)

    with pytest.raises(ValueError):
        func(empty_epochs, sfreq=256.0, fmin=5.0, fmax=15.0)
