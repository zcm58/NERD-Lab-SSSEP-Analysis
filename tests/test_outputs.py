"""Tests for beginner-friendly processing and error report text.

These tests focus on report wording and structure. They do not check CSV math,
because reports receive already-computed rows from the pipeline.
"""

from pathlib import Path

from sssep_batch.outputs import write_error_report, write_processing_report


def test_write_processing_report_includes_beginner_summary(tmp_path):
    """Successful reports should start with a readable summary section."""
    report_path = tmp_path / "sample_processing_report.txt"
    summary_path = tmp_path / "sample_sssep_event_summary.csv"

    write_processing_report(
        report_path=report_path,
        bdf_path=Path("sample.bdf"),
        original_sfreq=2048.0,
        final_sfreq=256.0,
        n_bad_by_kurtosis=1,
        found_codes=[1, 100],
        analysis_window_sec=7.5,
        filter_edge_margin_samples=100,
        filter_edge_margin_sec=0.391,
        analysis_channels=["Pz", "Cz"],
        report_lines=["WARNING: synthetic warning"],
        summary_rows=[
            {"status": "success", "epoch_count_ok": True},
            {"status": "no_complete_epochs", "epoch_count_ok": False},
        ],
        summary_csv_path=summary_path,
    )

    text = report_path.read_text(encoding="utf-8")
    assert "Beginner summary" in text
    assert "Result: Finished processing this file." in text
    assert f"Event summary CSV: {summary_path}" in text
    assert "Warnings in processing log: 1" in text


def test_write_error_report_includes_next_steps(tmp_path):
    """Error reports should include stage-specific next steps before traceback."""
    error_path = tmp_path / "ERROR.txt"

    write_error_report(
        error_path=error_path,
        bdf_path=Path("sample.bdf"),
        stage="loading_bdf",
        exc=RuntimeError("synthetic failure"),
        error_text="Traceback text",
        report_lines=["Started"],
    )

    text = error_path.read_text(encoding="utf-8")
    assert "Beginner summary" in text
    assert "Result: This file did not finish processing." in text
    assert "Confirm the file is a BioSemi .bdf file." in text
