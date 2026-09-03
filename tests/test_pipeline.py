"""Integration checks for the actual preprocessing/FFT orchestration."""

from dataclasses import replace
from pathlib import Path

import mne
import numpy as np
import pandas as pd
import pytest

import sssep_batch.pipeline as pipeline
from sssep_batch.experiment.models import CueTriggerCodes, analysis_protocol_for_task
from sssep_batch.models import AnalysisProtocol, AnalysisTrigger


def task_protocol() -> AnalysisProtocol:
    return AnalysisProtocol(
        active_triggers=tuple(
            AnalysisTrigger(code, f"Condition Site {code}", 10.0)
            for code in (1, 2, 3, 4)
        ),
        event_duration_sec=15.0,
        expected_repetitions_per_trigger=1,
        baseline_event_code=100,
    )


def make_recording(*, active=True, active_codes=(1, 2, 3, 4)):
    """Small continuous recording; the first trial must survive old FIR edges."""
    names = mne.channels.make_standard_montage("biosemi64").ch_names + ["EXG1", "EXG2", "Status"]
    sfreq = 256
    rng = np.random.default_rng(77)
    data = rng.normal(0, 1e-6, (len(names), sfreq * 80))
    data[-1] = 0
    if active:
        for code, seconds in zip(active_codes, (1, 12, 24, 36), strict=True):
            data[-1, seconds * sfreq:seconds * sfreq + 4] = code
    data[-1, 55 * sfreq:55 * sfreq + 4] = 100
    return mne.io.RawArray(
        data, mne.create_info(names, sfreq, ["eeg"] * 66 + ["stim"]), verbose=False
    )


