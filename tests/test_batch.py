"""Tests for batch discovery, preflight checks, progress, and summaries.

These tests use empty `.bdf` placeholder files and monkeypatched workers. They
verify batch orchestration behavior without loading real EEG data.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sssep_batch import batch
from sssep_batch.models import (
    AnalysisProtocol,
    AnalysisTrigger,
    ParticipantSpectrum,
    Spectrum,
)


def test_discover_bdf_files_rejects_missing_input_folder(tmp_path):
    """A missing input folder should produce a clear validation error."""
    missing_folder = tmp_path / "missing"

    with pytest.raises(batch.BatchValidationError, match="Input folder does not exist"):
        batch.discover_bdf_files(missing_folder)


def test_discover_bdf_files_rejects_empty_input_folder(tmp_path):
    """An input folder with no `.bdf` files should stop before processing."""
    with pytest.raises(batch.BatchValidationError, match="No \\.bdf files were found"):
        batch.discover_bdf_files(tmp_path)


def test_discover_bdf_files_returns_sorted_bdf_paths(tmp_path):
    """Only `.bdf` files should be returned, sorted by filename."""
    second = tmp_path / "b_file.bdf"
    first = tmp_path / "a_file.bdf"
    tmp_path.joinpath("notes.txt").write_text("ignore me", encoding="utf-8")
    tmp_path.joinpath("not_a_recording.bdf").mkdir()
    second.write_text("", encoding="utf-8")
    first.write_text("", encoding="utf-8")

    assert batch.discover_bdf_files(tmp_path) == [first, second]


def test_run_preflight_checks_creates_output_folder_and_counts_bdfs(tmp_path):
    """Preflight should create a writable output folder and count input files."""
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    input_folder.joinpath("sample.bdf").write_text("", encoding="utf-8")

    result = batch.run_preflight_checks(input_folder, output_folder)

    assert result["status"] == "ready"
    assert result["bdf_file_count"] == 1
    assert result["packages"] == "ok"
    assert result["config"] == "ok"
    assert output_folder.is_dir()


def test_output_probe_preserves_existing_files(tmp_path):
    """Checking permissions must not overwrite a file in the selected root."""
    existing_file = tmp_path / ".sssep_write_test.tmp"
    existing_file.write_text("keep these contents", encoding="utf-8")

    batch.ensure_output_folder_ready(tmp_path)

    assert existing_file.read_text(encoding="utf-8") == "keep these contents"
    assert list(tmp_path.iterdir()) == [existing_file]


def test_create_run_output_folder_is_unique_under_concurrent_calls(tmp_path):
    """Simultaneous launches must never share a run folder."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        folders = list(executor.map(batch.create_run_output_folder, [tmp_path] * 8))

    assert len(set(folders)) == 8
    assert all(folder.is_dir() and folder.parent == tmp_path for folder in folders)


def test_create_run_output_folder_uses_readable_date_and_24_hour_time(
    monkeypatch,
    tmp_path,
):
    """Run folders should be readable while remaining safe on Windows."""

    class FixedDatetime:
        @staticmethod
        def now():
            return datetime(2026, 9, 1, 10, 23)

    monkeypatch.setattr(batch, "datetime", FixedDatetime)

    first = batch.create_run_output_folder(tmp_path)
    second = batch.create_run_output_folder(tmp_path)

    assert first.name == "2026-09-01 @ 10h23"
    assert second.name == "2026-09-01 @ 10h23 (2)"


def test_runtime_preflight_does_not_require_development_packages(monkeypatch):
    """Analysis should not fail because pytest or unused YAML support is absent."""
    monkeypatch.setattr(
        batch.importlib.util, "find_spec",
        lambda name: None if name in {"pytest", "yaml"} else object(),
    )

    batch.validate_required_packages()


