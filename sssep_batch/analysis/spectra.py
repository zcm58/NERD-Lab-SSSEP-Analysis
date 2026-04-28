"""Compute frequency spectra from extracted EEG epochs.

An epoch is one fixed-length EEG window after a trigger. The processing pipeline
collects repeated epochs for a condition, then this module converts those time
series into frequency-domain power values.

Two spectrum styles are produced:

- the primary SSSEP FFT, where repeated epochs are averaged first and then a
  fast Fourier transform is computed; and
- a supplemental Welch PSD, which estimates power by averaging shorter
  overlapping segments across epochs and channels.

These functions are math-sensitive. Their output feeds the exported metrics, so
docstring changes are safe but formula changes should always be tested.
"""

import numpy as np
from scipy.signal import welch

from sssep_batch.config import EPS, N_OVERLAP_FRAC, N_PER_SEG_SEC
from sssep_batch.models import Spectrum


def compute_sssep_fft_from_averaged_epochs(
    epochs: np.ndarray,
    sfreq: float,
    fmin: float,
    fmax: float,
) -> Spectrum:
    """
    Compute the primary SSSEP spectrum by averaging epochs first, then FFT.

    Shape reminder for beginners: `epochs` must be a 3-D array with dimensions
    `(n_epochs, n_channels, n_times)`. The function averages repeated trials,
    removes each channel's mean offset, applies a Hann window, computes power,
    then keeps only frequencies between `fmin` and `fmax`.
    """

    if epochs.ndim != 3 or epochs.shape[0] == 0:
        raise ValueError("compute_sssep_fft_from_averaged_epochs needs at least one epoch.")

    evoked = np.mean(epochs, axis=0)
    evoked = evoked - np.mean(evoked, axis=1, keepdims=True)

    n_times = evoked.shape[1]
    window = np.hanning(n_times)
    windowed = evoked * window[np.newaxis, :]

    freqs = np.fft.rfftfreq(n_times, d=1.0 / sfreq)
    fft_values = np.fft.rfft(windowed, axis=1)

    scale = max(float(np.sum(window ** 2) * sfreq), EPS)
    channel_power = (np.abs(fft_values) ** 2) / scale
    mean_power = np.mean(channel_power, axis=0)

    keep = (freqs >= fmin) & (freqs <= fmax)
    return Spectrum(
        freqs=freqs[keep],
        power=mean_power[keep],
        method="SSSEP FFT after averaging repeated epochs",
    )


def compute_welch_psd_average(
    epochs: np.ndarray,
    sfreq: float,
    fmin: float,
    fmax: float,
) -> Spectrum:
    """
    Compute a supplemental Welch PSD averaged across epochs and channels.

    Welch PSD is not the primary SSSEP metric here; it is an additional view of
    the same data. It divides each epoch into short overlapping pieces, computes
    power for those pieces, then averages the result for a smoother spectrum.
    """

    if epochs.ndim != 3 or epochs.shape[0] == 0:
        raise ValueError("compute_welch_psd_average needs at least one epoch.")

    nperseg = int(round(sfreq * N_PER_SEG_SEC))
    nperseg = max(16, nperseg)
    noverlap = int(round(nperseg * N_OVERLAP_FRAC))

    psds: list[np.ndarray] = []
    kept_freqs: np.ndarray | None = None

    for epoch in epochs:
        channel_psds = []
        for channel_data in epoch:
            freqs, pxx = welch(
                channel_data,
                fs=sfreq,
                nperseg=min(nperseg, len(channel_data)),
                noverlap=min(noverlap, max(0, len(channel_data) // 2 - 1)),
                detrend="constant",
                scaling="density",
            )
            keep = (freqs >= fmin) & (freqs <= fmax)
            kept_freqs = freqs[keep]
            channel_psds.append(pxx[keep])
        psds.append(np.mean(np.asarray(channel_psds), axis=0))

    if kept_freqs is None:
        raise RuntimeError("Welch PSD failed to produce a frequency vector.")

    return Spectrum(
        freqs=kept_freqs,
        power=np.mean(np.asarray(psds), axis=0),
        method="Welch PSD averaged across epochs and channels",
    )
