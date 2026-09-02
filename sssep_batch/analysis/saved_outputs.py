"""Write PNG plots directly beside other saved FFT plots, without data copies."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from sssep_batch.analysis.plotting import (
    fft_plot_stem,
    plot_saved_roi_spectrum,
    plot_saved_scalp_map,
    reserve_plot_path,
    safe_filename_stem,
)
from sssep_batch.analysis.saved_fft import (
    SavedFftDataset,
    average_saved_roi,
    saved_scalp_values,
)


SAVED_PLOTS_FOLDERNAME = "saved_fft_plots"


def create_saved_plot_path(dataset: SavedFftDataset, stem: str) -> Path:
    """Reserve a unique PNG directly in saved_fft_plots without overwriting files."""
    folder = dataset.source_csv.parent / SAVED_PLOTS_FOLDERNAME
    return reserve_plot_path(folder, stem)


def create_saved_roi_outputs(
    dataset: SavedFftDataset,
    *,
    event_type: str,
    trigger_code: int,
    channels: Iterable[str],
    roi_name: str,
    participant_id: str | None = None,
    stimulation_hz: float | None = None,
) -> dict[str, object]:
    """Create an ROI PNG; frequency overrides affect its marker only."""

    name = str(roi_name).strip()
    if not name:
        raise ValueError("Enter a short name for the electrode or ROI plot.")
    spectrum = average_saved_roi(
        dataset,
        event_type=event_type,
        trigger_code=trigger_code,
        channels=channels,
        participant_id=participant_id,
    )
    stem = fft_plot_stem(spectrum.event.trigger_label, name)
    plot_path = create_saved_plot_path(dataset, stem)
    try:
        plot_saved_roi_spectrum(spectrum, name, plot_path, stimulation_hz=stimulation_hz)
    except Exception:
        plot_path.unlink(missing_ok=True)
        raise
    return {
        "kind": "roi",
        "output_folder": str(plot_path.parent),
        "plot_path": str(plot_path),
        "participant_count": spectrum.participant_count,
        "used_channels": list(spectrum.used_channels),
    }


def create_saved_scalp_outputs(
    dataset: SavedFftDataset,
    *,
    event_type: str,
    trigger_code: int,
    frequency_hz: float,
    participant_id: str | None = None,
) -> dict[str, object]:
    """Create a scalp-map PNG from the saved FFT amplitudes."""

    values = saved_scalp_values(
        dataset,
        event_type=event_type,
        trigger_code=trigger_code,
        frequency_hz=frequency_hz,
        participant_id=participant_id,
    )
    level = participant_id or "group"
    stem = safe_filename_stem(
        f"{level}_{event_type}_{trigger_code:03d}_"
        f"{values.actual_frequency_hz:g}_Hz_scalp_map"
    )
    plot_path = create_saved_plot_path(dataset, stem)
    try:
        omitted_channels = plot_saved_scalp_map(values, plot_path)
    except Exception:
        plot_path.unlink(missing_ok=True)
        raise
    omitted = set(omitted_channels)
    included_counts = [
        count
        for channel, count in zip(values.channel_names, values.participant_counts)
        if channel not in omitted
    ]
    return {
        "kind": "scalp",
        "output_folder": str(plot_path.parent),
        "plot_path": str(plot_path),
        "requested_frequency_hz": values.requested_frequency_hz,
        "actual_frequency_hz": values.actual_frequency_hz,
        "participant_count_min": min(included_counts),
        "participant_count_max": max(included_counts),
        "omitted_channels": list(omitted_channels),
    }
