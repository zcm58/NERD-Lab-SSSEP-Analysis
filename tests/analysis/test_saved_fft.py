"""Checks for reloading and plotting consolidated participant FFT data."""

from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest

from sssep_batch.analysis.grouping import participant_spectra_to_dataframe
from sssep_batch.analysis.saved_fft import (
    PARTICIPANT_FFT_FILENAME,
    average_saved_roi,
    load_saved_fft_dataset,
    saved_scalp_values,
)
from sssep_batch.analysis.saved_outputs import (
    create_saved_roi_outputs,
    create_saved_scalp_outputs,
    roi_participant_source_dataframe,
)
from sssep_batch.config import PROCESSING_METHOD
from sssep_batch.models import ParticipantSpectrum, Spectrum


FREQUENCIES = np.array([0.0, 10.0, 20.0])


def make_record(
    participant_id: str,
    amplitudes: dict[str, list[float]],
    *,
    trigger_code: int = 11,
    trigger_label: str = "BothHands Left Hand",
    target_hz: float | None = 10.0,
    event_type: str = "cue",
    frequencies: np.ndarray = FREQUENCIES,
    method: str = "fpvs_amplitude_v1",
    epoch_window_sec: float = 0.2,
    fft_crop_start_sec: float = 0.05,
    fft_crop_end_sec: float = 0.05,
) -> ParticipantSpectrum:
    """Build one compact saved-spectrum source record."""

    channel_names = tuple(amplitudes)
    return ParticipantSpectrum(
        participant_id=participant_id,
        file_name=f"{participant_id}.bdf",
        event_type=event_type,
        trigger_code=trigger_code,
        trigger_label=trigger_label,
        target_hz=target_hz,
        usable_epochs=4,
        channel_names=channel_names,
        analysis_channels=(channel_names[0],),
        sampling_rate_hz=2.0 * float(frequencies[-1]),
        analysis_window_sec=1.0 / float(frequencies[1] - frequencies[0]),
        epoch_window_sec=epoch_window_sec,
        fft_crop_start_sec=fft_crop_start_sec,
        fft_crop_end_sec=fft_crop_end_sec,
        spectrum=Spectrum(
            freqs=frequencies.copy(),
            amplitude_uv=np.asarray(list(amplitudes.values()), dtype=np.float64),
            method=method,
        ),
    )


def write_saved_dataset(tmp_path, records) -> tuple[Path, Path]:
    """Write records using the production participant-table serializer."""

    run_folder = tmp_path / "run_test"
    run_folder.mkdir()
    source_csv = run_folder / PARTICIPANT_FFT_FILENAME
    participant_spectra_to_dataframe(records).to_csv(source_csv, index=False)
    return run_folder, source_csv


def read_scalp_workbook(path: str) -> tuple[dict[str, str | float], dict[int, float]]:
    """Inspect real XLSX cells and sizing without adding a reader dependency."""
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(path) as archive:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.findall("s:sheets/s:sheet", namespace)
        assert [sheet.attrib["name"] for sheet in sheets] == ["FFT amplitudes"]
        strings_xml = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(item.itertext()) for item in strings_xml]
        worksheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    cells = {}
    for cell in worksheet.findall("s:sheetData/s:row/s:c", namespace):
        assert cell.find("s:f", namespace) is None
        raw_value = cell.find("s:v", namespace).text
        if cell.attrib.get("t") == "s":
            value = strings[int(raw_value)]
        else:
            assert cell.attrib.get("t") in (None, "n")
            value = float(raw_value)
        cells[cell.attrib["r"]] = value
    widths = {}
    for column in worksheet.findall("s:cols/s:col", namespace):
        assert column.attrib["customWidth"] == "1"
        for index in range(int(column.attrib["min"]), int(column.attrib["max"]) + 1):
            widths[index] = float(column.attrib["width"])
    assert set(widths) == {1, 2}
    assert all(reference.startswith(("A", "B")) for reference in cells)
    return cells, widths


