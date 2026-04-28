"""Write CSV summaries, human-readable reports, and error reports.

This module is the final output layer for one processed `.bdf` file. It does
not compute metrics; it receives rows and report text from the pipeline and
writes durable files that beginner users can inspect after a run.

The CSV field names are part of the user-facing contract. The beginner summary
sections in text reports can be expanded, but CSV renames/removals should only
happen when explicitly requested.
"""

from pathlib import Path

import pandas as pd

from sssep_batch.config import (
    ACTIVE_EVENT_CODES,
    APPLY_NOTCH,
    BASELINE_EVENT_CODE,
    HIGHCUT,
    KURTOSIS_REJECT_Z,
    LOWCUT,
    NOTCH_FREQ,
    REFERENCE_CHANNELS,
    STIM_CHANNEL,
)


def _count_summary_rows(
    summary_rows: list[dict[str, object]],
    *,
    status: str,
) -> int:
    """Count per-trigger summary rows with a specific status value."""
    return sum(1 for row in summary_rows if row.get("status") == status)


def _next_steps_for_stage(stage: str) -> list[str]:
    """Return beginner-friendly troubleshooting steps for a failed pipeline stage."""
    if stage == "loading_bdf":
        return [
            "Confirm the file is a BioSemi .bdf file.",
            "Close the file in other programs before running again.",
        ]
    if stage == "validating_channels":
        return [
            "Confirm the recording includes EXG1, EXG2, and Status channels.",
            "Check whether this file came from the expected BioSemi setup.",
        ]
    if stage == "status_event_detection":
        return [
            "Confirm the BioSemi Status channel contains the expected triggers.",
            "Check whether the selected file belongs to this SSSEP experiment.",
        ]
    if stage in {"filter_validation", "basic_fir_filtering"}:
        return [
            "Review LOWCUT, HIGHCUT, and trigger frequencies in sssep_batch/config.py.",
            "Undo recent config edits if the default settings used to work.",
        ]
    return [
        "Open batch_processing_summary.csv and find this file's error_file path.",
        "Share this ERROR.txt file with whoever is helping debug the run.",
    ]


def write_summary_csv(
    output_folder: Path,
    file_stem: str,
    summary_rows: list[dict[str, object]],
) -> Path:
    """Write the per-file event summary CSV and return its path."""
    summary_df = pd.DataFrame(summary_rows)
    summary_path = output_folder / f"{file_stem}_sssep_event_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    return summary_path


