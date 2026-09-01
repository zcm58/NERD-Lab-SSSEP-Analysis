"""Compute the FPVS Toolbox amplitude FFT from repeated SSSEP epochs.

Repetitions are averaged in the time domain separately for each electrode.
The transform preserves the Toolbox's scaling and arithmetic order, including
doubling the DC and Nyquist bins. No taper, detrending, or padding is applied.
"""

import numpy as np

from sssep_batch.config import PROCESSING_METHOD
from sssep_batch.models import Spectrum


def compute_sssep_fft_from_averaged_epochs(
    epochs: np.ndarray,
    sfreq: float,
    fmin: float = 0.0,
    fmax: float | None = None,
) -> Spectrum:
    """Return per-electrode FFT amplitudes in microvolts after trial averaging.

    Input is EEG in volts with shape (n_epochs, n_channels, n_times). By
    default all nonnegative frequency bins are returned. Optional frequency
    limits select output bins only; they do not change the transform.
    """
    if epochs.ndim != 3 or any(size == 0 for size in epochs.shape):
        raise ValueError("FFT needs at least one epoch, channel, and time sample.")
    if not np.isfinite(sfreq) or sfreq <= 0:
        raise ValueError("FFT sampling frequency must be positive and finite.")

    avg_data = np.mean(epochs.astype(np.float64), axis=0)
    avg_data_uv = avg_data * 1e6
    num_times = avg_data.shape[1]
    num_fft_bins = num_times // 2 + 1
    freqs = np.fft.rfftfreq(num_times, d=1.0 / sfreq)
    fft_full_spectrum = np.fft.fft(avg_data_uv, axis=1)
    amplitude_uv = np.abs(fft_full_spectrum[:, :num_fft_bins]) / num_times * 2

    keep = freqs >= fmin
    if fmax is not None:
        keep &= freqs <= fmax
    if not np.any(keep):
        raise ValueError("The requested frequency range contains no FFT bins.")
    return Spectrum(
        freqs=freqs[keep],
        amplitude_uv=amplitude_uv[:, keep],
        method=PROCESSING_METHOD,
    )