def test_validate_config_settings_reports_missing_trigger_metadata(monkeypatch):
    """Trigger codes without labels/frequencies should be beginner-visible errors."""
    monkeypatch.setattr(batch, "ACTIVE_EVENT_CODES", [999])
    monkeypatch.setattr(batch, "TRIGGER_LABELS", {})
    monkeypatch.setattr(batch, "TRIGGER_HZ_MAP", {})

    with pytest.raises(batch.BatchValidationError, match="TRIGGER_LABELS"):
        batch.validate_config_settings()


@pytest.mark.parametrize("plot_channel", [None, "", "   ", 4])
def test_plot_channel_selection_requires_a_channel_label(plot_channel):
    with pytest.raises(batch.BatchValidationError, match="FFT plot electrode"):
        batch.validate_plot_channel_selection(plot_channel)


def test_plot_channel_selection_trims_launcher_input():
    assert batch.validate_plot_channel_selection("  C4  ") == "C4"


@pytest.mark.parametrize(
    "lowcut,highcut,downsample",
    [(0.0, 50.0, 0), (None, 50.0, None), (0.1, None, 256),
     (None, None, 0), (0.1, 50.0, 256)],
)
def test_preflight_accepts_disabled_fpvs_stages_and_full_fft_plot_range(
    monkeypatch, lowcut, highcut, downsample
):
    monkeypatch.setattr(batch, "LOWCUT", lowcut)
    monkeypatch.setattr(batch, "HIGHCUT", highcut)
    monkeypatch.setattr(batch, "DOWNSAMPLE_RATE", downsample)
    monkeypatch.setattr(batch, "FMIN", 0.0)
    monkeypatch.setattr(batch, "FMAX", 128.0)
    batch.validate_config_settings()


@pytest.mark.parametrize(
    "setting,value",
    [("LOWCUT", -0.1), ("LOWCUT", 50.0), ("LOWCUT", 51.0),
     ("LOWCUT", float("nan")), ("HIGHCUT", 0), ("HIGHCUT", "text"),
     ("DOWNSAMPLE_RATE", -1), ("DOWNSAMPLE_RATE", float("inf")),
     ("FMIN", -1), ("FMIN", 50.0), ("FMAX", 2.0),
     ("FMAX", float("nan")), ("FMIN", None)],
)
def test_preflight_rejects_invalid_filter_and_plot_settings(monkeypatch, setting, value):
    monkeypatch.setattr(batch, setting, value)
    with pytest.raises(batch.BatchValidationError, match=setting):
        batch.validate_config_settings()


