"""Reload and aggregate saved participant FFT amplitudes for later plotting."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from sssep_batch.analysis.grouping import average_group_spectra
from sssep_batch.config import PROCESSING_METHOD
from sssep_batch.models import (
    FFT_EXPORT_SCHEMA_VERSION,
    ParticipantSpectrum,
    Spectrum,
)


PARTICIPANT_FFT_FILENAME = "participant_fft_amplitudes.csv"
_AMPLITUDE_SUFFIX = "_amplitude_uv"
_ANALYSIS_MEAN_COLUMN = "analysis_mean_amplitude_uv"
_PROVENANCE_COLUMNS = (
    "fft_schema_version",
    "fpvs_reference_commit",
    "montage_name",
    "sampling_rate_hz",
    "analysis_window_sec",
    "plot_fmin_hz",
    "plot_fmax_hz",
)
_CROP_PROVENANCE_COLUMNS = (
    "epoch_window_sec",
    "fft_crop_start_sec",
    "fft_crop_end_sec",
)
_TEXT_COLUMNS = (
    "participant_id",
    "file_name",
    "event_type",
    "trigger_label",
    "processing_method",
    "fpvs_reference_commit",
    "montage_name",
    "analysis_channels",
)
_REQUIRED_COLUMNS = (
    "participant_id",
    "file_name",
    "event_type",
    "trigger_code",
    "trigger_label",
    "target_hz",
    "usable_epochs",
    "processing_method",
    *_PROVENANCE_COLUMNS,
    "analysis_channels",
    "frequency_hz",
)


@dataclass(frozen=True, slots=True)
class SavedEvent:
    """One event definition found in a saved participant FFT table."""

    event_type: str
    trigger_code: int
    trigger_label: str
    target_hz: float | None

    @property
    def display_name(self) -> str:
        """Return a concise label for a GUI selector."""

        kind = "Cue" if self.event_type == "cue" else "Baseline"
        return f"{kind} {self.trigger_code}: {self.trigger_label}"


@dataclass(frozen=True, slots=True)
class FftProvenance:
    """Processing identity stored with reusable FFT amplitudes."""

    processing_method: str
    fft_schema_version: int
    fpvs_reference_commit: str
    montage_name: str
    sampling_rate_hz: float
    analysis_window_sec: float
    epoch_window_sec: float
    fft_crop_start_sec: float
    fft_crop_end_sec: float
    plot_fmin_hz: float
    plot_fmax_hz: float


@dataclass(frozen=True, slots=True)
class SavedFftDataset:
    """Validated participant spectra reconstructed from one saved CSV."""

    source_csv: Path
    records: tuple[ParticipantSpectrum, ...]
    channel_names: tuple[str, ...]
    provenance: FftProvenance

    @property
    def processing_method(self) -> str:
        """Return the validated processing-method label."""

        return self.provenance.processing_method

    @property
    def participant_ids(self) -> tuple[str, ...]:
        """Return participant IDs in their first-seen order."""

        return _ordered_unique(record.participant_id for record in self.records)

    @property
    def events(self) -> tuple[SavedEvent, ...]:
        """Return first-seen cue definitions, followed by baselines."""

        events: list[SavedEvent] = []
        seen: set[tuple[str, int]] = set()
        for event_type in ("cue", "baseline"):
            for record in self.records:
                if record.event_type != event_type:
                    continue
                key = (record.event_type, record.trigger_code)
                if key in seen:
                    continue
                seen.add(key)
                events.append(
                    SavedEvent(
                        event_type=record.event_type,
                        trigger_code=record.trigger_code,
                        trigger_label=record.trigger_label,
                        target_hz=record.target_hz,
                    )
                )
        return tuple(events)

    @property
    def frequencies(self) -> np.ndarray:
        """Return the common saved FFT grid."""

        return self.records[0].spectrum.freqs.copy()


@dataclass(frozen=True, slots=True)
class RoiSpectrum:
    """One participant or equal-participant group ROI amplitude spectrum."""

    event: SavedEvent
    participant_id: str | None
    requested_channels: tuple[str, ...]
    used_channels: tuple[str, ...]
    contributing_participant_ids: tuple[str, ...]
    frequencies: np.ndarray
    amplitude_uv: np.ndarray
    participant_contributions: tuple["RoiParticipantContribution", ...]
    provenance: FftProvenance

    @property
    def participant_count(self) -> int:
        """Return the number of participants contributing to this curve."""

        return len(self.contributing_participant_ids)

    @property
    def processing_method(self) -> str:
        """Return the processing method attached to the source table."""

        return self.provenance.processing_method


@dataclass(frozen=True, slots=True)
class RoiParticipantContribution:
    """One participant curve and the requested electrodes available for it."""

    participant_id: str
    used_channels: tuple[str, ...]
    amplitude_uv: np.ndarray


@dataclass(frozen=True, slots=True)
class ScalpMapValues:
    """Per-electrode amplitudes at one saved FFT bin."""

    event: SavedEvent
    participant_id: str | None
    requested_frequency_hz: float
    actual_frequency_hz: float
    channel_names: tuple[str, ...]
    amplitude_uv: np.ndarray
    participant_counts: tuple[int, ...]
    provenance: FftProvenance

    @property
    def processing_method(self) -> str:
        """Return the processing method attached to the source table."""

        return self.provenance.processing_method


def load_saved_fft_dataset(path: str | Path) -> SavedFftDataset:
    """Load and strictly validate a saved participant FFT CSV or its run folder."""

    source_csv = _participant_fft_path(path)
    try:
        frame = pd.read_csv(
            source_csv,
            float_precision="round_trip",
            dtype={column: "string" for column in _TEXT_COLUMNS},
            keep_default_na=False,
            na_values=[""],
        )
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"Could not read the saved FFT data: {source_csv}\n\n{exc}") from exc
    if frame.empty:
        raise ValueError(f"The saved FFT data file is empty: {source_csv}")

    missing = [column for column in _REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        missing_provenance = [
            column for column in missing if column in _PROVENANCE_COLUMNS
        ]
        if missing_provenance and len(missing_provenance) == len(missing):
            raise ValueError(
                "This participant FFT table predates the reusable, versioned FFT "
                "format and cannot be safely plotted later. Reprocess the original "
                f"BDF files with this SSSEP version. Missing provenance columns: "
                f"{missing_provenance}"
            )
        raise ValueError(
            "The selected file is not a complete SSSEP participant FFT table. "
            f"Missing columns: {missing}"
        )

    crop_provenance_present = [
        column for column in _CROP_PROVENANCE_COLUMNS if column in frame.columns
    ]
    if crop_provenance_present and len(crop_provenance_present) != len(
        _CROP_PROVENANCE_COLUMNS
    ):
        missing_crop_provenance = [
            column
            for column in _CROP_PROVENANCE_COLUMNS
            if column not in frame.columns
        ]
        raise ValueError(
            "Saved FFT crop provenance must include all three crop columns or "
            f"none of them. Missing columns: {missing_crop_provenance}"
        )
    if not crop_provenance_present:
        saved_methods = frame["processing_method"].dropna().astype(str).str.strip()
        if saved_methods.eq(PROCESSING_METHOD).any():
            raise ValueError(
                f"Saved FFT data using {PROCESSING_METHOD!r} requires all three "
                "epoch and crop provenance columns. Reprocess the original BDF "
                "files or restore the complete participant FFT CSV."
            )
        frame["epoch_window_sec"] = frame["analysis_window_sec"]
        frame["fft_crop_start_sec"] = 0.0
        frame["fft_crop_end_sec"] = 0.0

    amplitude_columns = [
        str(column)
        for column in frame.columns
        if str(column).endswith(_AMPLITUDE_SUFFIX)
        and str(column) != _ANALYSIS_MEAN_COLUMN
    ]
    if not amplitude_columns:
        raise ValueError("The saved FFT table contains no per-electrode amplitude columns.")
    channel_names = tuple(
        column[: -len(_AMPLITUDE_SUFFIX)] for column in amplitude_columns
    )
    if len({name.casefold() for name in channel_names}) != len(channel_names):
        raise ValueError("Saved FFT electrode columns must be unique ignoring case.")

    _convert_numeric_columns(frame, amplitude_columns)
    _validate_text_columns(frame)
    _validate_participant_file_mapping(frame)
    _validate_integer_column(frame, "trigger_code")
    _validate_integer_column(frame, "usable_epochs")
    _validate_integer_column(frame, "fft_schema_version")
    if not frame["fft_schema_version"].eq(FFT_EXPORT_SCHEMA_VERSION).all():
        found = sorted(frame["fft_schema_version"].unique().tolist())
        raise ValueError(
            f"Unsupported FFT export schema version(s): {found}. This version of "
            f"SSSEP reads schema {FFT_EXPORT_SCHEMA_VERSION}."
        )

    duplicate_columns = [
        "participant_id",
        "event_type",
        "trigger_code",
        "frequency_hz",
    ]
    duplicate_rows = frame.duplicated(duplicate_columns, keep=False)
    if duplicate_rows.any():
        example = frame.loc[duplicate_rows, duplicate_columns].iloc[0].to_dict()
        raise ValueError(
            "The saved FFT table has duplicate participant/event/frequency rows. "
            f"Example: {example}"
        )

    records: list[ParticipantSpectrum] = []
    group_columns = ["participant_id", "event_type", "trigger_code"]
    for _, rows in frame.groupby(group_columns, sort=False, dropna=False):
        rows = rows.sort_values("frequency_hz", kind="stable")
        records.append(_rows_to_record(rows, amplitude_columns, channel_names))

    if not records:
        raise ValueError("The saved FFT table contains no participant spectra.")
    average_group_spectra(records)  # Validate cross-participant alignment.
    ordered_channels = _ordered_unique(
        channel for record in records for channel in record.channel_names
    )
    first = records[0]
    provenance = FftProvenance(
        processing_method=first.spectrum.method,
        fft_schema_version=first.fft_schema_version,
        fpvs_reference_commit=first.fpvs_reference_commit,
        montage_name=first.montage_name,
        sampling_rate_hz=float(first.sampling_rate_hz),
        analysis_window_sec=float(first.analysis_window_sec),
        epoch_window_sec=float(first.epoch_window_sec),
        fft_crop_start_sec=float(first.fft_crop_start_sec),
        fft_crop_end_sec=float(first.fft_crop_end_sec),
        plot_fmin_hz=first.plot_fmin_hz,
        plot_fmax_hz=first.plot_fmax_hz,
    )
    return SavedFftDataset(
        source_csv=source_csv,
        records=tuple(records),
        channel_names=ordered_channels,
        provenance=provenance,
    )


def average_saved_roi(
    dataset: SavedFftDataset,
    *,
    event_type: str,
    trigger_code: int,
    channels: Iterable[str],
    participant_id: str | None = None,
) -> RoiSpectrum:
    """Average electrodes within participant, then participants with equal weight."""

    requested_channels = _resolve_channels(dataset, channels)
    records = _selected_records(
        dataset,
        event_type=event_type,
        trigger_code=trigger_code,
        participant_id=participant_id,
    )
    participant_curves: list[np.ndarray] = []
    participant_ids: list[str] = []
    participant_contributions: list[RoiParticipantContribution] = []
    used: set[str] = set()
    for record in records:
        available = [
            channel for channel in requested_channels if channel in record.channel_names
        ]
        if not available:
            continue
        indices = [record.channel_names.index(channel) for channel in available]
        participant_curve = np.mean(
            record.spectrum.amplitude_uv[indices].astype(np.float64, copy=False),
            axis=0,
        )
        participant_curves.append(participant_curve)
        participant_ids.append(record.participant_id)
        participant_contributions.append(
            RoiParticipantContribution(
                participant_id=record.participant_id,
                used_channels=tuple(available),
                amplitude_uv=participant_curve,
            )
        )
        used.update(available)
    if not participant_curves:
        who = f"participant {participant_id!r}" if participant_id else "any participant"
        raise ValueError(
            f"None of the selected electrodes were available for {who} and this event."
        )

    first = records[0]
    event = SavedEvent(
        first.event_type,
        first.trigger_code,
        first.trigger_label,
        first.target_hz,
    )
    return RoiSpectrum(
        event=event,
        participant_id=participant_id,
        requested_channels=requested_channels,
        used_channels=tuple(channel for channel in requested_channels if channel in used),
        contributing_participant_ids=tuple(participant_ids),
        frequencies=first.spectrum.freqs.copy(),
        amplitude_uv=np.mean(
            np.stack(participant_curves).astype(np.float64, copy=False), axis=0
        ),
        participant_contributions=tuple(participant_contributions),
        provenance=dataset.provenance,
    )


def saved_scalp_values(
    dataset: SavedFftDataset,
    *,
    event_type: str,
    trigger_code: int,
    frequency_hz: float,
    participant_id: str | None = None,
) -> ScalpMapValues:
    """Return participant or equal-participant electrode values at the nearest bin."""

    requested_frequency = float(frequency_hz)
    if not isfinite(requested_frequency):
        raise ValueError("The scalp-map frequency must be a finite number.")
    frequencies = dataset.frequencies
    lower_bound, upper_bound = saved_scalp_frequency_bounds(dataset)
    if requested_frequency < lower_bound or requested_frequency > upper_bound:
        raise ValueError(
            f"The scalp-map frequency must be between {lower_bound:g} and "
            f"{upper_bound:g} Hz."
        )
    usable_indices = np.flatnonzero(
        (frequencies >= lower_bound) & (frequencies <= upper_bound)
    )
    frequency_index = int(
        usable_indices[
            np.argmin(np.abs(frequencies[usable_indices] - requested_frequency))
        ]
    )
    actual_frequency = float(frequencies[frequency_index])
    records = _selected_records(
        dataset,
        event_type=event_type,
        trigger_code=trigger_code,
        participant_id=participant_id,
    )

    channel_names: list[str] = []
    channel_values: list[float] = []
    participant_counts: list[int] = []
    for channel in dataset.channel_names:
        values = [
            float(
                record.spectrum.amplitude_uv[
                    record.channel_names.index(channel), frequency_index
                ]
            )
            for record in records
            if channel in record.channel_names
        ]
        if not values:
            continue
        channel_names.append(channel)
        channel_values.append(float(np.mean(values, dtype=np.float64)))
        participant_counts.append(len(values))

    if not channel_names:
        raise ValueError("No electrode amplitudes were available for this scalp map.")
    first = records[0]
    return ScalpMapValues(
        event=SavedEvent(
            first.event_type,
            first.trigger_code,
            first.trigger_label,
            first.target_hz,
        ),
        participant_id=participant_id,
        requested_frequency_hz=requested_frequency,
        actual_frequency_hz=actual_frequency,
        channel_names=tuple(channel_names),
        amplitude_uv=np.asarray(channel_values, dtype=np.float64),
        participant_counts=tuple(participant_counts),
        provenance=dataset.provenance,
    )


def saved_scalp_frequency_bounds(dataset: SavedFftDataset) -> tuple[float, float]:
    """Return the configured display range supported by the saved FFT grid."""

    frequencies = dataset.frequencies
    lower_bound = max(
        float(frequencies[0]),
        dataset.provenance.plot_fmin_hz,
    )
    upper_bound = min(
        float(frequencies[-1]),
        dataset.provenance.plot_fmax_hz,
    )
    if not np.any((frequencies >= lower_bound) & (frequencies <= upper_bound)):
        raise ValueError(
            "The saved FFT grid has no bins in its recorded "
            f"{dataset.provenance.plot_fmin_hz:g}–"
            f"{dataset.provenance.plot_fmax_hz:g} Hz plot range."
        )
    return lower_bound, upper_bound


def _participant_fft_path(path: str | Path) -> Path:
    selected = Path(path).expanduser()
    source_csv = selected / PARTICIPANT_FFT_FILENAME if selected.is_dir() else selected
    if not source_csv.is_file():
        raise ValueError(
            "Choose an SSSEP run folder containing "
            f"{PARTICIPANT_FFT_FILENAME}, or choose that CSV directly.\n\n"
            f"Selected path: {selected}"
        )
    return source_csv.resolve()


def _convert_numeric_columns(frame: pd.DataFrame, amplitude_columns: list[str]) -> None:
    numeric_columns = [
        "trigger_code",
        "target_hz",
        "usable_epochs",
        "fft_schema_version",
        "sampling_rate_hz",
        "analysis_window_sec",
        "epoch_window_sec",
        "fft_crop_start_sec",
        "fft_crop_end_sec",
        "plot_fmin_hz",
        "plot_fmax_hz",
        "frequency_hz",
        *amplitude_columns,
    ]
    for column in numeric_columns:
        try:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Saved FFT column {column!r} must contain numeric values.") from exc
    if not np.isfinite(frame["frequency_hz"].to_numpy(dtype=float)).all():
        raise ValueError("Saved FFT frequencies must all be finite.")
    if (frame["frequency_hz"] < 0).any():
        raise ValueError("Saved FFT frequencies must be nonnegative.")
    for column in amplitude_columns:
        finite_values = frame[column].dropna().to_numpy(dtype=float)
        if not np.isfinite(finite_values).all():
            raise ValueError(
                f"Saved FFT electrode column {column!r} contains nonfinite values."
            )
        if np.any(finite_values < 0):
            raise ValueError("Saved FFT amplitudes must be nonnegative.")
    for column in ("sampling_rate_hz", "analysis_window_sec", "epoch_window_sec"):
        values = frame[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(values <= 0):
            raise ValueError(
                f"Saved FFT column {column!r} must contain finite values above zero."
            )
    for column in ("fft_crop_start_sec", "fft_crop_end_sec"):
        values = frame[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError(
                f"Saved FFT column {column!r} must contain finite nonnegative values."
            )


def _validate_text_columns(frame: pd.DataFrame) -> None:
    for column in _TEXT_COLUMNS:
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"Saved FFT column {column!r} contains a blank value.")
        frame[column] = frame[column].astype(str).str.strip()
    if not frame["event_type"].isin(("cue", "baseline")).all():
        raise ValueError("Saved FFT event_type values must be 'cue' or 'baseline'.")


def _validate_participant_file_mapping(frame: pd.DataFrame) -> None:
    """Require one BDF filename per participant and one participant per BDF."""

    pairs = frame[["participant_id", "file_name"]].drop_duplicates().copy()
    pairs["participant_key"] = pairs["participant_id"].str.casefold()
    pairs["file_key"] = pairs["file_name"].str.casefold()

    participant_variants = pairs.groupby("participant_key")[
        "participant_id"
    ].nunique()
    if (participant_variants > 1).any():
        participant_key = str(
            participant_variants[participant_variants > 1].index[0]
        )
        participant_ids = pairs.loc[
            pairs["participant_key"] == participant_key,
            "participant_id",
        ].tolist()
        raise ValueError(
            "Participant IDs that differ only by letter case would be counted "
            f"twice: {participant_ids}."
        )

    files_per_participant = pairs.groupby("participant_key")["file_key"].nunique()
    if (files_per_participant > 1).any():
        participant_key = str(files_per_participant[files_per_participant > 1].index[0])
        names = pairs.loc[
            pairs["participant_key"] == participant_key,
            "file_name",
        ].tolist()
        raise ValueError(
            "One saved participant ID is mapped to multiple BDF filenames: "
            f"{names}."
        )

    participants_per_file = pairs.groupby("file_key")["participant_key"].nunique()
    if (participants_per_file > 1).any():
        file_key = str(participants_per_file[participants_per_file > 1].index[0])
        participant_ids = pairs.loc[
            pairs["file_key"] == file_key,
            "participant_id",
        ].tolist()
        raise ValueError(
            "One saved BDF filename is mapped to multiple participant IDs: "
            f"{participant_ids}."
        )


def _validate_integer_column(frame: pd.DataFrame, column: str) -> None:
    values = frame[column].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
        raise ValueError(f"Saved FFT column {column!r} must contain whole numbers.")
    if np.any(values < 1):
        raise ValueError(f"Saved FFT column {column!r} must contain values of 1 or more.")
    frame[column] = values.astype(np.int64)


def _rows_to_record(
    rows: pd.DataFrame,
    amplitude_columns: list[str],
    channel_names: tuple[str, ...],
) -> ParticipantSpectrum:
    frequencies = rows["frequency_hz"].to_numpy(dtype=np.float64)
    if len(frequencies) == 0 or np.any(np.diff(frequencies) <= 0):
        raise ValueError("Each saved participant spectrum needs increasing frequency bins.")
    sampling_rate_hz = _single_float(rows, "sampling_rate_hz")
    analysis_window_sec = _single_float(rows, "analysis_window_sec")
    epoch_window_sec = _single_float(rows, "epoch_window_sec")
    fft_crop_start_sec = _single_float(rows, "fft_crop_start_sec")
    fft_crop_end_sec = _single_float(rows, "fft_crop_end_sec")
    plot_fmin_hz = _single_float(rows, "plot_fmin_hz")
    plot_fmax_hz = _single_float(rows, "plot_fmax_hz")
    if plot_fmin_hz < 0 or plot_fmax_hz <= plot_fmin_hz:
        raise ValueError(
            "Saved plot-frequency provenance needs a nonnegative minimum and a "
            "larger maximum."
        )
    n_samples = int(round(sampling_rate_hz * analysis_window_sec))
    if n_samples < 2:
        raise ValueError(
            "Saved sampling-rate and analysis-window provenance must describe at "
            "least two FFT samples."
        )
    expected_frequencies = np.fft.rfftfreq(
        n_samples,
        d=1.0 / sampling_rate_hz,
    )
    if not np.array_equal(frequencies, expected_frequencies):
        raise ValueError(
            "One saved participant frequency grid does not match its sampling "
            "rate and analysis-window provenance."
        )

    available_channels: list[str] = []
    amplitudes: list[np.ndarray] = []
    for column, channel in zip(amplitude_columns, channel_names):
        values = rows[column].to_numpy(dtype=np.float64)
        if np.isnan(values).all():
            continue
        if not np.isfinite(values).all():
            raise ValueError(
                f"Electrode {channel!r} has missing or nonfinite values within one spectrum."
            )
        available_channels.append(channel)
        amplitudes.append(values)
    if not available_channels:
        raise ValueError("A saved participant spectrum contains no usable electrodes.")

    analysis_channels = tuple(
        channel.strip()
        for channel in _single_text(rows, "analysis_channels").split(";")
        if channel.strip()
    )
    target_values = rows["target_hz"].to_numpy(dtype=np.float64)
    if np.isnan(target_values).all():
        target_hz = None
    else:
        if np.isnan(target_values).any():
            raise ValueError(
                "One saved participant spectrum has target_hz on only some rows."
            )
        if not np.isfinite(target_values).all() or np.any(target_values <= 0):
            raise ValueError("Saved target frequencies must be finite values above zero.")
        if len(np.unique(target_values)) != 1:
            raise ValueError(
                "One saved participant spectrum has inconsistent target frequencies."
            )
        target_hz = float(target_values[0])
        lower_hz = max(float(frequencies[0]), plot_fmin_hz)
        upper_hz = min(float(frequencies[-1]), plot_fmax_hz)
        if not lower_hz <= target_hz <= upper_hz:
            raise ValueError(
                f"Saved target frequency {target_hz:g} Hz is outside the usable "
                f"{lower_hz:g}–{upper_hz:g} Hz range."
            )

    return ParticipantSpectrum(
        participant_id=_single_text(rows, "participant_id"),
        file_name=_single_text(rows, "file_name"),
        event_type=_single_text(rows, "event_type"),
        trigger_code=_single_int(rows, "trigger_code"),
        trigger_label=_single_text(rows, "trigger_label"),
        target_hz=target_hz,
        usable_epochs=_single_int(rows, "usable_epochs"),
        channel_names=tuple(available_channels),
        analysis_channels=analysis_channels,
        spectrum=Spectrum(
            freqs=frequencies,
            amplitude_uv=np.stack(amplitudes).astype(np.float64, copy=False),
            method=_single_text(rows, "processing_method"),
        ),
        fpvs_reference_commit=_single_text(rows, "fpvs_reference_commit"),
        montage_name=_single_text(rows, "montage_name"),
        sampling_rate_hz=sampling_rate_hz,
        analysis_window_sec=analysis_window_sec,
        epoch_window_sec=epoch_window_sec,
        fft_crop_start_sec=fft_crop_start_sec,
        fft_crop_end_sec=fft_crop_end_sec,
        plot_fmin_hz=plot_fmin_hz,
        plot_fmax_hz=plot_fmax_hz,
        fft_schema_version=_single_int(rows, "fft_schema_version"),
    )


def _single_text(rows: pd.DataFrame, column: str) -> str:
    values = rows[column].astype(str).str.strip().unique()
    if len(values) != 1:
        raise ValueError(f"One saved participant spectrum has inconsistent {column} values.")
    return str(values[0])


def _single_int(rows: pd.DataFrame, column: str) -> int:
    values = rows[column].unique()
    if len(values) != 1:
        raise ValueError(f"One saved participant spectrum has inconsistent {column} values.")
    return int(values[0])


def _single_float(rows: pd.DataFrame, column: str) -> float:
    values = rows[column].to_numpy(dtype=np.float64)
    if len(np.unique(values)) != 1:
        raise ValueError(f"One saved participant spectrum has inconsistent {column} values.")
    return float(values[0])


def _selected_records(
    dataset: SavedFftDataset,
    *,
    event_type: str,
    trigger_code: int,
    participant_id: str | None,
) -> tuple[ParticipantSpectrum, ...]:
    records = tuple(
        record
        for record in dataset.records
        if record.event_type == event_type and record.trigger_code == int(trigger_code)
    )
    if not records:
        raise ValueError(
            f"No saved spectra match event_type={event_type!r}, trigger_code={trigger_code}."
        )
    if participant_id is not None:
        participant = str(participant_id).strip()
        records = tuple(
            record for record in records if record.participant_id == participant
        )
        if not records:
            raise ValueError(
                f"Participant {participant!r} has no saved spectrum for this event."
            )
    return records


def _resolve_channels(
    dataset: SavedFftDataset,
    channels: Iterable[str],
) -> tuple[str, ...]:
    lookup = {channel.casefold(): channel for channel in dataset.channel_names}
    resolved: list[str] = []
    unknown: list[str] = []
    for value in channels:
        requested = str(value).strip()
        if not requested:
            continue
        channel = lookup.get(requested.casefold())
        if channel is None:
            unknown.append(requested)
        elif channel not in resolved:
            resolved.append(channel)
    if unknown:
        raise ValueError(f"These electrodes are not in the saved FFT data: {unknown}")
    if not resolved:
        raise ValueError("Select at least one electrode for the FFT plot.")
    return tuple(resolved)


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return tuple(ordered)
