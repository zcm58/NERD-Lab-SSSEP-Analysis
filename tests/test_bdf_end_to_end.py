"""Exercise real BDF loading, preprocessing, amplitude export, and batch workers.

All recordings are generated here from deterministic signals, never participant
data. edfio writes the documented 24-bit BDF format; MNE reads it independently.
Only plotting settings are changed by tests, never the processing functions.
"""

from pathlib import Path
import shutil

import edfio
import mne
import numpy as np
import pandas as pd
from PIL import Image
import pytest

from sssep_batch import batch, config, pipeline
from sssep_batch.analysis.saved_fft import (
    average_saved_roi,
    load_saved_fft_dataset,
    saved_scalp_values,
)
from sssep_batch.loading import load_bdf
from sssep_batch.models import AnalysisProtocol, AnalysisTrigger


TEST_PROTOCOL = AnalysisProtocol(
    active_triggers=tuple(
        AnalysisTrigger(code, config.TRIGGER_LABELS[code], 10.0)
        for code in config.ACTIVE_EVENT_CODES
    ),
    event_duration_sec=config.EVENT_DURATION_SEC,
    expected_repetitions_per_trigger=config.EXPECTED_REPETITIONS_PER_TRIGGER,
    baseline_event_code=config.BASELINE_EVENT_CODE,
    baseline_label=config.TRIGGER_LABELS[config.BASELINE_EVENT_CODE],
)


