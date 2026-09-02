"""Write immediate and saved-data FFT amplitude plots."""

from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import mne
import numpy as np

from sssep_batch.analysis.saved_fft import RoiSpectrum, ScalpMapValues
from sssep_batch.config import FIXED_HZ_LINES, FMAX, FMIN
from sssep_batch.models import Spectrum


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


def _plot_stimulation_marker(axes, stimulation_hz: float | None) -> None:
    """Label the external TENS frequency without modifying FFT amplitudes."""
    if stimulation_hz is not None:
        axes.axvline(
            stimulation_hz, linestyle="--", linewidth=1.8, color="#a33b32",
            label="TENS Unit Stimulation Frequency",
        )


def plot_spectrum(
    active: Spectrum,
    baseline: Spectrum | None,
    title: str,
    outpath: Path,
    target_hz: float | None,
    channel_names: list[str],
    plot_channel: str,
    active_label: str = "Trigger code average",
    baseline_label: str = "Gap/Break baseline",
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
        plt.plot(active.freqs, active_amplitude, linewidth=1.8, label=active_label)
        if baseline_amplitude is not None:
            plt.plot(
                baseline.freqs, baseline_amplitude, linestyle="--", linewidth=1.4,
                label=baseline_label,
            )
        y_text = y_max * 0.98 if y_max > 0 else 1.0
        for hz in FIXED_HZ_LINES:
            plt.axvline(hz, linestyle=":", linewidth=1.0)
            plt.text(hz + 0.10, y_text, f"{hz:g} Hz", rotation=90, va="top", fontsize=8)
        _plot_stimulation_marker(plt.gca(), target_hz)
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


def plot_saved_roi_spectrum(
    spectrum: RoiSpectrum,
    roi_name: str,
    outpath: Path,
    stimulation_hz: float | None = None,
) -> None:
    """Save an ROI curve with an optional display-only stimulation marker override."""

    plot_fmin = spectrum.provenance.plot_fmin_hz
    plot_fmax = spectrum.provenance.plot_fmax_hz
    visible = (spectrum.frequencies >= plot_fmin) & (
        spectrum.frequencies <= plot_fmax
    )
    if not np.any(visible):
        raise ValueError("The saved spectrum contains no bins in the plot frequency range.")
    visible_amplitude = spectrum.amplitude_uv[visible]
    y_max = float(np.max(visible_amplitude))
    level = (
        f"Participant {spectrum.participant_id}"
        if spectrum.participant_id is not None
        else f"Group average (N={spectrum.participant_count})"
    )

    figure, axes = plt.subplots(figsize=(14, 6))
    try:
        axes.plot(
            spectrum.frequencies,
            spectrum.amplitude_uv,
            linewidth=1.8,
            label=level,
        )
        marker_hz = spectrum.event.target_hz if stimulation_hz is None else stimulation_hz
        _plot_stimulation_marker(axes, marker_hz)
        axes.set_title(
            f"{level} - {spectrum.event.trigger_label} - {roi_name}"
        )
        axes.set_xlabel("Frequency (Hz)")
        axes.set_ylabel("FFT amplitude (µV)")
        axes.set_xlim(plot_fmin, plot_fmax)
        axes.set_ylim(0, y_max * 1.08 if y_max > 0 else 1.0)
        axes.set_xticks(
            np.arange(np.ceil(plot_fmin), np.floor(plot_fmax) + 1, 1)
        )
        axes.grid(True, axis="y", alpha=0.3)
        axes.legend()
        figure.tight_layout()
        figure.savefig(outpath, dpi=300)
    finally:
        plt.close(figure)


@lru_cache(maxsize=8)
def _saved_plot_montage(montage_name: str):
    """Return the montage recorded in the reusable FFT table."""

    try:
        return mne.channels.make_standard_montage(montage_name)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"The saved montage {montage_name!r} is not available in this MNE "
            "installation."
        ) from exc


def plot_saved_scalp_map(values: ScalpMapValues, outpath: Path) -> tuple[str, ...]:
    """Save one FFT-amplitude scalp map and return labels without coordinates."""

    montage = _saved_plot_montage(values.provenance.montage_name)
    montage_lookup = {name.casefold(): name for name in montage.ch_names}
    mapped_names: list[str] = []
    mapped_values: list[float] = []
    mapped_counts: list[int] = []
    unmapped: list[str] = []
    for channel, amplitude, count in zip(
        values.channel_names,
        values.amplitude_uv,
        values.participant_counts,
    ):
        mapped = montage_lookup.get(channel.casefold())
        if mapped is None:
            unmapped.append(channel)
            continue
        if not np.isfinite(amplitude):
            raise ValueError(f"Scalp-map electrode {channel!r} has a nonfinite value.")
        mapped_names.append(mapped)
        mapped_values.append(float(amplitude))
        mapped_counts.append(count)
    if len(mapped_names) < 4:
        omitted_text = f" Unmapped electrodes: {unmapped}." if unmapped else ""
        raise ValueError(
            "At least four montage electrodes with finite values are required for a "
            f"scalp map.{omitted_text}"
        )

    info = mne.create_info(mapped_names, sfreq=100.0, ch_types="eeg")
    info.set_montage(montage)
    amplitude_array = np.asarray(mapped_values, dtype=np.float64)
    upper_limit = float(np.max(amplitude_array))
    if upper_limit <= 0:
        upper_limit = 1.0
    if values.participant_id is not None:
        level = f"Participant {values.participant_id}"
    else:
        count_min = min(mapped_counts)
        count_max = max(mapped_counts)
        count_text = (
            f"N={count_min}"
            if count_min == count_max
            else f"electrode N={count_min}–{count_max}"
        )
        level = f"Group average ({count_text})"

    figure, axes = plt.subplots(figsize=(7, 6))
    try:
        image, _ = mne.viz.plot_topomap(
            amplitude_array,
            info,
            axes=axes,
            show=False,
            sensors=True,
            contours=6,
            cmap="viridis",
            vlim=(0.0, upper_limit),
        )
        axes.set_title(
            f"{level} - {values.event.trigger_label}\n"
            f"FFT amplitude at {values.actual_frequency_hz:g} Hz"
        )
        colorbar = figure.colorbar(image, ax=axes, shrink=0.82)
        colorbar.set_label("FFT amplitude (µV)")
        figure.tight_layout()
        figure.savefig(outpath, dpi=300)
    finally:
        plt.close(figure)
    return tuple(unmapped)