def test_saved_fft_round_trip_recovers_events_participants_and_electrodes(tmp_path):
    records = (
        make_record("P01", {"C3": [1, 2, 3], "C4": [4, 5, 6]}),
        make_record("P02", {"C4": [7, 8, 9]}),
        make_record(
            "P01",
            {"C3": [0.5, 1, 1.5], "C4": [2, 2.5, 3]},
            event_type="baseline",
            trigger_code=100,
            trigger_label="Gap/Break",
            target_hz=None,
        ),
    )
    run_folder, source_csv = write_saved_dataset(tmp_path, records)

    dataset = load_saved_fft_dataset(run_folder)

    assert dataset.source_csv == source_csv.resolve()
    assert dataset.participant_ids == ("P01", "P02")
    assert dataset.channel_names == ("C3", "C4")
    assert [event.display_name for event in dataset.events] == [
        "Trigger code 11: BothHands Left Hand",
        "Baseline 100: Gap/Break",
    ]
    assert dataset.processing_method == "fpvs_amplitude_v1"
    assert dataset.provenance.fft_schema_version == 1
    assert dataset.provenance.montage_name == "standard_1005"
    assert dataset.provenance.sampling_rate_hz == 40.0
    assert dataset.provenance.analysis_window_sec == 0.1
    assert dataset.provenance.epoch_window_sec == 0.2
    assert dataset.provenance.fft_crop_start_sec == 0.05
    assert dataset.provenance.fft_crop_end_sec == 0.05
    assert dataset.provenance.plot_fmin_hz == 3.0
    assert dataset.provenance.plot_fmax_hz == 50.0
    np.testing.assert_array_equal(dataset.frequencies, FREQUENCIES)


def test_saved_events_list_cues_before_baseline_even_when_exported_baseline_first(
    tmp_path,
):
    baseline = make_record(
        "P01",
        {"C3": [1, 2, 3]},
        event_type="baseline",
        trigger_code=100,
        trigger_label="Gap/Break",
        target_hz=None,
    )
    cue = make_record("P01", {"C3": [2, 3, 4]})
    run_folder, _ = write_saved_dataset(tmp_path, (baseline, cue))

    dataset = load_saved_fft_dataset(run_folder)

    assert [event.event_type for event in dataset.events] == ["cue", "baseline"]


def test_saved_fft_preserves_numeric_and_na_like_participant_ids(tmp_path):
    run_folder, _ = write_saved_dataset(
        tmp_path,
        (
            make_record("001", {"C3": [1, 2, 3]}),
            make_record("NA", {"C3": [2, 3, 4]}),
        ),
    )

    dataset = load_saved_fft_dataset(run_folder)

    assert dataset.participant_ids == ("001", "NA")


@pytest.mark.parametrize("conflict", ["same_file", "same_participant"])
def test_saved_fft_requires_one_bdf_filename_per_participant(tmp_path, conflict):
    second = make_record("P02", {"C3": [2, 3, 4]})
    if conflict == "same_participant":
        second = make_record(
            "P01",
            {"C3": [2, 3, 4]},
            event_type="baseline",
            trigger_code=100,
            trigger_label="Gap/Break",
            target_hz=None,
        )
    run_folder, source_csv = write_saved_dataset(
        tmp_path,
        (make_record("P01", {"C3": [1, 2, 3]}), second),
    )
    frame = pd.read_csv(source_csv)
    if conflict == "same_file":
        frame.loc[frame.participant_id == "P02", "file_name"] = "P01.bdf"
        message = "BDF filename is mapped to multiple participant IDs"
    else:
        frame.loc[frame.event_type == "baseline", "file_name"] = "other.bdf"
        message = "participant ID is mapped to multiple BDF filenames"
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match=message):
        load_saved_fft_dataset(run_folder)


