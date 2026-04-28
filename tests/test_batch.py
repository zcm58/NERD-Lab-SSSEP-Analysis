"""Tests for batch discovery, preflight checks, progress, and summaries.

These tests use empty `.bdf` placeholder files and monkeypatched workers. They
verify batch orchestration behavior without loading real EEG data.
"""

from pathlib import Path

import pytest

from sssep_batch import batch


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


def test_validate_config_settings_reports_missing_trigger_metadata(monkeypatch):
    """Trigger codes without labels/frequencies should be beginner-visible errors."""
    monkeypatch.setattr(batch, "ACTIVE_EVENT_CODES", [999])
    monkeypatch.setattr(batch, "TRIGGER_LABELS", {})
    monkeypatch.setattr(batch, "TRIGGER_HZ_MAP", {})

    with pytest.raises(batch.BatchValidationError, match="TRIGGER_LABELS"):
        batch.validate_config_settings()


def test_run_batch_reports_progress_and_writes_summary(monkeypatch, tmp_path):
    """A mixed success/failure batch should report progress and write a summary."""
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    first = input_folder / "a_file.bdf"
    second = input_folder / "b_file.bdf"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")

    futures = []

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

        def submit(self, func, bdf_file: Path, output_root: Path):
            """Return deterministic success/failure rows for synthetic files."""
            if bdf_file.name == "a_file.bdf":
                result = {
                    "file_name": bdf_file.name,
                    "status": "success",
                    "output_folder": str(output_root / bdf_file.stem),
                    "summary_csv": str(output_root / bdf_file.stem / "summary.csv"),
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
    )

    assert result["status"] == "completed_with_failures"
    assert result["total_files"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert (output_folder / "batch_processing_summary.csv").exists()

    log_text = (output_folder / "sssep_batch_processing.log").read_text(encoding="utf-8")
    assert "QUEUED 1/2: a_file.bdf" in log_text
    assert "QUEUED 2/2: b_file.bdf" in log_text
    assert "COMPLETED 1/2: a_file.bdf" in log_text
    assert "FAILED 2/2: b_file.bdf" in log_text
    assert any(event["phase"] == "complete" for event in progress_events)
