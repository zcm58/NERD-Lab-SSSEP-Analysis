from pathlib import Path

import pytest

from sssep_batch import batch


def test_discover_bdf_files_rejects_missing_input_folder(tmp_path):
    missing_folder = tmp_path / "missing"

    with pytest.raises(batch.BatchValidationError, match="Input folder does not exist"):
        batch.discover_bdf_files(missing_folder)


def test_discover_bdf_files_rejects_empty_input_folder(tmp_path):
    with pytest.raises(batch.BatchValidationError, match="No \\.bdf files were found"):
        batch.discover_bdf_files(tmp_path)


def test_discover_bdf_files_returns_sorted_bdf_paths(tmp_path):
    second = tmp_path / "b_file.bdf"
    first = tmp_path / "a_file.bdf"
    tmp_path.joinpath("notes.txt").write_text("ignore me", encoding="utf-8")
    second.write_text("", encoding="utf-8")
    first.write_text("", encoding="utf-8")

    assert batch.discover_bdf_files(tmp_path) == [first, second]


def test_run_batch_reports_progress_and_writes_summary(monkeypatch, tmp_path):
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    first = input_folder / "a_file.bdf"
    second = input_folder / "b_file.bdf"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")

    futures = []

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

        def submit(self, func, bdf_file: Path, output_root: Path):
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
