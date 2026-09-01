"""Write plots and source CSVs from validated saved SSSEP FFT data."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import Iterable

import pandas as pd

from sssep_batch.analysis.plotting import (
    plot_saved_roi_spectrum,
    plot_saved_scalp_map,
)
from sssep_batch.analysis.saved_fft import (
    FftProvenance,
    RoiSpectrum,
    SavedFftDataset,
    ScalpMapValues,
    average_saved_roi,
    saved_scalp_values,
)


SAVED_PLOTS_FOLDERNAME = "saved_fft_plots"


def roi_source_dataframe(spectrum: RoiSpectrum, roi_name: str) -> pd.DataFrame:
    """Return the exact values used for a saved ROI line plot."""

    level = spectrum.participant_id or "Group average"
    return pd.DataFrame(
        {
            "level": level,
            "participant_count": spectrum.participant_count,
            "event_type": spectrum.event.event_type,
            "trigger_code": spectrum.event.trigger_code,
            "trigger_label": spectrum.event.trigger_label,
            "target_hz": spectrum.event.target_hz,
            "roi_name": roi_name,
            "requested_electrodes": ";".join(spectrum.requested_channels),
            "contributing_electrodes": ";".join(spectrum.used_channels),
            **_provenance_columns(spectrum.provenance),
            "frequency_hz": spectrum.frequencies,
            "fft_amplitude_uv": spectrum.amplitude_uv,
        }
    )


def roi_participant_source_dataframe(
    spectrum: RoiSpectrum,
    roi_name: str,
) -> pd.DataFrame:
    """Return participant ROI curves and their contributing electrodes."""

    frames: list[pd.DataFrame] = []
    for contribution in spectrum.participant_contributions:
        frames.append(
            pd.DataFrame(
                {
                    "participant_id": contribution.participant_id,
                    "event_type": spectrum.event.event_type,
                    "trigger_code": spectrum.event.trigger_code,
                    "trigger_label": spectrum.event.trigger_label,
                    "target_hz": spectrum.event.target_hz,
                    "roi_name": roi_name,
                    "requested_electrodes": ";".join(spectrum.requested_channels),
                    "contributing_electrodes": ";".join(
                        contribution.used_channels
                    ),
                    "contributing_electrode_count": len(
                        contribution.used_channels
                    ),
                    **_provenance_columns(spectrum.provenance),
                    "frequency_hz": spectrum.frequencies,
                    "participant_fft_amplitude_uv": contribution.amplitude_uv,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def scalp_source_dataframe(
    values: ScalpMapValues,
    omitted_channels: Iterable[str] = (),
) -> pd.DataFrame:
    """Return the exact electrode values used for one saved scalp map."""

    level = values.participant_id or "Group average"
    omitted = set(omitted_channels)
    return pd.DataFrame(
        {
            "level": level,
            "event_type": values.event.event_type,
            "trigger_code": values.event.trigger_code,
            "trigger_label": values.event.trigger_label,
            "requested_frequency_hz": values.requested_frequency_hz,
            "plotted_frequency_hz": values.actual_frequency_hz,
            **_provenance_columns(values.provenance),
            "electrode": values.channel_names,
            "fft_amplitude_uv": values.amplitude_uv,
            "participant_count": values.participant_counts,
            "included_in_scalp_map": [
                channel not in omitted for channel in values.channel_names
            ],
        }
    )


def _provenance_columns(provenance: FftProvenance) -> dict[str, object]:
    """Return stable provenance fields for every post-processing CSV."""

    return {
        "processing_method": provenance.processing_method,
        "fft_schema_version": provenance.fft_schema_version,
        "fpvs_reference_commit": provenance.fpvs_reference_commit,
        "montage_name": provenance.montage_name,
        "sampling_rate_hz": provenance.sampling_rate_hz,
        "analysis_window_sec": provenance.analysis_window_sec,
        "plot_fmin_hz": provenance.plot_fmin_hz,
        "plot_fmax_hz": provenance.plot_fmax_hz,
    }


def safe_filename_stem(value: str) -> str:
    """Return a Windows-safe, readable filename stem."""

    invalid = '<>:"/\\|?*'
    translated = "".join("_" if char in invalid or ord(char) < 32 else char for char in value)
    stem = " ".join(translated.split()).strip(" .")
    return stem or "saved_fft_plot"


def create_saved_plot_output_folder(dataset: SavedFftDataset) -> Path:
    """Create a fresh post-processing folder beside the source FFT table."""

    parent = dataset.source_csv.parent / SAVED_PLOTS_FOLDERNAME
    try:
        parent.mkdir(parents=True, exist_ok=True)
        prefix = datetime.now().strftime("plot_%Y%m%d_%H%M%S_")
        return Path(mkdtemp(prefix=prefix, dir=parent))
    except OSError as exc:
        raise ValueError(
            "Could not create a saved-plot output folder beside the FFT data.\n\n"
            f"Folder: {parent}\nSystem error: {exc}"
        ) from exc


def _remove_failed_plot_folder(
    dataset: SavedFftDataset,
    output_folder: Path,
) -> None:
    """Remove only the fresh folder created for one failed plot attempt."""

    expected_parent = (dataset.source_csv.parent / SAVED_PLOTS_FOLDERNAME).resolve()
    resolved_output = output_folder.resolve()
    if resolved_output.parent != expected_parent:
        raise RuntimeError(
            "Refusing to clean a failed plot folder outside the saved-results "
            f"location: {resolved_output}"
        )
    shutil.rmtree(resolved_output)


def create_saved_roi_outputs(
    dataset: SavedFftDataset,
    *,
    event_type: str,
    trigger_code: int,
    channels: Iterable[str],
    roi_name: str,
    participant_id: str | None = None,
) -> dict[str, object]:
    """Create a saved-data ROI PNG and its exact plotted-value CSV."""

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
    output_folder = create_saved_plot_output_folder(dataset)
    level = participant_id or "group"
    stem = safe_filename_stem(
        f"{level}_{event_type}_{trigger_code:03d}_{name}_fft_amplitude"
    )
    source_csv = output_folder / f"{stem}_data.csv"
    participant_source_csv = output_folder / f"{stem}_participant_values.csv"
    plot_path = output_folder / f"{stem}.png"
    try:
        roi_source_dataframe(spectrum, name).to_csv(source_csv, index=False)
        roi_participant_source_dataframe(spectrum, name).to_csv(
            participant_source_csv,
            index=False,
        )
        plot_saved_roi_spectrum(spectrum, name, plot_path)
    except Exception:
        _remove_failed_plot_folder(dataset, output_folder)
        raise
    return {
        "kind": "roi",
        "output_folder": str(output_folder),
        "plot_path": str(plot_path),
        "source_csv": str(source_csv),
        "participant_source_csv": str(participant_source_csv),
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
    """Create a saved-data scalp-map PNG and its exact electrode-value CSV."""

    values = saved_scalp_values(
        dataset,
        event_type=event_type,
        trigger_code=trigger_code,
        frequency_hz=frequency_hz,
        participant_id=participant_id,
    )
    output_folder = create_saved_plot_output_folder(dataset)
    level = participant_id or "group"
    stem = safe_filename_stem(
        f"{level}_{event_type}_{trigger_code:03d}_"
        f"{values.actual_frequency_hz:g}_Hz_scalp_map"
    )
    source_csv = output_folder / f"{stem}_data.csv"
    plot_path = output_folder / f"{stem}.png"
    try:
        omitted_channels = plot_saved_scalp_map(values, plot_path)
        scalp_source_dataframe(values, omitted_channels).to_csv(
            source_csv,
            index=False,
        )
    except Exception:
        _remove_failed_plot_folder(dataset, output_folder)
        raise
    omitted = set(omitted_channels)
    included_counts = [
        count
        for channel, count in zip(values.channel_names, values.participant_counts)
        if channel not in omitted
    ]
    return {
        "kind": "scalp",
        "output_folder": str(output_folder),
        "plot_path": str(plot_path),
        "source_csv": str(source_csv),
        "requested_frequency_hz": values.requested_frequency_hz,
        "actual_frequency_hz": values.actual_frequency_hz,
        "participant_count_min": min(included_counts),
        "participant_count_max": max(included_counts),
        "omitted_channels": list(omitted_channels),
    }
