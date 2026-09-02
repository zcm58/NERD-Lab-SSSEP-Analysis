"""Write plots, ROI source CSVs, and scalp workbooks from saved FFT data."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import Iterable

import pandas as pd
from xlsxwriter import Workbook

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


def _write_scalp_workbook(values: ScalpMapValues, output_path: Path) -> None:
    """Save only electrode names and numeric FFT amplitudes, with fitted columns."""
    with Workbook(output_path) as workbook:
        worksheet = workbook.add_worksheet("FFT amplitudes")
        worksheet.write_row(0, 0, ("Electrode", "FFT amplitude (µV)"))
        for row, (channel, amplitude) in enumerate(
            zip(values.channel_names, values.amplitude_uv), start=1
        ):
            # Electrode labels are text, even if a saved label starts with '='.
            worksheet.write_string(row, 0, channel)
            worksheet.write_number(row, 1, float(amplitude))
        worksheet.autofit()


def _provenance_columns(provenance: FftProvenance) -> dict[str, object]:
    """Return stable provenance fields for every post-processing CSV."""

    return {
        "processing_method": provenance.processing_method,
        "fft_schema_version": provenance.fft_schema_version,
        "fpvs_reference_commit": provenance.fpvs_reference_commit,
        "montage_name": provenance.montage_name,
        "sampling_rate_hz": provenance.sampling_rate_hz,
        "analysis_window_sec": provenance.analysis_window_sec,
        "epoch_window_sec": provenance.epoch_window_sec,
        "fft_crop_start_sec": provenance.fft_crop_start_sec,
        "fft_crop_end_sec": provenance.fft_crop_end_sec,
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
    stimulation_hz: float | None = None,
) -> dict[str, object]:
    """Create an ROI PNG and source CSV; frequency overrides affect its marker only."""

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
        plot_saved_roi_spectrum(spectrum, name, plot_path, stimulation_hz=stimulation_hz)
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
    """Create a scalp-map PNG and a two-column electrode/amplitude workbook."""

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
    source_xlsx = output_folder / f"{stem}_data.xlsx"
    plot_path = output_folder / f"{stem}.png"
    try:
        omitted_channels = plot_saved_scalp_map(values, plot_path)
        _write_scalp_workbook(values, source_xlsx)
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
        "source_xlsx": str(source_xlsx),
        "requested_frequency_hz": values.requested_frequency_hz,
        "actual_frequency_hz": values.actual_frequency_hz,
        "participant_count_min": min(included_counts),
        "participant_count_max": max(included_counts),
        "omitted_channels": list(omitted_channels),
    }
