"""Write PNG plots directly beside other saved FFT plots, without data copies."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from sssep_batch.analysis.plotting import (
    fft_plot_stem,
    plot_saved_paired_scalp_maps,
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


def create_saved_paired_scalp_outputs(
    dataset: SavedFftDataset,
    *,
    event_requests: Iterable[tuple[str, int, float]],
    participant_id: str | None = None,
) -> dict[str, object]:
    """Create one two-panel scalp-map PNG with a shared amplitude scale."""

    requests = tuple(event_requests)
    if len(requests) != 2:
        raise ValueError("Paired scalp maps require exactly two event requests.")
    if any(event_type != "cue" for event_type, _code, _frequency in requests):
        raise ValueError("Paired scalp maps support cue conditions only.")
    event_keys = tuple(
        (str(event_type), int(trigger_code))
        for event_type, trigger_code, _frequency in requests
    )
    if len(set(event_keys)) != 2:
        raise ValueError("Paired scalp maps require two distinct event requests.")

    values = tuple(
        saved_scalp_values(
            dataset,
            event_type=event_type,
            trigger_code=trigger_code,
            frequency_hz=frequency_hz,
            participant_id=participant_id,
        )
        for event_type, trigger_code, frequency_hz in requests
    )
    level = participant_id or "group"
    map_stems = "_and_".join(
        f"{item.event.event_type}_{item.event.trigger_code:03d}_"
        f"{item.actual_frequency_hz:g}_Hz"
        for item in values
    )
    stem = safe_filename_stem(f"{level}_{map_stems}_scalp_map")
    plot_path = create_saved_plot_path(dataset, stem)
    try:
        omitted_by_map = plot_saved_paired_scalp_maps(values, plot_path)
    except Exception:
        plot_path.unlink(missing_ok=True)
        raise

    maps: list[dict[str, object]] = []
    for item, omitted_channels in zip(values, omitted_by_map):
        omitted = set(omitted_channels)
        included_counts = [
            count
            for channel, count in zip(item.channel_names, item.participant_counts)
            if channel not in omitted
        ]
        maps.append(
            {
                "event_type": item.event.event_type,
                "trigger_code": item.event.trigger_code,
                "trigger_label": item.event.trigger_label,
                "requested_frequency_hz": item.requested_frequency_hz,
                "actual_frequency_hz": item.actual_frequency_hz,
                "participant_count_min": min(included_counts),
                "participant_count_max": max(included_counts),
                "omitted_channels": list(omitted_channels),
            }
        )
    return {
        "kind": "scalp",
        "layout": "paired",
        "output_folder": str(plot_path.parent),
        "plot_path": str(plot_path),
        "maps": maps,
    }