def test_saved_fft_rejects_participant_ids_that_differ_only_by_case(tmp_path):
    run_folder, _ = write_saved_dataset(
        tmp_path,
        (
            make_record("P01", {"C3": [1, 2, 3]}),
            make_record(
                "p01",
                {"C3": [2, 3, 4]},
                trigger_code=12,
                trigger_label="BothHands Right Hand",
            ),
        ),
    )

    with pytest.raises(ValueError, match="differ only by letter case"):
        load_saved_fft_dataset(run_folder)


def test_saved_roi_averages_channels_within_participant_before_group(tmp_path):
    run_folder, _ = write_saved_dataset(
        tmp_path,
        (
            make_record("P01", {"C3": [2, 4, 6], "C4": [4, 8, 12]}),
            make_record("P02", {"C3": [10, 20, 30]}),
        ),
    )
    dataset = load_saved_fft_dataset(run_folder)

    group = average_saved_roi(
        dataset,
        event_type="cue",
        trigger_code=11,
        channels=("c3", "C4"),
    )
    participant = average_saved_roi(
        dataset,
        event_type="cue",
        trigger_code=11,
        channels=("C3", "C4"),
        participant_id="P01",
    )

    np.testing.assert_array_equal(group.amplitude_uv, [6.5, 13.0, 19.5])
    np.testing.assert_array_equal(participant.amplitude_uv, [3.0, 6.0, 9.0])
    assert group.contributing_participant_ids == ("P01", "P02")
    assert group.used_channels == ("C3", "C4")
    assert participant.participant_count == 1
    contributions = roi_participant_source_dataframe(group, "Central ROI")
    membership = contributions.groupby("participant_id").first()
    assert membership.loc["P01", "contributing_electrodes"] == "C3;C4"
    assert membership.loc["P01", "contributing_electrode_count"] == 2
    assert membership.loc["P02", "contributing_electrodes"] == "C3"
    assert membership.loc["P02", "contributing_electrode_count"] == 1


def test_saved_scalp_map_uses_nearest_bin_and_reports_electrode_counts(tmp_path):
    run_folder, _ = write_saved_dataset(
        tmp_path,
        (
            make_record("P01", {"C3": [1, 2, 3], "C4": [2, 6, 4]}),
            make_record("P02", {"C3": [3, 10, 5]}),
        ),
    )
    dataset = load_saved_fft_dataset(run_folder)

    values = saved_scalp_values(
        dataset,
        event_type="cue",
        trigger_code=11,
        frequency_hz=9.7,
    )

    assert values.actual_frequency_hz == 10.0
    assert values.channel_names == ("C3", "C4")
    np.testing.assert_array_equal(values.amplitude_uv, [6.0, 6.0])
    assert values.participant_counts == (2, 1)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.drop(columns="participant_id"), "Missing columns"),
        (
            lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
            "duplicate participant/event/frequency",
        ),
    ],
)
def test_saved_fft_rejects_incomplete_or_duplicate_tables(
    tmp_path, mutation, message
):
    run_folder, source_csv = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    frame = pd.read_csv(source_csv)
    mutation(frame).to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match=message):
        load_saved_fft_dataset(run_folder)


def test_saved_fft_gives_legacy_tables_a_reprocessing_message(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    frame = pd.read_csv(source_csv).drop(
        columns=[
            "fft_schema_version",
            "fpvs_reference_commit",
            "montage_name",
            "sampling_rate_hz",
            "analysis_window_sec",
            "plot_fmin_hz",
            "plot_fmax_hz",
        ]
    )
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match="Reprocess the original BDF files"):
        load_saved_fft_dataset(run_folder)