def test_pipeline_uses_fpvs_order_and_creates_one_plot_per_cue(monkeypatch, tmp_path):
    raw = make_recording()
    monkeypatch.setattr(pipeline, "load_bdf", lambda *args: raw)
    calls = []
    extracted_sample_counts = []
    fft_input_sample_counts = []
    for name in (
        "apply_basic_fir_filter", "downsample_if_needed",
        "detect_and_interpolate_bad_channels_by_kurtosis",
        "apply_final_average_reference", "find_status_events",
    ):
        original = getattr(pipeline, name)

        def tracked(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(pipeline, name, tracked)
    original_extract_epochs = pipeline.extract_epochs_for_code
    original_compute_fft = pipeline.compute_sssep_fft_from_averaged_epochs

    def tracked_extract_epochs(*args, **kwargs):
        epoch_set = original_extract_epochs(*args, **kwargs)
        extracted_sample_counts.append(epoch_set.epochs.shape[-1])
        return epoch_set

    def tracked_compute_fft(epochs, *args, **kwargs):
        fft_input_sample_counts.append(epochs.shape[-1])
        return original_compute_fft(epochs, *args, **kwargs)

    monkeypatch.setattr(pipeline, "extract_epochs_for_code", tracked_extract_epochs)
    monkeypatch.setattr(
        pipeline,
        "compute_sssep_fft_from_averaged_epochs",
        tracked_compute_fft,
    )
    plots = []
    monkeypatch.setattr(pipeline, "plot_spectrum", lambda **kwargs: plots.append(kwargs))
    result = pipeline.process_one_bdf(
        "synthetic.bdf",
        tmp_path,
        plot_channel="C4",
        analysis_protocol=task_protocol(),
    )

    assert result["status"] == "success", result
    assert calls == [
        "apply_basic_fir_filter", "downsample_if_needed",
        "detect_and_interpolate_bad_channels_by_kurtosis",
        "apply_final_average_reference", "find_status_events",
    ]
    summary = pd.read_csv(result["summary_csv"])
    assert summary.usable_epochs.tolist() == [1, 1, 1, 1]
    assert summary.trigger_code.tolist() == [1, 2, 3, 4]
    assert summary.expected_repetitions.tolist() == [1, 1, 1, 1]
    assert summary.epoch_window_sec.tolist() == [15.0, 15.0, 15.0, 15.0]
    assert summary.fft_crop_start_sec.tolist() == [2.5, 2.5, 2.5, 2.5]
    assert summary.fft_crop_end_sec.tolist() == [2.5, 2.5, 2.5, 2.5]
    assert summary.analysis_window_sec.tolist() == [10.0, 10.0, 10.0, 10.0]
    assert summary.edge_excluded_epochs.tolist() == [0, 0, 0, 0]
    assert set(summary.processing_method) == {"fpvs_amplitude_epoch_crop_v2"}
    assert "sssep_fft_nearest_amplitude_uv" in summary
    assert not any("power" in name or "welch" in name for name in summary.columns)
    assert len(plots) == 4
    assert result["participant_plot_count"] == 4
    assert result["participant_plot_failures"] == 0
    assert plots[0]["plot_channel"] == "C4"
    assert [plot["outpath"].name for plot in plots] == [
        f"Condition_Site_{code}_C4_FFT_Amplitude.png" for code in (1, 2, 3, 4)
    ]
    records = result["_participant_spectra"]
    assert len(records) == 5  # four cues plus one baseline stored once
    cue_records = [record for record in records if record.event_type == "cue"]
    assert [record.trigger_code for record in cue_records] == [1, 2, 3, 4]
    assert cue_records[0].spectrum.freqs[0] == 0
    assert cue_records[0].spectrum.freqs[-1] == 128
    assert extracted_sample_counts == [3840] * 5
    assert fft_input_sample_counts == [2560] * 5
    assert all(record.epoch_window_sec == 15.0 for record in records)
    assert all(record.fft_crop_start_sec == 2.5 for record in records)
    assert all(record.fft_crop_end_sec == 2.5 for record in records)
    assert all(record.analysis_window_sec == 10.0 for record in records)
    assert len(cue_records[0].spectrum.freqs) == 1281
    assert cue_records[0].spectrum.freqs[1] == pytest.approx(0.1)
    assert "Cz" in cue_records[0].channel_names
    assert plots[0]["active"].amplitude_uv.ndim == 2
    assert "one per usable trigger code" in (
        Path(result["output_folder"]) / "synthetic_processing_report.txt"
    ).read_text()


def test_task_protocol_audits_epoch_end_markers_without_using_a_baseline_fft(
    monkeypatch, tmp_path,
):
    protocol = analysis_protocol_for_task(
        epoch_duration_sec=15.0,
        epochs_per_condition=2,
        trigger_codes=CueTriggerCodes(11, 12, 21, 22),
        target_hz=10.0,
    )
    assert protocol.analyze_baseline is False

    monkeypatch.setattr(
        pipeline,
        "load_bdf",
        lambda *_args, **_kwargs: make_recording(active_codes=(11, 12, 21, 22)),
    )
    monkeypatch.setattr(pipeline, "SAVE_PLOTS", False)
    fft_calls = []
    original_compute_fft = pipeline.compute_sssep_fft_from_averaged_epochs

    def tracked_compute_fft(epochs, *args, **kwargs):
        fft_calls.append(epochs.copy())
        return original_compute_fft(epochs, *args, **kwargs)

    monkeypatch.setattr(
        pipeline,
        "compute_sssep_fft_from_averaged_epochs",
        tracked_compute_fft,
    )

    without_baseline = pipeline.process_one_bdf(
        "task_recording.bdf",
        tmp_path / "without_baseline",
        analysis_protocol=protocol,
    )
    assert without_baseline["status"] == "success", without_baseline
    assert len(fft_calls) == 4
    assert {record.event_type for record in without_baseline["_participant_spectra"]} == {
        "cue"
    }
    detected = pd.read_csv(
        Path(without_baseline["output_folder"]) / "detected_status_events.csv"
    )
    assert 100 in set(detected["trigger_code"])
    summary = pd.read_csv(without_baseline["summary_csv"])
    assert (summary["baseline_usable_epochs"] == 0).all()
    assert summary["sssep_fft_active_vs_baseline_amplitude_ratio"].isna().all()
    report = (
        Path(without_baseline["output_folder"])
        / "task_recording_processing_report.txt"
    ).read_text(encoding="utf-8")
    assert "epoch-end/break delimiter" in report
    assert "baseline FFT calculation is disabled" in report

    with_baseline = pipeline.process_one_bdf(
        "task_recording.bdf",
        tmp_path / "with_baseline",
        analysis_protocol=replace(protocol, analyze_baseline=True),
    )
    assert with_baseline["status"] == "success", with_baseline
    assert len(fft_calls) == 9
    enabled_records = with_baseline["_participant_spectra"]
    assert [record.event_type for record in enabled_records].count("baseline") == 1
    disabled_cues = {
        record.trigger_code: record.spectrum.amplitude_uv
        for record in without_baseline["_participant_spectra"]
    }
    enabled_cues = {
        record.trigger_code: record.spectrum.amplitude_uv
        for record in enabled_records
        if record.event_type == "cue"
    }
    assert disabled_cues.keys() == enabled_cues.keys()
    for code in disabled_cues:
        np.testing.assert_array_equal(disabled_cues[code], enabled_cues[code])


def test_missing_plot_electrode_skips_pngs_without_suppressing_fft_spectra(
    monkeypatch, tmp_path
):
    raw = make_recording()
    monkeypatch.setattr(pipeline, "load_bdf", lambda *args: raw)
    original_get_fft_channels = pipeline.get_fft_channels
    monkeypatch.setattr(
        pipeline,
        "get_fft_channels",
        lambda recording: [
            channel
            for channel in original_get_fft_channels(recording)
            if channel != "C4"
        ],
    )
    plots = []
    monkeypatch.setattr(pipeline, "plot_spectrum", lambda **kwargs: plots.append(kwargs))

    result = pipeline.process_one_bdf(
        "missing_plot_channel.bdf",
        tmp_path,
        plot_channel="C4",
        analysis_protocol=task_protocol(),
    )

    assert result["status"] == "success", result
    output_folder = Path(result["output_folder"])
    assert len(result["_participant_spectra"]) == 5
    assert plots == []
    assert result["participant_plot_count"] == 0
    assert result["participant_plot_failures"] == 0
    report = (output_folder / "missing_plot_channel_processing_report.txt").read_text()
    assert "Plot electrode 'C4' is unavailable" in report


def test_plot_error_preserves_spectra_and_continues_later_cue_plots(
    monkeypatch, tmp_path
):
    raw = make_recording()
    monkeypatch.setattr(pipeline, "load_bdf", lambda *args: raw)
    attempted_codes = []

    def fail_first_plot(**kwargs):
        code = int(kwargs["title"].split("Trigger code ")[1].split()[0])
        attempted_codes.append(code)
        Path(kwargs["outpath"]).write_bytes(f"trigger {code}".encode())
        if code == 1:
            raise OSError("synthetic PNG write failure")

    monkeypatch.setattr(pipeline, "plot_spectrum", fail_first_plot)

    result = pipeline.process_one_bdf(
        "plot_failure.bdf",
        tmp_path,
        plot_channel="C4",
        analysis_protocol=task_protocol(),
    )

    assert result["status"] == "success", result
    assert attempted_codes == [1, 2, 3, 4]
    assert result["participant_plot_count"] == 3
    assert result["participant_plot_failures"] == 1
    assert sorted(path.name for path in (Path(result["output_folder"]) / "plots").iterdir()) == [
        f"Condition_Site_{code}_C4_FFT_Amplitude.png" for code in (2, 3, 4)
    ]
    records = result["_participant_spectra"]
    assert len(records) == 5
    assert [record.trigger_code for record in records if record.event_type == "cue"] == [
        1, 2, 3, 4,
    ]
    report = (
        Path(result["output_folder"]) / "plot_failure_processing_report.txt"
    ).read_text()
    assert "WARNING: Participant plot skipped for trigger 1" in report
    assert "synthetic PNG write failure" in report
    assert "Created 3 participant amplitude plot(s)" in report
    assert "1 plot(s) failed" in report


def test_duplicate_condition_names_preserve_plots_when_one_render_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "load_bdf", lambda *args: make_recording())
    protocol = AnalysisProtocol(
        active_triggers=tuple(AnalysisTrigger(code, "Same Condition", 10.0) for code in (1, 2, 3, 4)),
        event_duration_sec=15.0,
        expected_repetitions_per_trigger=1,
        baseline_event_code=100,
    )

    def render(**kwargs):
        code = int(kwargs["title"].split("Trigger code ")[1].split()[0])
        path = kwargs["outpath"]
        assert path.read_bytes() == b""
        path.write_bytes(f"trigger {code}".encode())
        if code == 2:
            raise OSError("synthetic partial render")

    monkeypatch.setattr(pipeline, "plot_spectrum", render)
    result = pipeline.process_one_bdf(
        "same_names.bdf", tmp_path, plot_channel="C4", analysis_protocol=protocol,
    )

    assert result["status"] == "success"
    assert result["participant_plot_count"] == 3
    assert result["participant_plot_failures"] == 1
    plot_folder = Path(result["output_folder"]) / "plots"
    assert {path.name: path.read_bytes() for path in plot_folder.iterdir()} == {
        "Same_Condition_C4_FFT_Amplitude.png": b"trigger 1",
        "Same_Condition_C4_FFT_Amplitude (2).png": b"trigger 3",
        "Same_Condition_C4_FFT_Amplitude (3).png": b"trigger 4",
    }
    assert len(result["_participant_spectra"]) == 5


def test_no_active_epochs_is_failed_with_stable_amplitude_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "load_bdf", lambda *args: make_recording(active=False))
    result = pipeline.process_one_bdf("baseline_only.bdf", tmp_path)
    assert result["status"] == "failed"
    assert "No usable active-condition epochs" in result["error"]
    summary = pd.read_csv(tmp_path / "baseline_only" / "baseline_only_sssep_event_summary.csv")
    assert set(summary.status) == {"no_complete_epochs"}
    assert summary.sssep_fft_nearest_amplitude_uv.isna().all()
    assert "baseline_sssep_fft_nearest_amplitude_uv" in summary
    assert Path(result["error_file"]).exists()


def test_direct_rerun_refuses_to_overwrite_previous_results(tmp_path):
    previous = tmp_path / "old"
    previous.mkdir()
    sentinel = previous / "old_sssep_event_summary.csv"
    sentinel.write_text("preserved results")
    with pytest.raises(FileExistsError):
        pipeline.process_one_bdf("old.bdf", tmp_path)
    assert sentinel.read_text() == "preserved results"