def test_run_batch_reports_progress_and_writes_summary(monkeypatch, tmp_path):
    """A mixed success/failure batch should report progress and write a summary."""
    monkeypatch.setattr(batch, "SAVE_PLOTS", False)
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    first = input_folder / "a_file.bdf"
    second = input_folder / "b_file.bdf"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")

    futures = []
    submitted_plot_channels = []
    submitted_protocols = []

    class FakeFuture:
        """Minimal future object that returns a prepared worker result."""

        def __init__(self, result):
            """Store the worker result that `result()` should return."""
            self._result = result

        def result(self):
            """Return the prepared worker result."""
            return self._result

    class FakeExecutor:
        """Small stand-in for `ProcessPoolExecutor` used by this unit test."""

        def __init__(self, max_workers):
            """Remember the selected worker count for parity with the real executor."""
            self.max_workers = max_workers

        def __enter__(self):
            """Support use in a `with` block."""
            return self

        def __exit__(self, exc_type, exc, tb):
            """Do not suppress exceptions from the code under test."""
            return False

        def submit(
            self,
            func,
            bdf_file: Path,
            output_root: Path,
            plot_channel: str,
            analysis_protocol,
        ):
            """Return deterministic success/failure rows for synthetic files."""
            submitted_plot_channels.append(plot_channel)
            submitted_protocols.append(analysis_protocol)
            if bdf_file.name == "a_file.bdf":
                spectrum = Spectrum(
                    freqs=np.array([0.0, 10.0, 20.0]),
                    amplitude_uv=np.array([[1.0, 4.0, 2.0]]),
                    method="FPVS test amplitude",
                )
                result = {
                    "file_name": bdf_file.name,
                    "status": "success",
                    "output_folder": str(output_root / bdf_file.stem),
                    "summary_csv": str(output_root / bdf_file.stem / "summary.csv"),
                    "_participant_spectra": (
                        ParticipantSpectrum(
                            participant_id=bdf_file.stem,
                            file_name=bdf_file.name,
                            event_type="baseline",
                            trigger_code=analysis_protocol.baseline_event_code,
                            trigger_label=analysis_protocol.baseline_label,
                            target_hz=None,
                            usable_epochs=2,
                            channel_names=("C4",),
                            analysis_channels=("C4",),
                            sampling_rate_hz=40.0,
                            analysis_window_sec=0.1,
                            spectrum=spectrum,
                        ),
                        ParticipantSpectrum(
                            participant_id=bdf_file.stem,
                            file_name=bdf_file.name,
                            event_type="cue",
                            trigger_code=analysis_protocol.active_triggers[0].code,
                            trigger_label=analysis_protocol.active_triggers[0].label,
                            target_hz=analysis_protocol.active_triggers[0].target_hz,
                            usable_epochs=2,
                            channel_names=("C4",),
                            analysis_channels=("C4",),
                            sampling_rate_hz=40.0,
                            analysis_window_sec=0.1,
                            spectrum=spectrum,
                        ),
                    ),
                }
            else:
                result = {
                    "file_name": bdf_file.name,
                    "status": "failed",
                    "failed_stage": "loading_bdf",
                    "output_folder": str(output_root / bdf_file.stem),
                    "error": "synthetic failure",
                    "error_file": str(output_root / bdf_file.stem / "ERROR.txt"),
                }
            future = FakeFuture(result)
            futures.append(future)
            return future

    monkeypatch.setattr(batch, "ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr(batch, "as_completed", lambda future_to_file: list(future_to_file))
    monkeypatch.setattr(batch, "get_process_one_bdf", lambda: lambda *args: None)

    progress_events = []
    result = batch.run_batch(
        input_folder,
        output_folder,
        progress_callback=progress_events.append,
        plot_channel=" C4 ",
    )

    assert result["status"] == "completed_with_failures"
    assert result["total_files"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert submitted_plot_channels == ["C4", "C4"]
    assert all(
        protocol.active_event_codes == (11, 12, 21, 22)
        for protocol in submitted_protocols
    )
    run_folder = Path(result["output_folder"])
    summary_path = Path(result["summary_csv"])
    assert run_folder.parent == output_folder
    assert summary_path == run_folder / "batch_processing_summary.csv"
    assert summary_path.exists()
    assert all(Path(row["output_folder"]).parent == run_folder for row in result["results"])
    assert all("_participant_spectra" not in row for row in result["results"])
    assert "_participant_spectra" not in pd.read_csv(summary_path).columns
    assert result["group_output_status"] == "success"
    assert Path(result["participant_fft_csv"]).exists()
    assert Path(result["group_fft_csv"]).exists()

    log_path = run_folder / "sssep_batch_processing.log"
    log_text = log_path.read_text(encoding="utf-8")
    assert "QUEUED 1/2: a_file.bdf" in log_text
    assert "QUEUED 2/2: b_file.bdf" in log_text
    assert "COMPLETED 1/2: a_file.bdf" in log_text
    assert "FAILED 2/2: b_file.bdf" in log_text
    assert any(event["phase"] == "complete" for event in progress_events)

    summary_bytes = summary_path.read_bytes()
    old_error = run_folder / "ERROR.txt"
    old_error.write_text("previous run only", encoding="utf-8")
    next_result = batch.run_batch(input_folder, output_folder)
    next_folder = Path(next_result["output_folder"])

    assert next_folder != run_folder
    assert next_folder.parent == output_folder
    assert Path(next_result["summary_csv"]).parent == next_folder
    assert summary_path.read_bytes() == summary_bytes
    assert log_path.read_text(encoding="utf-8") == log_text
    assert old_error.read_text(encoding="utf-8") == "previous run only"
    assert not (next_folder / "ERROR.txt").exists()
    assert submitted_plot_channels[-2:] == [batch.PLOT_CHANNEL, batch.PLOT_CHANNEL]


def test_worker_crash_writes_detailed_per_file_error(tmp_path):
    result = batch.make_worker_crash_result(
        "participant_01.bdf",
        tmp_path,
        RuntimeError("synthetic worker failure"),
    )

    output_folder = tmp_path / "participant_01"
    error_path = output_folder / "ERROR.txt"
    assert result["status"] == "failed"
    assert result["failed_stage"] == "worker_crash"
    assert result["processing_method"] == batch.PROCESSING_METHOD
    assert result["output_folder"] == str(output_folder)
    assert result["error_file"] == str(error_path)
    assert error_path.exists()
    error_text = error_path.read_text(encoding="utf-8")
    assert "participant_01.bdf" in error_text
    assert "worker_crash" in error_text
    assert "synthetic worker failure" in error_text
    assert "unexpected worker-process failure" in error_text


def _participant_record(
    participant_id: str,
    *,
    event_type: str,
    trigger_code: int,
    trigger_label: str,
    amplitude: float,
) -> ParticipantSpectrum:
    return ParticipantSpectrum(
        participant_id=participant_id,
        file_name=f"{participant_id}.bdf",
        event_type=event_type,
        trigger_code=trigger_code,
        trigger_label=trigger_label,
        target_hz=10.0 if event_type == "cue" else None,
        usable_epochs=2,
        channel_names=("Cz",),
        analysis_channels=("Cz",),
        sampling_rate_hz=40.0,
        analysis_window_sec=0.1,
        spectrum=Spectrum(
            freqs=np.array([0.0, 10.0, 20.0]),
            amplitude_uv=np.full((1, 3), amplitude),
            method="FPVS test amplitude",
        ),
    )


def _run_fake_spectrum_batch(
    monkeypatch,
    tmp_path,
    payloads: dict[str, tuple[ParticipantSpectrum, ...]],
    protocol: AnalysisProtocol,
    fake_plot,
) -> dict[str, object]:
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    for file_name in payloads:
        (input_folder / file_name).write_bytes(b"")

    class FakeFuture:
        def __init__(self, result):
            self._result = result

        def result(self):
            return self._result

    class FakeExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, func, bdf_file, output_root, plot_channel, analysis_protocol):
            return FakeFuture(
                {
                    "file_name": bdf_file.name,
                    "status": "success",
                    "output_folder": str(output_root / bdf_file.stem),
                    "summary_csv": str(output_root / bdf_file.stem / "summary.csv"),
                    "_participant_spectra": payloads[bdf_file.name],
                }
            )

    import sssep_batch.analysis.plotting as plotting

    monkeypatch.setattr(batch, "ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr(batch, "as_completed", lambda future_to_file: list(future_to_file))
    monkeypatch.setattr(batch, "get_process_one_bdf", lambda: lambda *args: None)
    monkeypatch.setattr(batch, "SAVE_CSV_SUMMARIES", True)
    monkeypatch.setattr(batch, "SAVE_PLOTS", True)
    monkeypatch.setattr(plotting, "plot_spectrum", fake_plot)
    return batch.run_batch(
        input_folder,
        output_folder,
        plot_channel="Cz",
        analysis_protocol=protocol,
    )


def test_group_plot_failure_does_not_stop_later_plots_or_hide_csv_success(
    monkeypatch, tmp_path
):
    protocol = AnalysisProtocol(
        active_triggers=(
            AnalysisTrigger(11, "BothHands Left Hand", 10.0),
            AnalysisTrigger(12, "BothHands Right Hand", 10.0),
        ),
        event_duration_sec=7.5,
        expected_repetitions_per_trigger=2,
        baseline_event_code=100,
    )
    payloads = {
        "P01.bdf": (
            _participant_record(
                "P01", event_type="baseline", trigger_code=100,
                trigger_label="Gap/Break", amplitude=1.0,
            ),
            _participant_record(
                "P01", event_type="cue", trigger_code=11,
                trigger_label="BothHands Left Hand", amplitude=2.0,
            ),
            _participant_record(
                "P01", event_type="cue", trigger_code=12,
                trigger_label="BothHands Right Hand", amplitude=3.0,
            ),
        )
    }
    calls: list[int] = []

    def fake_plot(**kwargs):
        trigger_code = 11 if "Cue 11" in kwargs["title"] else 12
        calls.append(trigger_code)
        if trigger_code == 11:
            raise RuntimeError("synthetic plot failure")
        Path(kwargs["outpath"]).write_bytes(b"png")

    result = _run_fake_spectrum_batch(
        monkeypatch, tmp_path, payloads, protocol, fake_plot
    )

    assert calls == [11, 12]
    assert result["status"] == "completed_with_failures"
    assert result["group_output_status"] == "success_with_warnings"
    assert result["participant_fft_csv_status"] == "success"
    assert result["group_fft_csv_status"] == "success"
    assert result["group_plot_status"] == "completed_with_failures"
    assert result["group_plot_count"] == 1
    assert result["group_plot_skipped_trigger_codes"] == [11]
    assert "synthetic plot failure" in result["group_plot_errors"][0]
    assert Path(result["group_plot_error_file"]).exists()
    assert Path(result["participant_fft_csv"]).exists()
    assert Path(result["group_fft_csv"]).exists()
    assert Path(result["group_plots_folder"]).is_dir()
    assert Path(result["group_plot_files"][0]).name == (
        "group_cue_012_fft_amplitude.png"
    )


def test_group_plot_baseline_uses_only_complete_matched_cue_participants(
    monkeypatch, tmp_path
):
    protocol = AnalysisProtocol(
        active_triggers=(
            AnalysisTrigger(11, "BothHands Left Hand", 10.0),
            AnalysisTrigger(12, "BothHands Right Hand", 10.0),
        ),
        event_duration_sec=7.5,
        expected_repetitions_per_trigger=2,
        baseline_event_code=100,
    )
    payloads = {
        "P01.bdf": (
            _participant_record(
                "P01", event_type="baseline", trigger_code=100,
                trigger_label="Gap/Break", amplitude=10.0,
            ),
            _participant_record(
                "P01", event_type="cue", trigger_code=11,
                trigger_label="BothHands Left Hand", amplitude=2.0,
            ),
            _participant_record(
                "P01", event_type="cue", trigger_code=12,
                trigger_label="BothHands Right Hand", amplitude=3.0,
            ),
        ),
        "P02.bdf": (
            _participant_record(
                "P02", event_type="cue", trigger_code=11,
                trigger_label="BothHands Left Hand", amplitude=4.0,
            ),
        ),
        "P03.bdf": (
            _participant_record(
                "P03", event_type="baseline", trigger_code=100,
                trigger_label="Gap/Break", amplitude=1000.0,
            ),
        ),
    }
    captured: dict[int, dict[str, object]] = {}

    def fake_plot(**kwargs):
        trigger_code = 11 if "Cue 11" in kwargs["title"] else 12
        captured[trigger_code] = kwargs
        Path(kwargs["outpath"]).write_bytes(b"png")

    result = _run_fake_spectrum_batch(
        monkeypatch, tmp_path, payloads, protocol, fake_plot
    )

    assert captured[11]["baseline"] is None
    matched_baseline = captured[12]["baseline"]
    assert matched_baseline is not None
    np.testing.assert_array_equal(matched_baseline.amplitude_uv, [[10.0, 10.0, 10.0]])
    assert captured[12]["baseline_label"] == "Gap/Break group mean (matched N=1)"
    assert result["status"] == "success"
    assert result["group_output_status"] == "success_with_warnings"
    assert result["group_plot_status"] == "success_with_warnings"
    assert result["group_plot_count"] == 2
    assert result["group_plot_skipped_trigger_codes"] == []
    assert any("P02" in warning for warning in result["group_plot_warnings"])