def test_saved_fft_loads_schema_one_table_without_crop_provenance(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    frame = pd.read_csv(source_csv).drop(
        columns=[
            "epoch_window_sec",
            "fft_crop_start_sec",
            "fft_crop_end_sec",
        ]
    )
    frame.to_csv(source_csv, index=False)

    dataset = load_saved_fft_dataset(run_folder)

    assert dataset.provenance.epoch_window_sec == 0.1
    assert dataset.provenance.fft_crop_start_sec == 0.0
    assert dataset.provenance.fft_crop_end_sec == 0.0


def test_saved_fft_rejects_current_crop_method_without_crop_provenance(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path,
        (make_record("P01", {"C3": [1, 2, 3]}, method=PROCESSING_METHOD),),
    )
    frame = pd.read_csv(source_csv).drop(
        columns=[
            "epoch_window_sec",
            "fft_crop_start_sec",
            "fft_crop_end_sec",
        ]
    )
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match="requires all three"):
        load_saved_fft_dataset(run_folder)


def test_saved_fft_rejects_partial_crop_provenance(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    frame = pd.read_csv(source_csv).drop(columns="fft_crop_end_sec")
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match="all three crop columns or none"):
        load_saved_fft_dataset(run_folder)


def test_saved_fft_rejects_partial_missing_electrode_trace(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    frame = pd.read_csv(source_csv)
    frame.loc[1, "C3_amplitude_uv"] = np.nan
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match="missing or nonfinite values"):
        load_saved_fft_dataset(run_folder)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("frequency_hz", -1.0, "frequencies must be nonnegative"),
        ("C3_amplitude_uv", -1.0, "amplitudes must be nonnegative"),
    ],
)
def test_saved_fft_rejects_negative_frequency_or_amplitude(
    tmp_path,
    column,
    value,
    message,
):
    run_folder, source_csv = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    frame = pd.read_csv(source_csv)
    frame.loc[0, column] = value
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match=message):
        load_saved_fft_dataset(run_folder)


def test_saved_fft_rejects_target_frequency_present_on_only_some_rows(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    frame = pd.read_csv(source_csv)
    frame.loc[1, "target_hz"] = np.nan
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match="target_hz on only some rows"):
        load_saved_fft_dataset(run_folder)


def test_saved_fft_rejects_target_frequency_outside_usable_range(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    frame = pd.read_csv(source_csv)
    frame["target_hz"] = 999.0
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match="outside the usable 3–20 Hz range"):
        load_saved_fft_dataset(run_folder)


def test_saved_fft_rejects_mixed_saved_provenance(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path,
        (
            make_record("P01", {"C3": [1, 2, 3]}),
            make_record("P02", {"C3": [2, 3, 4]}),
        ),
    )
    frame = pd.read_csv(source_csv)
    frame.loc[frame.participant_id == "P02", "montage_name"] = "biosemi64"
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match="inconsistent FFT provenance"):
        load_saved_fft_dataset(run_folder)


def test_saved_fft_rejects_mixed_crop_provenance(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path,
        (
            make_record("P01", {"C3": [1, 2, 3]}),
            make_record("P02", {"C3": [2, 3, 4]}),
        ),
    )
    frame = pd.read_csv(source_csv)
    p02_rows = frame.participant_id == "P02"
    frame.loc[p02_rows, "fft_crop_start_sec"] = 0.0
    frame.loc[p02_rows, "fft_crop_end_sec"] = 0.1
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match="inconsistent FFT provenance"):
        load_saved_fft_dataset(run_folder)


