"""Checks for equal-participant FFT aggregation and consolidated tables."""

import numpy as np
import pytest

from sssep_batch.analysis.grouping import (
    average_group_spectra,
    group_spectra_to_dataframe,
    participant_spectra_to_dataframe,
)
from sssep_batch.models import ParticipantSpectrum, Spectrum


FREQUENCIES = np.array([0.0, 10.0, 20.0])


def make_record(
    participant_id: str,
    amplitudes: dict[str, list[float]],
    *,
    usable_epochs: int = 5,
    event_type: str = "cue",
    trigger_code: int = 11,
    trigger_label: str = "BothHands Left Hand",
    target_hz: float | None = 10.0,
    analysis_channels: tuple[str, ...] | None = None,
    frequencies: np.ndarray = FREQUENCIES,
    method: str = "fpvs_amplitude_v1",
) -> ParticipantSpectrum:
    """Build a compact participant spectrum with explicit electrode order."""

    channel_names = tuple(amplitudes)
    return ParticipantSpectrum(
        participant_id=participant_id,
        file_name=f"{participant_id}.bdf",
        event_type=event_type,
        trigger_code=trigger_code,
        trigger_label=trigger_label,
        target_hz=target_hz,
        usable_epochs=usable_epochs,
        channel_names=channel_names,
        analysis_channels=analysis_channels or channel_names,
        sampling_rate_hz=2.0 * float(frequencies[-1]),
        analysis_window_sec=1.0 / float(frequencies[1] - frequencies[0]),
        spectrum=Spectrum(
            freqs=frequencies.copy(),
            amplitude_uv=np.array(list(amplitudes.values()), dtype=np.float64),
            method=method,
        ),
    )


def test_participant_table_has_one_row_per_event_and_frequency() -> None:
    cue = make_record(
        "P01",
        {"C3": [2.0, 4.0, 6.0], "C4": [4.0, 8.0, 12.0]},
        analysis_channels=("C3", "C4"),
    )
    baseline = make_record(
        "P01",
        {"C3": [1.0, 2.0, 3.0], "C4": [3.0, 4.0, 5.0]},
        event_type="baseline",
        trigger_code=100,
        trigger_label="Gap/Break",
        target_hz=None,
        analysis_channels=("C3", "C4"),
    )

    frame = participant_spectra_to_dataframe([cue, baseline])

    assert len(frame) == 2 * len(FREQUENCIES)
    assert frame.groupby(["participant_id", "event_type", "trigger_code"]).ngroups == 2
    cue_rows = frame[frame.event_type == "cue"]
    np.testing.assert_array_equal(cue_rows.frequency_hz, FREQUENCIES)
    np.testing.assert_array_equal(cue_rows.analysis_mean_amplitude_uv, [3.0, 6.0, 9.0])
    np.testing.assert_array_equal(cue_rows.C3_amplitude_uv, [2.0, 4.0, 6.0])
    assert cue_rows.analysis_channels.unique().tolist() == ["C3;C4"]
    assert cue_rows.fft_schema_version.unique().tolist() == [1]
    assert cue_rows.montage_name.unique().tolist() == ["standard_1005"]
    assert cue_rows.sampling_rate_hz.unique().tolist() == [40.0]
    assert cue_rows.analysis_window_sec.unique().tolist() == [0.1]
    assert cue_rows.plot_fmin_hz.unique().tolist() == [3.0]
    assert cue_rows.plot_fmax_hz.unique().tolist() == [50.0]
    assert cue_rows.fpvs_reference_commit.str.len().min() == 40
    assert frame[frame.event_type == "baseline"].shape[0] == len(FREQUENCIES)


def test_group_average_weights_participants_equally_not_by_epoch_count() -> None:
    one_epoch = make_record("P01", {"C3": [2.0, 2.0, 2.0]}, usable_epochs=1)
    nine_epochs = make_record("P02", {"C3": [6.0, 6.0, 6.0]}, usable_epochs=9)

    group = average_group_spectra([one_epoch, nine_epochs])[0]

    np.testing.assert_array_equal(group.spectrum.amplitude_uv[0], [4.0, 4.0, 4.0])
    np.testing.assert_array_equal(group.analysis_mean_amplitude_uv, [4.0, 4.0, 4.0])
    assert group.participant_count == 2
    assert group.channel_participant_counts == (2,)


