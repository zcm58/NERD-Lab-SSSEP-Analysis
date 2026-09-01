"""Combine participant-level FFT amplitudes without weighting by trial count."""

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from sssep_batch.models import ParticipantSpectrum, Spectrum


@dataclass(frozen=True, slots=True)
class GroupSpectrum:
    """Equal-participant mean amplitudes for one event and its electrode counts."""

    event_type: str
    trigger_code: int
    trigger_label: str
    target_hz: float | None
    participant_count: int
    channel_names: tuple[str, ...]
    channel_participant_counts: tuple[int, ...]
    analysis_mean_amplitude_uv: np.ndarray
    spectrum: Spectrum
    fpvs_reference_commit: str
    montage_name: str
    sampling_rate_hz: float
    analysis_window_sec: float
    epoch_window_sec: float
    fft_crop_start_sec: float
    fft_crop_end_sec: float
    plot_fmin_hz: float
    plot_fmax_hz: float
    fft_schema_version: int


def _validate_records(
    records: Iterable[ParticipantSpectrum],
) -> tuple[ParticipantSpectrum, ...]:
    """Return records after validating all cross-participant alignment metadata."""

    records = tuple(records)
    if not records:
        raise ValueError("At least one participant spectrum is required.")
    if not all(isinstance(record, ParticipantSpectrum) for record in records):
        raise TypeError("All records must be ParticipantSpectrum values.")

    first = records[0]
    expected_freqs = np.asarray(first.spectrum.freqs)
    expected_method = first.spectrum.method
    expected_provenance = (
        first.fpvs_reference_commit,
        first.montage_name,
        first.sampling_rate_hz,
        first.analysis_window_sec,
        first.epoch_window_sec,
        first.fft_crop_start_sec,
        first.fft_crop_end_sec,
        first.plot_fmin_hz,
        first.plot_fmax_hz,
        first.fft_schema_version,
    )
    definitions: dict[tuple[str, int], tuple[str, float | None]] = {}
    seen_records: set[tuple[str, str, int]] = set()

    for record in records:
        record_key = (record.participant_id, record.event_type, record.trigger_code)
        if record_key in seen_records:
            raise ValueError(
                "Duplicate participant/event/trigger record: "
                f"participant={record.participant_id!r}, event_type={record.event_type!r}, "
                f"trigger_code={record.trigger_code}."
            )
        seen_records.add(record_key)

        event_key = (record.event_type, record.trigger_code)
        definition = (record.trigger_label, record.target_hz)
        if event_key in definitions and definitions[event_key] != definition:
            raise ValueError(
                "Inconsistent trigger label or target frequency for "
                f"event_type={record.event_type!r}, trigger_code={record.trigger_code}."
            )
        definitions[event_key] = definition

        if record.spectrum.method != expected_method:
            raise ValueError("Participant spectra use inconsistent processing methods.")
        if not np.array_equal(record.spectrum.freqs, expected_freqs):
            raise ValueError(
                "Participant spectra must use exactly matching frequency grids; "
                f"participant {record.participant_id!r} does not match."
            )
        provenance = (
            record.fpvs_reference_commit,
            record.montage_name,
            record.sampling_rate_hz,
            record.analysis_window_sec,
            record.epoch_window_sec,
            record.fft_crop_start_sec,
            record.fft_crop_end_sec,
            record.plot_fmin_hz,
            record.plot_fmax_hz,
            record.fft_schema_version,
        )
        if provenance != expected_provenance:
            raise ValueError("Participant spectra use inconsistent FFT provenance.")
        if (
            record.spectrum.amplitude_uv.shape
            != (len(record.channel_names), len(record.spectrum.freqs))
        ):
            raise ValueError(
                f"Participant {record.participant_id!r} has amplitudes that do not "
                "match its electrode labels and frequency grid."
            )
        if not np.isfinite(record.spectrum.freqs).all() or not np.isfinite(
            record.spectrum.amplitude_uv
        ).all():
            raise ValueError(
                f"Participant {record.participant_id!r} has nonfinite FFT values."
            )

    return records


def _ordered_channels(records: Iterable[ParticipantSpectrum]) -> tuple[str, ...]:
    """Return the first-seen union of electrode labels."""

    channels: list[str] = []
    seen: set[str] = set()
    for record in records:
        for channel in record.channel_names:
            if channel not in seen:
                channels.append(channel)
                seen.add(channel)
    return tuple(channels)


def _participant_analysis_mean(record: ParticipantSpectrum) -> np.ndarray:
    """Average configured analysis electrodes after the participant FFT."""

    indices = [record.channel_names.index(channel) for channel in record.analysis_channels]
    return np.mean(
        record.spectrum.amplitude_uv[indices].astype(np.float64, copy=False),
        axis=0,
    )