@pytest.mark.parametrize(
    ("second", "message"),
    [
        (
            make_record(
                "P02",
                {"C3": [1, 2, 3]},
                method="different_method",
            ),
            "inconsistent processing methods",
        ),
        (
            make_record(
                "P02",
                {"C3": [1, 2, 3]},
                frequencies=np.array([0.0, 10.1, 20.2]),
            ),
            "exactly matching frequency grids",
        ),
    ],
)
def test_saved_fft_rejects_mixed_methods_or_frequency_grids(tmp_path, second, message):
    first = make_record("P01", {"C3": [1, 2, 3]})
    run_folder = tmp_path / "run_test"
    run_folder.mkdir()
    pd.concat(
        [
            participant_spectra_to_dataframe((first,)),
            participant_spectra_to_dataframe((second,)),
        ],
        ignore_index=True,
    ).to_csv(run_folder / PARTICIPANT_FFT_FILENAME, index=False)

    with pytest.raises(ValueError, match=message):
        load_saved_fft_dataset(run_folder)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("frequency_hz", 19.0),
        ("sampling_rate_hz", 42.0),
        ("analysis_window_sec", 0.2),
    ],
)
def test_saved_fft_grid_must_match_sampling_and_window_provenance(
    tmp_path,
    column,
    value,
):
    run_folder, source_csv = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    frame = pd.read_csv(source_csv)
    if column == "frequency_hz":
        frame.loc[frame.index[-1], column] = value
    else:
        frame[column] = value
    frame.to_csv(source_csv, index=False)

    with pytest.raises(ValueError, match="does not match its sampling"):
        load_saved_fft_dataset(run_folder)


@pytest.mark.parametrize("participant_id", [None, "P02"])
def test_saved_roi_and_scalp_outputs_include_exact_source_data(tmp_path, participant_id):
    channels = {
        "Fp1": [1, 2.123456789012345, 3],
        "Fp2": [2, 3, 4],
        "F7": [3, 4, 5],
        "F8": [4, 5, 6],
        "C3": [5, 6, 7],
        "C4": [6, 7, 8],
        "O1": [7, 8, 9],
        "O2": [8, 9, 10],
    }
    second_channels = {
        channel: [value + 10 for value in amplitudes]
        for channel, amplitudes in channels.items()
    }
    run_folder, source_csv = write_saved_dataset(
        tmp_path,
        (make_record("P01", channels), make_record("P02", second_channels)),
    )
    original_source = source_csv.read_bytes()
    dataset = load_saved_fft_dataset(run_folder)

    roi_result = create_saved_roi_outputs(
        dataset,
        event_type="cue",
        trigger_code=11,
        channels=("C3", "C4"),
        roi_name="Central ROI",
    )
    scalp_result = create_saved_scalp_outputs(
        dataset,
        event_type="cue",
        trigger_code=11,
        frequency_hz=11.0,
        participant_id=participant_id,
    )

    for result in (roi_result, scalp_result):
        assert result["plot_path"].endswith(".png")
        assert (run_folder / "saved_fft_plots") in Path(result["plot_path"]).parents
    assert roi_result["source_csv"].endswith("_data.csv")
    roi_source = pd.read_csv(roi_result["source_csv"])
    assert not roi_source.empty
    assert {
        "fpvs_reference_commit", "epoch_window_sec", "fft_crop_start_sec", "fft_crop_end_sec",
    }.issubset(roi_source.columns)
    participant_values = pd.read_csv(roi_result["participant_source_csv"])
    assert set(participant_values.participant_id) == {"P01", "P02"}

    assert "source_csv" not in scalp_result
    workbook_path = Path(scalp_result["source_xlsx"])
    assert workbook_path.name == f"{participant_id or 'group'}_cue_011_10_Hz_scalp_map_data.xlsx"
    assert sorted(path.suffix for path in workbook_path.parent.iterdir()) == [".png", ".xlsx"]
    cells, widths = read_scalp_workbook(str(workbook_path))
    assert cells["A1"] == "Electrode"
    assert cells["B1"] == "FFT amplitude (µV)"
    assert len(cells) == 2 * (len(channels) + 1)
    assert widths[1] >= 9.0  # Header is wider than Excel's default 8.43 characters.
    assert widths[2] >= 18.0
    assert [cells[f"A{index}"] for index in range(2, 10)] == list(channels)
    expected = [values[1] + (5 if participant_id is None else 10) for values in channels.values()]
    assert [cells[f"B{index}"] for index in range(2, 10)] == pytest.approx(expected, rel=1e-14)
    assert all(isinstance(cells[f"B{index}"], float) for index in range(2, 10))
    assert scalp_result["requested_frequency_hz"] == 11.0
    assert scalp_result["actual_frequency_hz"] == 10.0
    assert source_csv.read_bytes() == original_source


