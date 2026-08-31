"""Integration checks for the actual preprocessing/FFT orchestration."""

from pathlib import Path

import mne
import numpy as np
import pandas as pd
import pytest

import sssep_batch.pipeline as pipeline
from sssep_batch.models import AnalysisProtocol, AnalysisTrigger


def task_protocol() -> AnalysisProtocol:
    return AnalysisProtocol(
        active_triggers=tuple(
            AnalysisTrigger(code, f"Condition Site {code}", 10.0)
            for code in (1, 2, 3, 4)
        ),
        event_duration_sec=7.5,
        expected_repetitions_per_trigger=1,
        baseline_event_code=100,
    )


def make_recording(*, active=True):
    """Small continuous recording; the first trial must survive old FIR edges."""
    names = mne.channels.make_standard_montage("biosemi64").ch_names + ["EXG1", "EXG2", "Status"]
    sfreq = 256
    rng = np.random.default_rng(77)
    data = rng.normal(0, 1e-6, (len(names), sfreq * 80))
    data[-1] = 0
    if active:
        for code, seconds in enumerate((1, 12, 24, 36), start=1):
            data[-1, seconds * sfreq:seconds * sfreq + 4] = code
    data[-1, 55 * sfreq:55 * sfreq + 4] = 100
    return mne.io.RawArray(
        data, mne.create_info(names, sfreq, ["eeg"] * 66 + ["stim"]), verbose=False
    )


def test_pipeline_uses_fpvs_order_and_limits_plots_only(monkeypatch, tmp_path):
    raw = make_recording()
    monkeypatch.setattr(pipeline, "load_bdf", lambda *args: raw)
    monkeypatch.setattr(pipeline, "MAX_INDIVIDUAL_PLOTS", 2)
    calls = []
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
    assert summary.analysis_window_sec.tolist() == [7.5, 7.5, 7.5, 7.5]
    assert summary.edge_excluded_epochs.tolist() == [0, 0, 0, 0]
    assert set(summary.processing_method) == {"fpvs_amplitude_v1"}
    assert "sssep_fft_nearest_amplitude_uv" in summary
    assert not any("power" in name or "welch" in name for name in summary.columns)
    csvs = list(Path(result["output_folder"]).rglob("*_sssep_fft_amplitude.csv"))
    assert len(csvs) == 4
    assert len(plots) == 2
    assert plots[0]["plot_channel"] == "C4"
    exported = pd.read_csv(csvs[0])
    assert exported.frequency_hz.iloc[0] == 0
    assert exported.frequency_hz.iloc[-1] == 128
    assert len(exported) == 961  # 7.5 seconds * 256 Hz -> N/2+1
    assert "active_Cz_amplitude_uv" in exported
    assert "active_mean_amplitude_uv" in exported
    assert plots[0]["active"].amplitude_uv.ndim == 2
    assert "MAX_INDIVIDUAL_PLOTS=2" in (Path(result["output_folder"]) / "synthetic_processing_report.txt").read_text()


def test_missing_plot_electrode_skips_pngs_without_suppressing_fft_csvs(
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
    assert len(list(output_folder.rglob("*_sssep_fft_amplitude.csv"))) == 4
    assert plots == []
    report = (output_folder / "missing_plot_channel_processing_report.txt").read_text()
    assert "Plot electrode 'C4' is unavailable" in report


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
