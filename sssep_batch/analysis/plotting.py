"""Write full per-electrode FFT amplitude tables and single-electrode plots.

Frequency tables retain every supplied FFT bin and the existing ROI mean
columns. Plots show one configured electrode in FMIN/FMAX; plotting limits do
not change the FFT, tables, or summary calculations.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sssep_batch.config import FIXED_HZ_LINES, FMAX, FMIN
from sssep_batch.models import Spectrum


def _mean_selected_amplitude(
    spectrum: Spectrum,
    channel_names: list[str],
    analysis_channels: list[str],
) -> np.ndarray:
    """Select electrodes by name and average their already-computed amplitudes."""
    if spectrum.amplitude_uv.shape != (len(channel_names), len(spectrum.freqs)):
        raise ValueError("Channel names and frequency bins must match the amplitude array.")
    if len(set(channel_names)) != len(channel_names):
        raise ValueError("Channel names must be unique in amplitude outputs.")
    if not analysis_channels:
        raise ValueError("Select at least one analysis channel for amplitude outputs.")
    missing = [channel for channel in analysis_channels if channel not in channel_names]
    if missing:
        raise ValueError(f"Analysis channels are missing from the spectrum: {missing}")
    indices = [channel_names.index(channel) for channel in analysis_channels]
    return np.mean(spectrum.amplitude_uv[indices], axis=0)


def _channel_amplitude(
    spectrum: Spectrum,
    channel_names: list[str],
    plot_channel: str,
) -> np.ndarray:
    """Return one named electrode's already-computed amplitudes."""
    if spectrum.amplitude_uv.shape != (len(channel_names), len(spectrum.freqs)):
        raise ValueError("Channel names and frequency bins must match the amplitude array.")
    if len(set(channel_names)) != len(channel_names):
        raise ValueError("Channel names must be unique in amplitude outputs.")
    if plot_channel not in channel_names:
        raise ValueError(
            f"Plot electrode {plot_channel!r} is missing from the spectrum. "
            f"Available electrodes: {channel_names}"
        )
    return spectrum.amplitude_uv[channel_names.index(plot_channel)]


def _check_baseline_alignment(active: Spectrum, baseline: Spectrum) -> None:
    """Reject incompatible spectra instead of silently combining mismatched bins."""
    if (
        not np.array_equal(active.freqs, baseline.freqs)
        or active.amplitude_uv.shape != baseline.amplitude_uv.shape
    ):
        raise ValueError("Active and baseline spectra must have matching channels and frequency bins.")


def spectrum_to_dataframe(
    active: Spectrum,
    baseline: Spectrum | None,
    channel_names: list[str],
    analysis_channels: list[str],
) -> pd.DataFrame:
    """Return full-frequency microvolt amplitudes for each electrode and ROI mean."""
    columns = {
        "frequency_hz": active.freqs,
        "active_mean_amplitude_uv": _mean_selected_amplitude(
            active, channel_names, analysis_channels
        ),
    }
    if baseline is not None:
        _check_baseline_alignment(active, baseline)
        columns["baseline_mean_amplitude_uv"] = _mean_selected_amplitude(
            baseline, channel_names, analysis_channels
        )
    for index, channel in enumerate(channel_names):
        columns[f"active_{channel}_amplitude_uv"] = active.amplitude_uv[index]
        if baseline is not None:
            columns[f"baseline_{channel}_amplitude_uv"] = baseline.amplitude_uv[index]
    return pd.DataFrame(columns)


def plot_spectrum(
    active: Spectrum,
    baseline: Spectrum | None,
    title: str,
    outpath: Path,
    target_hz: float | None,
    channel_names: list[str],
    plot_channel: str,
) -> None:
    """Save one electrode's FFT amplitudes in microvolts as a PNG."""
    active_amplitude = _channel_amplitude(active, channel_names, plot_channel)
    baseline_amplitude = None
    if baseline is not None:
        _check_baseline_alignment(active, baseline)
        baseline_amplitude = _channel_amplitude(baseline, channel_names, plot_channel)
    visible = (active.freqs >= FMIN) & (active.freqs <= FMAX)
    if not np.any(visible):
        raise ValueError("The spectrum contains no bins in the plot frequency range.")
    y_max = float(np.max(active_amplitude[visible]))
    if baseline_amplitude is not None:
        y_max = max(y_max, float(np.max(baseline_amplitude[visible])))

    plt.figure(figsize=(14, 6))
    try:
        plt.plot(active.freqs, active_amplitude, linewidth=1.8, label="Active")
        if baseline_amplitude is not None:
            plt.plot(
                baseline.freqs, baseline_amplitude, linestyle="--", linewidth=1.4,
                label="Gap/Break baseline",
            )
        y_text = y_max * 0.98 if y_max > 0 else 1.0
        for hz in FIXED_HZ_LINES:
            plt.axvline(hz, linestyle=":", linewidth=1.0)
            plt.text(hz + 0.10, y_text, f"{hz:g} Hz", rotation=90, va="top", fontsize=8)
        if target_hz is not None:
            plt.axvline(target_hz, linestyle="-", linewidth=1.8)
            plt.text(
                target_hz + 0.15, y_max * 0.88 if y_max > 0 else 1.0,
                f"Expected {target_hz:g} Hz", rotation=90, va="top", fontsize=9,
            )
        plt.title(f"{title} - Electrode {plot_channel}")
        plt.xlabel("Frequency (Hz)")
        plt.ylabel(f"FFT amplitude at {plot_channel} (µV)")
        plt.xlim(FMIN, FMAX)
        plt.ylim(0, y_max * 1.08 if y_max > 0 else 1.0)
        plt.xticks(np.arange(np.ceil(FMIN), np.floor(FMAX) + 1, 1))
        plt.grid(True, axis="y", alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(outpath, dpi=300)
    finally:
        plt.close()