def test_group_average_aligns_electrodes_by_label_and_allows_missing_electrodes() -> None:
    first = make_record(
        "P01",
        {"C3": [2.0, 4.0, 6.0], "C4": [10.0, 20.0, 30.0]},
        analysis_channels=("C4",),
    )
    reversed_order = make_record(
        "P02",
        {"C4": [30.0, 40.0, 50.0], "C3": [6.0, 8.0, 10.0]},
        analysis_channels=("C4",),
    )
    missing_c3 = make_record(
        "P03",
        {"C4": [50.0, 60.0, 70.0]},
        analysis_channels=("C4",),
    )

    group = average_group_spectra([first, reversed_order, missing_c3])[0]

    assert group.channel_names == ("C3", "C4")
    assert group.channel_participant_counts == (2, 3)
    np.testing.assert_array_equal(group.spectrum.amplitude_uv[0], [4.0, 6.0, 8.0])
    np.testing.assert_array_equal(group.spectrum.amplitude_uv[1], [30.0, 40.0, 50.0])
    np.testing.assert_array_equal(group.analysis_mean_amplitude_uv, [30.0, 40.0, 50.0])


def test_consolidated_tables_mark_unavailable_electrodes_and_report_group_ns() -> None:
    cue_11 = make_record("P01", {"C3": [2.0, 4.0, 6.0], "C4": [4.0, 6.0, 8.0]})
    cue_11_missing_c3 = make_record("P02", {"C4": [8.0, 10.0, 12.0]})
    cue_12 = make_record(
        "P01",
        {"C3": [1.0, 3.0, 5.0]},
        trigger_code=12,
        trigger_label="BothHands Right Hand",
    )

    participant_frame = participant_spectra_to_dataframe(
        [cue_11, cue_11_missing_c3, cue_12]
    )
    groups = average_group_spectra([cue_11, cue_11_missing_c3, cue_12])
    group_frame = group_spectra_to_dataframe(groups)

    p02_rows = participant_frame[participant_frame.participant_id == "P02"]
    assert p02_rows.C3_amplitude_uv.isna().all()
    trigger_11 = group_frame[group_frame.trigger_code == 11]
    assert trigger_11.participant_count.unique().tolist() == [2]
    assert trigger_11.analysis_mean_n_participants.unique().tolist() == [2]
    assert trigger_11.C3_n_participants.unique().tolist() == [1]
    assert trigger_11.C4_n_participants.unique().tolist() == [2]
    assert trigger_11.fft_schema_version.unique().tolist() == [1]
    assert trigger_11.montage_name.unique().tolist() == ["standard_1005"]
    trigger_12 = group_frame[group_frame.trigger_code == 12]
    assert trigger_12.C3_n_participants.unique().tolist() == [1]
    assert trigger_12.C4_n_participants.unique().tolist() == [0]
    assert trigger_12.C4_mean_amplitude_uv.isna().all()


def test_exact_frequency_grid_mismatch_is_rejected() -> None:
    first = make_record("P01", {"C3": [1.0, 2.0, 3.0]})
    changed_bin = make_record(
        "P02",
        {"C3": [1.0, 2.0, 3.0]},
        frequencies=np.array([0.0, 10.0 + 1e-12, 20.0]),
    )

    with pytest.raises(ValueError, match="exactly matching frequency grids"):
        average_group_spectra([first, changed_bin])


def test_duplicate_participant_event_trigger_is_rejected() -> None:
    first = make_record("P01", {"C3": [1.0, 2.0, 3.0]})
    duplicate = make_record("P01", {"C3": [4.0, 5.0, 6.0]}, usable_epochs=9)

    with pytest.raises(ValueError, match="Duplicate participant/event/trigger"):
        participant_spectra_to_dataframe([first, duplicate])


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ({"trigger_label": "Different label"}, "label or target frequency"),
        ({"target_hz": 12.0}, "label or target frequency"),
        ({"method": "different_method"}, "inconsistent processing methods"),
    ],
)
def test_inconsistent_event_metadata_or_processing_method_is_rejected(
    changed: dict[str, object], message: str
) -> None:
    first = make_record("P01", {"C3": [1.0, 2.0, 3.0]})
    second_kwargs = {
        "trigger_label": "BothHands Left Hand",
        "target_hz": 10.0,
        "method": "fpvs_amplitude_v1",
    }
    second_kwargs.update(changed)
    second = make_record(
        "P02",
        {"C3": [4.0, 5.0, 6.0]},
        **second_kwargs,
    )

    with pytest.raises(ValueError, match=message):
        average_group_spectra([first, second])


def test_nonfinite_participant_spectrum_is_rejected() -> None:
    with pytest.raises(ValueError, match="must all be finite"):
        make_record("P01", {"C3": [1.0, np.nan, 3.0]})


def test_mutated_nonfinite_spectrum_is_rejected_before_aggregation() -> None:
    record = make_record("P01", {"C3": [1.0, 2.0, 3.0]})
    record.spectrum.amplitude_uv[0, 1] = np.inf

    with pytest.raises(ValueError, match="nonfinite FFT values"):
        average_group_spectra([record])