def test_saved_roi_stimulation_override_changes_only_png_marker(tmp_path, monkeypatch):
    from sssep_batch.analysis import plotting

    run_folder, source_csv = write_saved_dataset(
        tmp_path,
        (
            make_record("P01", {"C3": [1, 2, 3], "C4": [3, 6, 9]}, target_hz=10.0),
            make_record("P02", {"C3": [2, 4, 6], "C4": [6, 12, 18]}, target_hz=10.0),
        ),
    )
    original_source = source_csv.read_bytes()
    dataset = load_saved_fft_dataset(run_folder)
    figures = []
    monkeypatch.setattr(plotting.plt.Figure, "savefig", lambda figure, *_args, **_kwargs: figures.append(figure))

    original = create_saved_roi_outputs(
        dataset, event_type="cue", trigger_code=11, channels=("C3", "C4"), roi_name="Central",
    )
    overridden = create_saved_roi_outputs(
        dataset, event_type="cue", trigger_code=11, channels=("C3", "C4"), roi_name="Central",
        stimulation_hz=26.0,
    )

    for result_key in ("source_csv", "participant_source_csv"):
        assert Path(original[result_key]).read_bytes() == Path(overridden[result_key]).read_bytes()
    source = pd.read_csv(overridden["source_csv"])
    assert source.target_hz.tolist() == [10.0, 10.0, 10.0]
    np.testing.assert_array_equal(source.fft_amplitude_uv, [3.0, 6.0, 9.0])
    for figure, expected_frequency in zip(figures, [10.0, 26.0]):
        axes = figure.axes[0]
        marker = next(line for line in axes.lines if line.get_label() == "TENS Unit Stimulation Frequency")
        assert list(marker.get_xdata()) == [expected_frequency, expected_frequency]
        assert marker.get_linestyle() == "--"
        np.testing.assert_array_equal(axes.lines[0].get_ydata(), source.fft_amplitude_uv)
    assert len(figures) == 2
    assert dataset.events[0].target_hz == 10.0
    assert source_csv.read_bytes() == original_source


def test_saved_scalp_plot_requires_four_mapped_electrodes(tmp_path):
    run_folder, _ = write_saved_dataset(
        tmp_path,
        (
            make_record(
                "P01",
                {
                    "C3": [1, 2, 3],
                    "C4": [2, 3, 4],
                    "Cz": [3, 4, 5],
                    "Unknown": [4, 5, 6],
                },
            ),
        ),
    )
    dataset = load_saved_fft_dataset(run_folder)

    with pytest.raises(ValueError, match="At least four montage electrodes"):
        create_saved_scalp_outputs(
            dataset,
            event_type="cue",
            trigger_code=11,
            frequency_hz=10.0,
        )
    assert not list((run_folder / "saved_fft_plots").glob("plot_*"))


def test_saved_scalp_plot_omits_unmapped_electrodes_and_records_them(tmp_path):
    run_folder, _ = write_saved_dataset(
        tmp_path,
        (
            make_record(
                "P01",
                {
                    "Fp1": [1, 2, 3],
                    "Fp2": [2, 3, 4],
                    "C3": [3, 4, 5],
                    "C4": [4, 5, 6],
                    "Unknown": [5, 6, 7],
                },
            ),
        ),
    )
    dataset = load_saved_fft_dataset(run_folder)

    result = create_saved_scalp_outputs(
        dataset,
        event_type="cue",
        trigger_code=11,
        frequency_hz=10.0,
    )

    assert result["omitted_channels"] == ["Unknown"]
    cells, _ = read_scalp_workbook(result["source_xlsx"])
    assert len(cells) == 12
    assert cells["A6"] == "Unknown"
    assert cells["B6"] == 6.0


