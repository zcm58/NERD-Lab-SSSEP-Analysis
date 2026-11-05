"""Run-level demographics export, filtering and source preservation."""

import csv

import pytest

from sssep_batch.experiment import demographics


def _write_log(path, **overrides):
    row = {
        "participant_number": "007",
        "participant_age": "22",
        "participant_sex": "Female",
        "participant_handedness": "Right handed",
        "participant_colorblind": "False",
        "run_id": "first-run",
        "started_at_utc": "2026-10-01T16:00:00+00:00",
        "run_aborted": "False",
        "test_mode": "False",
        **overrides,
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=row)
        writer.writeheader()
        writer.writerows([row, row])
    return path


def test_exports_one_row_per_run_and_keeps_repeated_participants(tmp_path):
    first = _write_log(tmp_path / "sssep_task_events_a.csv")
    second = _write_log(
        tmp_path / "sssep_task_events_b.csv",
        run_id="second-run",
        started_at_utc="2026-10-02T16:00:00+00:00",
        run_aborted="True",
    )
    _write_log(tmp_path / "sssep_task_events_test.csv", test_mode="True")
    legacy = tmp_path / "sssep_task_events_legacy.csv"
    legacy.write_text("run_id,test_mode\nold,False\n", encoding="utf-8")
    _write_log(tmp_path / "unrelated.csv")
    output = tmp_path / "participant_demographics.csv"
    original = first.read_bytes()

    result = demographics.export_demographics(tmp_path, output)

    assert (result.output_path, result.exported_count, result.skipped_count, result.invalid_count) == (
        output, 2, 2, 0,
    )
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "participant_number": "007",
            "participant_age": "22",
            "participant_sex": "Female",
            "participant_handedness": "Right handed",
            "participant_colorblind": "False",
            "run_id": run_id,
            "started_at_utc": timestamp,
            "run_aborted": aborted,
            "source_file": path.name,
        }
        for run_id, timestamp, aborted, path in (
            ("first-run", "2026-10-01T16:00:00+00:00", "False", first),
            ("second-run", "2026-10-02T16:00:00+00:00", "True", second),
        )
    ]
    assert first.read_bytes() == original


def test_duplicate_runs_and_unsafe_or_inconsistent_metadata(tmp_path):
    _write_log(tmp_path / "sssep_task_events_a.csv")
    _write_log(tmp_path / "sssep_task_events_a_copy.csv")
    _write_log(tmp_path / "sssep_task_events_b.csv", run_id="second-run")
    _write_log(
        tmp_path / "sssep_task_events_b_copy.csv",
        run_id="second-run",
        participant_handedness="Left handed",
    )
    _write_log(tmp_path / "sssep_task_events_unsafe.csv", run_id="=1+1")
    conflicting = _write_log(tmp_path / "sssep_task_events_conflicting.csv", run_id="conflict")
    lines = conflicting.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace("Right handed", "Left handed")
    conflicting.write_text("\n".join(lines), encoding="utf-8")

    result = demographics.export_demographics(tmp_path, tmp_path / "demographics.csv")

    assert (result.exported_count, result.skipped_count, result.invalid_count) == (1, 5, 4)


def test_refuses_to_overwrite_a_task_log(tmp_path):
    source = _write_log(tmp_path / "sssep_task_events_run.csv")
    original = source.read_bytes()

    with pytest.raises(ValueError, match="does not replace a task log"):
        demographics.export_demographics(tmp_path, source)

    assert source.read_bytes() == original


def test_no_demographics_preserves_an_existing_export(tmp_path):
    _write_log(tmp_path / "sssep_task_events_test.csv", test_mode="True")
    output = tmp_path / "demographics.csv"
    output.write_bytes(b"previous export")

    with pytest.raises(ValueError, match="No participant demographics"):
        demographics.export_demographics(tmp_path, output)

    assert output.read_bytes() == b"previous export"


def test_failed_replacement_cleans_temporary_file_and_preserves_export(tmp_path, monkeypatch):
    _write_log(tmp_path / "sssep_task_events_run.csv")
    output = tmp_path / "demographics.csv"
    output.write_bytes(b"previous export")
    previous_files = set(tmp_path.iterdir())

    def fail_to_replace(*_):
        raise PermissionError("Destination file is in use")

    monkeypatch.setattr(demographics.os, "replace", fail_to_replace)

    with pytest.raises(PermissionError, match="Destination file is in use"):
        demographics.export_demographics(tmp_path, output)

    assert output.read_bytes() == b"previous export"
    assert set(tmp_path.iterdir()) == previous_files