def write_processing_report(
    report_path: Path,
    bdf_path: Path,
    original_sfreq: float,
    final_sfreq: float,
    n_bad_by_kurtosis: int,
    found_codes: list[int],
    analysis_window_sec: float,
    filter_edge_margin_samples: int,
    filter_edge_margin_sec: float,
    analysis_channels: list[str],
    report_lines: list[str],
    summary_rows: list[dict[str, object]],
    summary_csv_path: Path,
) -> None:
    """Write a per-file text report with a beginner summary and technical log."""
    active_found = [c for c in ACTIVE_EVENT_CODES if c in found_codes]
    active_missing = [c for c in ACTIVE_EVENT_CODES if c not in found_codes]
    successful_rows = _count_summary_rows(summary_rows, status="success")
    no_epoch_rows = _count_summary_rows(summary_rows, status="no_complete_epochs")
    short_epoch_rows = sum(
        1 for row in summary_rows if row.get("epoch_count_ok") is False
    )
    warning_count = sum(1 for line in report_lines if line.startswith("WARNING:"))
    plots_folder = report_path.parent / "plots"

    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write("Targeted BioSemi SSSEP Processing Report\n")
        report_file.write("=" * 44 + "\n\n")
        report_file.write("Beginner summary\n")
        report_file.write("-" * 16 + "\n")
        report_file.write("Result: Finished processing this file.\n")
        report_file.write(f"File processed: {bdf_path.name}\n")
        report_file.write(f"Event summary CSV: {summary_csv_path}\n")
        report_file.write(f"Plots folder: {plots_folder}\n")
        report_file.write(f"Active triggers found: {active_found}\n")
        report_file.write(f"Active triggers missing: {active_missing}\n")
        report_file.write(
            f"Baseline trigger {BASELINE_EVENT_CODE} found: "
            f"{BASELINE_EVENT_CODE in found_codes}\n"
        )
        report_file.write(f"Successful trigger rows: {successful_rows}\n")
        report_file.write(f"Rows with no complete epochs: {no_epoch_rows}\n")
        report_file.write(f"Rows with fewer epochs than expected: {short_epoch_rows}\n")
        report_file.write(f"Warnings in processing log: {warning_count}\n\n")
        report_file.write("Detailed settings and processing log\n")
        report_file.write("-" * 36 + "\n")
        report_file.write(f"File: {bdf_path.name}\n")
        report_file.write(f"Full path: {bdf_path}\n")
        report_file.write(f"Original sampling rate: {original_sfreq:.3f} Hz\n")
        report_file.write(f"Final sampling rate: {final_sfreq:.3f} Hz\n")
        report_file.write(f"Reference channels: {REFERENCE_CHANNELS}\n")
        report_file.write("Reference channels dropped after reference: Yes\n")
        report_file.write(f"Stim channel: {STIM_CHANNEL}\n")
        report_file.write(f"Lowcut: {LOWCUT} Hz\n")
        report_file.write(f"Highcut: {HIGHCUT} Hz\n")
        report_file.write(f"Notch requested: {APPLY_NOTCH}, {NOTCH_FREQ} Hz\n")
        report_file.write(f"Kurtosis rejection Z threshold: {KURTOSIS_REJECT_Z}\n")
        report_file.write(f"Bad channels by kurtosis: {n_bad_by_kurtosis}\n")
        report_file.write(f"Active triggers found: {[c for c in ACTIVE_EVENT_CODES if c in found_codes]}\n")
        report_file.write(f"Active triggers missing: {[c for c in ACTIVE_EVENT_CODES if c not in found_codes]}\n")
        report_file.write(f"Baseline trigger {BASELINE_EVENT_CODE} found: {BASELINE_EVENT_CODE in found_codes}\n")
        report_file.write(f"Analysis window seconds: {analysis_window_sec}\n")
        report_file.write(
            "FIR edge exclusion margin: "
            f"{filter_edge_margin_samples} samples "
            f"({filter_edge_margin_sec:.3f} sec)\n"
        )
        report_file.write(f"Analysis channels: {analysis_channels}\n\n")
        report_file.write("Step-by-step log\n")
        report_file.write("-" * 16 + "\n")
        for line in report_lines:
            report_file.write(line + "\n")


def write_error_report(
    error_path: Path,
    bdf_path: Path,
    stage: str,
    exc: Exception,
    error_text: str,
    report_lines: list[str],
) -> None:
    """Write `ERROR.txt` for a file that failed before normal report writing."""
    next_steps = _next_steps_for_stage(stage)
    with open(error_path, "w", encoding="utf-8") as error_file:
        error_file.write("Targeted BioSemi SSSEP Processing Error\n")
        error_file.write("=" * 39 + "\n\n")
        error_file.write("Beginner summary\n")
        error_file.write("-" * 16 + "\n")
        error_file.write("Result: This file did not finish processing.\n")
        error_file.write(f"File: {bdf_path.name}\n")
        error_file.write(f"Failed step: {stage}\n")
        error_file.write(f"Main error: {exc}\n")
        error_file.write("What to try next:\n")
        for step in next_steps:
            error_file.write(f"- {step}\n")
        error_file.write("\nTechnical details\n")
        error_file.write("-" * 17 + "\n")
        error_file.write(f"File: {bdf_path.name}\n")
        error_file.write(f"Full path: {bdf_path}\n")
        error_file.write(f"FAILED_STAGE: {stage}\n")
        error_file.write(f"Error: {exc}\n\n")
        error_file.write("Traceback:\n")
        error_file.write(error_text)
        error_file.write("\n\nStep-by-step log before failure:\n")
        error_file.write("-" * 35 + "\n")
        for line in report_lines:
            error_file.write(line + "\n")