def test_saved_scalp_plot_uses_the_montage_recorded_in_the_csv(tmp_path):
    run_folder, source_csv = write_saved_dataset(
        tmp_path,
        (
            make_record(
                "P01",
                {
                    "Fp1": [1, 2, 3],
                    "Fp2": [2, 3, 4],
                    "C3": [3, 4, 5],
                    "C4": [4, 5, 6],
                },
            ),
        ),
    )
    frame = pd.read_csv(source_csv)
    frame["montage_name"] = "not_a_real_montage"
    frame.to_csv(source_csv, index=False)
    dataset = load_saved_fft_dataset(run_folder)

    with pytest.raises(ValueError, match="saved montage 'not_a_real_montage'"):
        create_saved_scalp_outputs(
            dataset,
            event_type="cue",
            trigger_code=11,
            frequency_hz=10.0,
        )
    assert not list((run_folder / "saved_fft_plots").glob("plot_*"))


def test_failed_roi_render_removes_partial_output_folder(
    tmp_path,
    monkeypatch,
):
    import sssep_batch.analysis.saved_outputs as saved_outputs

    run_folder, _ = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    dataset = load_saved_fft_dataset(run_folder)

    def fail_render(*_args, **_kwargs):
        raise RuntimeError("synthetic render failure")

    monkeypatch.setattr(saved_outputs, "plot_saved_roi_spectrum", fail_render)

    with pytest.raises(RuntimeError, match="synthetic render failure"):
        create_saved_roi_outputs(
            dataset,
            event_type="cue",
            trigger_code=11,
            channels=("C3",),
            roi_name="C3",
        )
    assert not list((run_folder / "saved_fft_plots").glob("plot_*"))


def test_failed_scalp_workbook_removes_png_and_partial_workbook(tmp_path, monkeypatch):
    import sssep_batch.analysis.saved_outputs as saved_outputs

    run_folder, source_csv = write_saved_dataset(
        tmp_path,
        (make_record("P01", {
            "Fp1": [1, 2, 3], "Fp2": [2, 3, 4],
            "C3": [3, 4, 5], "C4": [4, 5, 6],
        }),),
    )
    original_source = source_csv.read_bytes()
    dataset = load_saved_fft_dataset(run_folder)
    old_folder = run_folder / "saved_fft_plots" / "previous_success"
    old_folder.mkdir(parents=True)
    previous_png = old_folder / "keep.png"
    previous_png.write_bytes(b"previous successful output")
    attempts = []

    def fail_workbook(_values, output_path):
        output_path = Path(output_path)
        assert len(list(output_path.parent.glob("*.png"))) == 1
        output_path.write_bytes(b"partial workbook")
        attempts.append(output_path)
        raise OSError("synthetic workbook failure")

    monkeypatch.setattr(saved_outputs, "_write_scalp_workbook", fail_workbook)
    with pytest.raises(OSError, match="synthetic workbook failure"):
        create_saved_scalp_outputs(
            dataset, event_type="cue", trigger_code=11, frequency_hz=10.0,
        )
    assert len(attempts) == 1
    assert not attempts[0].parent.exists()
    assert previous_png.read_bytes() == b"previous successful output"
    assert source_csv.read_bytes() == original_source


def test_saved_scalp_frequency_is_limited_to_configured_plot_range(tmp_path):
    run_folder, _ = write_saved_dataset(
        tmp_path, (make_record("P01", {"C3": [1, 2, 3]}),)
    )
    dataset = load_saved_fft_dataset(run_folder)

    with pytest.raises(ValueError, match="between 3 and 20 Hz"):
        saved_scalp_values(
            dataset,
            event_type="cue",
            trigger_code=11,
            frequency_hz=0.0,
        )