def write_synthetic_bdf(path: Path, sfreq: int = 512) -> dict[str, object]:
    """Write 90 seconds of 64 scalp channels, EXG1/2, and digital Status pulses.

    EEG values supplied to edfio are in microvolts. Status is written directly
    as digital integers, avoiding physical-to-digital rounding of trigger codes.
    API: https://edfio.readthedocs.io/en/stable/generated/edfio.BdfSignal.html
    """
    scalp_channels = mne.channels.make_standard_montage("biosemi64").ch_names
    duration_sec = 90
    times = np.arange(duration_sec * sfreq) / sfreq
    rng = np.random.default_rng(5261)
    carrier = sum(
        amplitude * np.sin(2 * np.pi * frequency * times)
        for frequency, amplitude in ((10, 3), (17, 1), (23, 0.7), (34, 0.4), (45, 0.3))
    )
    common = 1.2 * np.sin(2 * np.pi * 0.35 * times) + 0.4 * np.cos(2 * np.pi * 7 * times)
    # Opposite pairs with equal gain have zero mean signal across the scalp.
    gains = np.repeat(np.linspace(0.75, 1.25, 32), 2) * np.tile([1, -1], 32)
    signals = []
    probe_samples_uv = None
    for index, channel in enumerate(scalp_channels):
        samples_uv = gains[index] * carrier + common + rng.normal(0, 0.03, len(times))
        if index == 0:
            probe_samples_uv = samples_uv[:64].copy()
        signals.append(edfio.BdfSignal(
            samples_uv, sfreq, label=channel,
            physical_dimension="uV", physical_range=(-100, 100),
        ))
    for channel in ("EXG1", "EXG2"):
        reference_uv = 0.8 * np.sin(2 * np.pi * 0.35 * times) + rng.normal(0, 0.03, len(times))
        signals.append(edfio.BdfSignal(
            reference_uv, sfreq, label=channel,
            physical_dimension="uV", physical_range=(-100, 100),
        ))

    codes = [11, 12, 21, 22, 100, 11, 100, 9, 100, 11]
    onsets = np.rint((0.125 + 8 * np.arange(len(codes))) * sfreq).astype(int)
    status = np.zeros(len(times), dtype=np.int32)
    for sample, code in zip(onsets, codes):
        status[sample:sample + 4] = code
    signals.append(edfio.BdfSignal.from_digital(
        status, sfreq, label="Status", digital_range=(-8388608, 8388607),
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    edfio.Bdf(signals, data_record_duration=1).write(path)
    return {
        "scalp_channels": scalp_channels,
        "channel_names": scalp_channels + ["EXG1", "EXG2", "Status"],
        "sfreq": sfreq,
        "duration_sec": duration_sec,
        "events": np.column_stack([onsets, np.zeros(len(codes), dtype=int), codes]),
        "active_counts": {11: 3, 12: 1, 21: 1, 22: 1},
        "baseline_count": 3,
        "probe_channel": scalp_channels[0],
        "probe_samples_uv": probe_samples_uv,
        "target_amplitude_uv": 3 * abs(gains[0]),
    }


@pytest.fixture
def synthetic_bdf(tmp_path):
    path = tmp_path / "input" / "Synthetic_A.bdf"
    return path, write_synthetic_bdf(path)


def test_actual_bdf_reader_preserves_microvolts_channels_and_digital_events(synthetic_bdf):
    path, known = synthetic_bdf
    with load_bdf(path) as raw:
        assert raw.ch_names == known["channel_names"]
        assert raw.info["sfreq"] == known["sfreq"]
        assert raw.n_times == known["duration_sec"] * known["sfreq"]
        np.testing.assert_allclose(
            raw.get_data(picks=[known["probe_channel"]], stop=64)[0] * 1e6,
            known["probe_samples_uv"], atol=7e-6, rtol=0,
        )
        events = mne.find_events(raw, stim_channel="Status", shortest_event=1, verbose=False)
        np.testing.assert_array_equal(events, known["events"])


def _check_processing_summary(result: dict[str, object], known: dict[str, object]) -> pd.DataFrame:
    assert result["status"] == "success", result
    assert result["original_sfreq_hz"] == 512
    assert result["final_sfreq_hz"] == 256
    output = Path(result["output_folder"])
    summary = pd.read_csv(result["summary_csv"]).set_index("trigger_code")
    assert summary.index.tolist() == config.ACTIVE_EVENT_CODES
    assert set(summary.columns) >= {
        "sssep_fft_nearest_amplitude_uv", "sssep_fft_local_amplitude_snr",
        "sssep_fft_active_vs_baseline_amplitude_ratio",
    }
    assert not any("welch" in name or "power" in name for name in summary.columns)
    assert (summary["baseline_usable_epochs"] == known["baseline_count"]).all()
    assert (summary["edge_excluded_epochs"] == 0).all()
    assert (summary["out_of_bounds_epochs"] == 0).all()
    assert (summary["baseline_edge_excluded_epochs"] == 0).all()
    assert (summary["epoch_window_sec"] == 15.0).all()
    assert (summary["fft_crop_start_sec"] == 2.5).all()
    assert (summary["fft_crop_end_sec"] == 2.5).all()
    assert (summary["analysis_window_sec"] == 10.0).all()
    for code in config.ACTIVE_EVENT_CODES:
        expected = known["active_counts"].get(code, 0)
        assert summary.loc[code, "usable_epochs"] == expected
        assert summary.loc[code, "status"] == ("success" if expected else "no_complete_epochs")
        if not expected:
            assert np.isnan(summary.loc[code, "sssep_fft_nearest_amplitude_uv"])

    detected = pd.read_csv(output / "detected_status_events.csv")
    np.testing.assert_array_equal(detected["trigger_code"], known["events"][:, 2])
    np.testing.assert_array_equal(detected["sample"], known["events"][:, 0] // 2)
    assert not bool(detected.loc[detected["trigger_code"] == 9, "intended_for_analysis_or_baseline"].iloc[0])
    assert detected["sample"].iloc[0] == 32  # The complete first trial is retained near the FIR boundary.

    assert not list(output.rglob("*_sssep_fft_amplitude.csv"))
    assert not list(output.rglob("*welch*"))
    assert not (output / "ERROR.txt").exists()
    report = next(output.glob("*_processing_report.txt")).read_text(encoding="utf-8")
    assert "FPVS" in report and "amplitude" in report.lower()
    return summary


def _check_participant_spectra(
    result: dict[str, object], known: dict[str, object], summary: pd.DataFrame
) -> None:
    records = result["_participant_spectra"]
    assert len(records) == 1 + len(known["active_counts"])
    baseline_records = [record for record in records if record.event_type == "baseline"]
    cue_records = [record for record in records if record.event_type == "cue"]
    assert len(baseline_records) == 1
    assert [record.trigger_code for record in cue_records] == config.ACTIVE_EVENT_CODES
    assert baseline_records[0].usable_epochs == known["baseline_count"]
    assert [record.usable_epochs for record in cue_records] == [
        known["active_counts"][code] for code in config.ACTIVE_EVENT_CODES
    ]
    assert all(record.channel_names == tuple(known["scalp_channels"]) for record in records)
    assert all(record.epoch_window_sec == 15.0 for record in records)
    assert all(record.fft_crop_start_sec == 2.5 for record in records)
    assert all(record.fft_crop_end_sec == 2.5 for record in records)
    assert all(record.analysis_window_sec == 10.0 for record in records)

    cue_11 = next(record for record in cue_records if record.trigger_code == 11)
    expected_frequencies = np.fft.rfftfreq(2560, 1 / 256)
    np.testing.assert_allclose(cue_11.spectrum.freqs, expected_frequencies)
    assert cue_11.spectrum.amplitude_uv.shape == (64, 1281)
    probe_index = cue_11.channel_names.index(known["probe_channel"])
    nearest = int(np.argmin(abs(cue_11.spectrum.freqs - 10)))
    assert cue_11.spectrum.amplitude_uv[probe_index, nearest] == pytest.approx(
        known["target_amplitude_uv"], rel=0.05,
    )
    analysis_indices = [
        cue_11.channel_names.index(channel) for channel in cue_11.analysis_channels
    ]
    analysis_mean = cue_11.spectrum.amplitude_uv[analysis_indices].mean(axis=0)
    assert summary.loc[11, "sssep_fft_nearest_amplitude_uv"] == pytest.approx(
        analysis_mean[nearest]
    )


def test_actual_bdf_processing_preserves_full_electrode_spectra(
    synthetic_bdf, tmp_path, monkeypatch
):
    path, known = synthetic_bdf
    monkeypatch.setattr(pipeline, "SAVE_PLOTS", False)
    result = pipeline.process_one_bdf(
        path,
        tmp_path / "direct_output",
        analysis_protocol=TEST_PROTOCOL,
    )
    summary = _check_processing_summary(result, known)
    _check_participant_spectra(result, known, summary)
    assert not list(Path(result["output_folder"]).rglob("*.png"))


def test_real_batch_workers_write_consolidated_group_outputs_and_keep_reruns_separate(
    synthetic_bdf, tmp_path, monkeypatch
):
    path, known = synthetic_bdf
    shutil.copyfile(path, path.with_name("Synthetic_B.bdf"))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    output_root = tmp_path / "batch_output"

    first = batch.run_batch(
        path.parent,
        output_root,
        analysis_protocol=TEST_PROTOCOL,
    )

    assert first["status"] == "success", first
    assert first["succeeded"] == 2 and first["failed"] == 0
    assert first["participant_plot_count"] == 2 * len(known["active_counts"])
    assert first["participant_plot_failures"] == 0
    first_run = Path(first["output_folder"])
    assert first_run.parent == output_root
    summaries = [_check_processing_summary(result, known) for result in first["results"]]
    pd.testing.assert_frame_equal(
        summaries[0].drop(columns="file_name"),
        summaries[1].drop(columns="file_name"),
    )
    for result in first["results"]:
        assert "_participant_spectra" not in result
        plots = sorted(Path(result["output_folder"]).glob("plots/*_FFT_Amplitude.png"))
        assert len(plots) == len(known["active_counts"])
        for plot in plots:
            with Image.open(plot) as image:
                assert image.format == "PNG" and image.width >= 1000 and image.height >= 500
                image.verify()

    participant_csv = Path(first["participant_fft_csv"])
    group_csv = Path(first["group_fft_csv"])
    group_plots_folder = Path(first["group_plots_folder"])
    assert "_participant_spectra" not in pd.read_csv(first["summary_csv"]).columns
    assert participant_csv == first_run / "participant_fft_amplitudes.csv"
    assert group_csv == first_run / "group_fft_amplitudes.csv"
    assert group_plots_folder == first_run / "group_plots"
    assert first["group_output_status"] == "success"
    assert first["group_plot_count"] == len(known["active_counts"])
    assert first["group_plot_skipped_trigger_codes"] == []
    assert sorted(first["group_plot_files"]) == sorted(
        str(group_plots_folder / (
            f"{config.TRIGGER_LABELS[code].replace(' ', '_')}_{config.PLOT_CHANNEL}_FFT_Amplitude.png"
        ))
        for code in config.ACTIVE_EVENT_CODES
    )

    participant_frame = pd.read_csv(participant_csv, float_precision="round_trip")
    assert participant_frame.processing_method.unique().tolist() == [
        config.PROCESSING_METHOD
    ]
    assert len(participant_frame) == 2 * (1 + len(known["active_counts"])) * 1281
    assert participant_frame.groupby(
        ["participant_id", "event_type", "trigger_code"]
    ).ngroups == 2 * (1 + len(known["active_counts"]))
    assert set(participant_frame.participant_id) == {"Synthetic_A", "Synthetic_B"}
    assert set(participant_frame[participant_frame.event_type == "cue"].trigger_code) == set(
        config.ACTIVE_EVENT_CODES
    )
    assert all(
        f"{channel}_amplitude_uv" in participant_frame
        for channel in known["scalp_channels"]
    )
    participant_11 = participant_frame[
        (participant_frame.participant_id == "Synthetic_A")
        & (participant_frame.event_type == "cue")
        & (participant_frame.trigger_code == 11)
    ].reset_index(drop=True)
    assert len(participant_11) == 1281
    np.testing.assert_allclose(
        participant_11.frequency_hz,
        np.fft.rfftfreq(2560, 1 / 256),
    )
    roi_columns = [f"{channel}_amplitude_uv" for channel in config.ANALYSIS_CHANNELS]
    np.testing.assert_allclose(
        participant_11.analysis_mean_amplitude_uv,
        participant_11[roi_columns].mean(axis=1),
    )
    nearest = int(np.argmin(abs(participant_11.frequency_hz - 10)))
    assert participant_11.loc[
        nearest, f"{known['probe_channel']}_amplitude_uv"
    ] == pytest.approx(known["target_amplitude_uv"], rel=0.05)

    group_frame = pd.read_csv(group_csv, float_precision="round_trip")
    assert group_frame.processing_method.unique().tolist() == [
        config.PROCESSING_METHOD
    ]
    assert len(group_frame) == (1 + len(known["active_counts"])) * 1281
    assert group_frame.groupby(["event_type", "trigger_code"]).ngroups == (
        1 + len(known["active_counts"])
    )
    group_11 = group_frame[
        (group_frame.event_type == "cue") & (group_frame.trigger_code == 11)
    ].reset_index(drop=True)
    assert group_11.participant_count.unique().tolist() == [2]
    assert group_11[f"{known['probe_channel']}_n_participants"].unique().tolist() == [2]
    np.testing.assert_allclose(
        group_11[f"{known['probe_channel']}_mean_amplitude_uv"],
        participant_11[f"{known['probe_channel']}_amplitude_uv"],
    )

    saved_dataset = load_saved_fft_dataset(first_run)
    saved_roi = average_saved_roi(
        saved_dataset,
        event_type="cue",
        trigger_code=11,
        channels=(known["probe_channel"],),
    )
    np.testing.assert_allclose(
        saved_roi.amplitude_uv,
        group_11[f"{known['probe_channel']}_mean_amplitude_uv"],
    )
    saved_scalp = saved_scalp_values(
        saved_dataset,
        event_type="cue",
        trigger_code=11,
        frequency_hz=10.0,
    )
    assert saved_scalp.actual_frequency_hz == 10.0
    assert saved_scalp.participant_counts == (2,) * len(saved_scalp.channel_names)

    group_plots = sorted(group_plots_folder.glob("*_FFT_Amplitude.png"))
    assert len(group_plots) == len(known["active_counts"])
    for plot in group_plots:
        with Image.open(plot) as image:
            assert image.format == "PNG" and image.width >= 1000 and image.height >= 500
            image.verify()

    first_summary = Path(first["summary_csv"]).read_bytes()
    first_participant_csv = participant_csv.read_bytes()
    first_group_csv = group_csv.read_bytes()
    second_input = tmp_path / "second_input"
    second_input.mkdir()
    shutil.copyfile(path, second_input / path.name)

    second = batch.run_batch(
        second_input,
        output_root,
        analysis_protocol=TEST_PROTOCOL,
    )

    assert second["status"] == "success", second
    assert Path(second["output_folder"]) != first_run
    assert Path(second["output_folder"]).parent == output_root
    assert Path(first["summary_csv"]).read_bytes() == first_summary
    assert participant_csv.read_bytes() == first_participant_csv
    assert group_csv.read_bytes() == first_group_csv
    assert len(list(output_root.glob("????-??-?? @ ??h??*"))) == 2
    _check_processing_summary(second["results"][0], known)
    assert Path(second["participant_fft_csv"]).exists()
    assert Path(second["group_fft_csv"]).exists()
