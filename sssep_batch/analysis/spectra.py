"""Compute the FPVS Toolbox amplitude FFT from repeated SSSEP epochs.

Repetitions are averaged in the time domain separately for each electrode.
The transform preserves the Toolbox's scaling and arithmetic order, including
doubling the DC and Nyquist bins. No taper, detrending, or padding is applied.
"""

from numbers import Real

import numpy as np

from sssep_batch.config import (
    FFT_CROP_END_SEC,
    FFT_CROP_START_SEC,
    PROCESSING_METHOD,
)
from sssep_batch.models import Spectrum


def crop_epochs_for_fft(
    epochs: np.ndarray,
    sfreq: float,
    *,
    crop_start_sec: float = FFT_CROP_START_SEC,
    crop_end_sec: float = FFT_CROP_END_SEC,
) -> np.ndarray:
    """Return the stop-exclusive epoch samples retained for the FFT.

    Crop boundaries are converted to samples with the same ``round`` rule used
    for epoch extraction. A 15-second epoch at 256 Hz therefore keeps samples
    640 through 3199: exactly the middle 2560 samples, or 10 seconds.
    """

    epoch_data = np.asarray(epochs)
    if epoch_data.ndim != 3 or epoch_data.shape[-1] == 0:
        raise ValueError(
            "FFT cropping needs epochs shaped as trials, channels, and time samples."
        )
    if (
        not isinstance(sfreq, Real)
        or isinstance(sfreq, bool)
        or not np.isfinite(sfreq)
        or sfreq <= 0
    ):
        raise ValueError("FFT sampling frequency must be positive and finite.")
    if (
        not isinstance(crop_start_sec, Real)
        or isinstance(crop_start_sec, bool)
        or not isinstance(crop_end_sec, Real)
        or isinstance(crop_end_sec, bool)
        or not np.isfinite(crop_start_sec)
        or not np.isfinite(crop_end_sec)
        or crop_start_sec < 0
        or crop_end_sec < 0
    ):
        raise ValueError("FFT crop durations must be finite nonnegative numbers.")

    start_sample = int(round(crop_start_sec * sfreq))
    end_samples = int(round(crop_end_sec * sfreq))
    stop_sample = epoch_data.shape[-1] - end_samples
    if start_sample >= stop_sample:
        raise ValueError(
            "The extracted epoch is too short for the configured FFT crop. "
            f"It has {epoch_data.shape[-1]} samples, but the crop removes "
            f"{start_sample} from the start and {end_samples} from the end."
        )
    return epoch_data[..., start_sample:stop_sample]


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