def participant_spectra_to_dataframe(
    records: Iterable[ParticipantSpectrum],
) -> pd.DataFrame:
    """Return one wide row per participant, event, and frequency bin."""

    records = _validate_records(records)
    all_channels = _ordered_channels(records)
    frames: list[pd.DataFrame] = []

    for record in records:
        rows: dict[str, object] = {
            "participant_id": record.participant_id,
            "file_name": record.file_name,
            "event_type": record.event_type,
            "trigger_code": record.trigger_code,
            "trigger_label": record.trigger_label,
            "target_hz": np.full(
                len(record.spectrum.freqs),
                np.nan if record.target_hz is None else record.target_hz,
                dtype=np.float64,
            ),
            "usable_epochs": record.usable_epochs,
            "processing_method": record.spectrum.method,
            "fft_schema_version": record.fft_schema_version,
            "fpvs_reference_commit": record.fpvs_reference_commit,
            "montage_name": record.montage_name,
            "sampling_rate_hz": record.sampling_rate_hz,
            "analysis_window_sec": record.analysis_window_sec,
            "epoch_window_sec": record.epoch_window_sec,
            "fft_crop_start_sec": record.fft_crop_start_sec,
            "fft_crop_end_sec": record.fft_crop_end_sec,
            "plot_fmin_hz": record.plot_fmin_hz,
            "plot_fmax_hz": record.plot_fmax_hz,
            "analysis_channels": ";".join(record.analysis_channels),
            "frequency_hz": record.spectrum.freqs,
            "analysis_mean_amplitude_uv": _participant_analysis_mean(record),
        }
        channel_indices = {
            channel: index for index, channel in enumerate(record.channel_names)
        }
        for channel in all_channels:
            if channel in channel_indices:
                rows[f"{channel}_amplitude_uv"] = record.spectrum.amplitude_uv[
                    channel_indices[channel]
                ]
            else:
                rows[f"{channel}_amplitude_uv"] = np.full(
                    len(record.spectrum.freqs), np.nan
                )
        frames.append(pd.DataFrame(rows))

    return pd.concat(frames, ignore_index=True)


def average_group_spectra(
    records: Iterable[ParticipantSpectrum],
) -> tuple[GroupSpectrum, ...]:
    """Average participant amplitude spectra with one equal vote per participant."""

    records = _validate_records(records)
    event_groups: dict[tuple[str, int], list[ParticipantSpectrum]] = {}
    for record in records:
        event_groups.setdefault((record.event_type, record.trigger_code), []).append(record)

    groups: list[GroupSpectrum] = []
    for grouped_records in event_groups.values():
        first = grouped_records[0]
        channel_names = _ordered_channels(grouped_records)
        channel_means: list[np.ndarray] = []
        channel_counts: list[int] = []
        for channel in channel_names:
            amplitudes = [
                record.spectrum.amplitude_uv[record.channel_names.index(channel)]
                for record in grouped_records
                if channel in record.channel_names
            ]
            channel_means.append(
                np.mean(np.stack(amplitudes).astype(np.float64, copy=False), axis=0)
            )
            channel_counts.append(len(amplitudes))

        participant_analysis_means = np.stack(
            [_participant_analysis_mean(record) for record in grouped_records]
        )
        groups.append(
            GroupSpectrum(
                event_type=first.event_type,
                trigger_code=first.trigger_code,
                trigger_label=first.trigger_label,
                target_hz=first.target_hz,
                participant_count=len(grouped_records),
                channel_names=channel_names,
                channel_participant_counts=tuple(channel_counts),
                analysis_mean_amplitude_uv=np.mean(
                    participant_analysis_means.astype(np.float64, copy=False), axis=0
                ),
                spectrum=Spectrum(
                    freqs=first.spectrum.freqs.copy(),
                    amplitude_uv=np.stack(channel_means),
                    method=first.spectrum.method,
                ),
                fpvs_reference_commit=first.fpvs_reference_commit,
                montage_name=first.montage_name,
                sampling_rate_hz=first.sampling_rate_hz,
                analysis_window_sec=first.analysis_window_sec,
                epoch_window_sec=first.epoch_window_sec,
                fft_crop_start_sec=first.fft_crop_start_sec,
                fft_crop_end_sec=first.fft_crop_end_sec,
                plot_fmin_hz=first.plot_fmin_hz,
                plot_fmax_hz=first.plot_fmax_hz,
                fft_schema_version=first.fft_schema_version,
            )
        )

    return tuple(groups)


def group_spectra_to_dataframe(groups: Iterable[GroupSpectrum]) -> pd.DataFrame:
    """Return one wide row per group event and frequency bin, including all Ns."""

    groups = tuple(groups)
    if not groups:
        raise ValueError("At least one group spectrum is required.")
    if not all(isinstance(group, GroupSpectrum) for group in groups):
        raise TypeError("All groups must be GroupSpectrum values.")

    expected_freqs = groups[0].spectrum.freqs
    expected_method = groups[0].spectrum.method
    expected_provenance = (
        groups[0].fpvs_reference_commit,
        groups[0].montage_name,
        groups[0].sampling_rate_hz,
        groups[0].analysis_window_sec,
        groups[0].epoch_window_sec,
        groups[0].fft_crop_start_sec,
        groups[0].fft_crop_end_sec,
        groups[0].plot_fmin_hz,
        groups[0].plot_fmax_hz,
        groups[0].fft_schema_version,
    )
    seen_groups: set[tuple[str, int]] = set()
    all_channels: list[str] = []
    seen_channels: set[str] = set()
    for group in groups:
        key = (group.event_type, group.trigger_code)
        if key in seen_groups:
            raise ValueError(f"Duplicate group spectrum for {key}.")
        seen_groups.add(key)
        if group.spectrum.method != expected_method:
            raise ValueError("Group spectra use inconsistent processing methods.")
        provenance = (
            group.fpvs_reference_commit,
            group.montage_name,
            group.sampling_rate_hz,
            group.analysis_window_sec,
            group.epoch_window_sec,
            group.fft_crop_start_sec,
            group.fft_crop_end_sec,
            group.plot_fmin_hz,
            group.plot_fmax_hz,
            group.fft_schema_version,
        )
        if provenance != expected_provenance:
            raise ValueError("Group spectra use inconsistent FFT provenance.")
        if not np.array_equal(group.spectrum.freqs, expected_freqs):
            raise ValueError("Group spectra must use exactly matching frequency grids.")
        if group.spectrum.amplitude_uv.shape != (
            len(group.channel_names), len(group.spectrum.freqs)
        ):
            raise ValueError("Group amplitudes do not match electrode labels and frequencies.")
        if len(group.channel_names) != len(group.channel_participant_counts):
            raise ValueError("Group electrode labels and participant counts must align.")
        if group.analysis_mean_amplitude_uv.shape != group.spectrum.freqs.shape:
            raise ValueError("Group analysis mean must match the frequency grid.")
        if not np.isfinite(group.spectrum.amplitude_uv).all() or not np.isfinite(
            group.analysis_mean_amplitude_uv
        ).all():
            raise ValueError("Group spectrum values must all be finite.")
        for channel in group.channel_names:
            if channel not in seen_channels:
                all_channels.append(channel)
                seen_channels.add(channel)

    frames: list[pd.DataFrame] = []
    for group in groups:
        rows: dict[str, object] = {
            "event_type": group.event_type,
            "trigger_code": group.trigger_code,
            "trigger_label": group.trigger_label,
            "target_hz": np.full(
                len(group.spectrum.freqs),
                np.nan if group.target_hz is None else group.target_hz,
                dtype=np.float64,
            ),
            "participant_count": group.participant_count,
            "processing_method": group.spectrum.method,
            "fft_schema_version": group.fft_schema_version,
            "fpvs_reference_commit": group.fpvs_reference_commit,
            "montage_name": group.montage_name,
            "sampling_rate_hz": group.sampling_rate_hz,
            "analysis_window_sec": group.analysis_window_sec,
            "epoch_window_sec": group.epoch_window_sec,
            "fft_crop_start_sec": group.fft_crop_start_sec,
            "fft_crop_end_sec": group.fft_crop_end_sec,
            "plot_fmin_hz": group.plot_fmin_hz,
            "plot_fmax_hz": group.plot_fmax_hz,
            "frequency_hz": group.spectrum.freqs,
            "analysis_mean_amplitude_uv": group.analysis_mean_amplitude_uv,
            "analysis_mean_n_participants": group.participant_count,
        }
        channel_indices = {
            channel: index for index, channel in enumerate(group.channel_names)
        }
        for channel in all_channels:
            if channel in channel_indices:
                index = channel_indices[channel]
                rows[f"{channel}_mean_amplitude_uv"] = group.spectrum.amplitude_uv[index]
                rows[f"{channel}_n_participants"] = group.channel_participant_counts[index]
            else:
                rows[f"{channel}_mean_amplitude_uv"] = np.full(
                    len(group.spectrum.freqs), np.nan
                )
                rows[f"{channel}_n_participants"] = 0
        frames.append(pd.DataFrame(rows))

    return pd.concat(frames, ignore_index=True)
