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
    BASELINE_EVENT_CODE,
    HIGHCUT,
    KURTOSIS_REJECT_Z,
    LOWCUT,
    FPVS_REFERENCE_COMMIT,
    MONTAGE_NAME,
    PROCESSING_METHOD,
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
    if stage in {"baseline_fft_window_cropping", "active_fft_window_cropping"}:
        return [
            "Use epochs longer than the combined FFT start and end crop.",
            "Restore the documented 15-second epoch if the duration was changed.",
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
    active_event_codes: tuple[int, ...] | list[int] | None = None,
    baseline_event_code: int = BASELINE_EVENT_CODE,
    epoch_window_sec: float | None = None,
    fft_crop_start_sec: float = 0.0,
    fft_crop_end_sec: float = 0.0,
) -> None:
    """Write a per-file text report with a beginner summary and technical log."""
    selected_active_codes = (
        tuple(ACTIVE_EVENT_CODES)
        if active_event_codes is None
        else tuple(active_event_codes)
    )
    active_found = [c for c in selected_active_codes if c in found_codes]
    active_missing = [c for c in selected_active_codes if c not in found_codes]
    successful_rows = _count_summary_rows(summary_rows, status="success")
    no_epoch_rows = _count_summary_rows(summary_rows, status="no_complete_epochs")
    unexpected_epoch_rows = sum(
        1 for row in summary_rows if row.get("epoch_count_ok") is False
    )
    warning_count = sum(1 for line in report_lines if line.upper().startswith(("WARNING:", "WARN:")))
    plots_folder = report_path.parent / "plots"

    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write("Targeted BioSemi SSSEP Processing Report\n")
        report_file.write("=" * 44 + "\n\n")
        report_file.write("Beginner summary\n")
        report_file.write("-" * 16 + "\n")
        if successful_rows:
            report_file.write("Result: Finished processing this file.\n")
        else:
            report_file.write("Result: No usable active-condition epochs.\n")
        report_file.write(f"File processed: {bdf_path.name}\n")
        report_file.write(f"Event summary CSV: {summary_csv_path}\n")
        report_file.write(f"Plots folder: {plots_folder}\n")
        report_file.write(f"Active triggers found: {active_found}\n")
        report_file.write(f"Active triggers missing: {active_missing}\n")
        report_file.write(
            f"Baseline trigger {baseline_event_code} found: "
            f"{baseline_event_code in found_codes}\n"
        )
        report_file.write(f"Successful trigger rows: {successful_rows}\n")
        report_file.write(f"Rows with no complete epochs: {no_epoch_rows}\n")
        report_file.write(f"Rows with a different epoch count than expected: {unexpected_epoch_rows}\n")
        report_file.write(f"Warnings in processing log: {warning_count}\n\n")
        report_file.write("Detailed settings and processing log\n")
        report_file.write("-" * 36 + "\n")
        report_file.write(f"File: {bdf_path.name}\n")
        report_file.write(f"Full path: {bdf_path}\n")
        report_file.write(f"Processing method: {PROCESSING_METHOD}\n")
        report_file.write(f"FPVS reference commit: {FPVS_REFERENCE_COMMIT}\n")
        report_file.write("FFT: float64 trial mean, volts to uV, abs(FFT) / N * 2; no taper or detrending.\n")
        report_file.write(f"Electrode montage: {MONTAGE_NAME}\n")
        report_file.write(f"Original sampling rate: {original_sfreq:.3f} Hz\n")
        report_file.write(f"Final sampling rate: {final_sfreq:.3f} Hz\n")
        report_file.write(f"Reference channels: {REFERENCE_CHANNELS}\n")
        report_file.write("Selected reference channels are dropped when present; see log for applied/skipped reference status.\n")
        report_file.write(f"Stim channel: {STIM_CHANNEL}\n")
        report_file.write(f"Lowcut: {LOWCUT} Hz\n")
        report_file.write(f"Highcut: {HIGHCUT} Hz\n")
        report_file.write("Filter before downsample; no additional notch or EEG zero replacement.\n")
        report_file.write("Final reference requested: average projection over retained good EEG, after interpolation; see log for outcome.\n")
        report_file.write(f"Kurtosis rejection Z threshold: {KURTOSIS_REJECT_Z}\n")
        report_file.write(f"Bad channels by kurtosis: {n_bad_by_kurtosis}\n")
        report_file.write(f"Active triggers found: {active_found}\n")
        report_file.write(f"Active triggers missing: {active_missing}\n")
        report_file.write(
            f"Baseline trigger {baseline_event_code} found: "
            f"{baseline_event_code in found_codes}\n"
        )
        extracted_epoch_sec = (
            analysis_window_sec if epoch_window_sec is None else epoch_window_sec
        )
        report_file.write(f"Extracted epoch window seconds: {extracted_epoch_sec}\n")
        report_file.write(f"FFT crop from epoch start seconds: {fft_crop_start_sec}\n")
        report_file.write(f"FFT crop from epoch end seconds: {fft_crop_end_sec}\n")
        report_file.write(f"Analysis window seconds: {analysis_window_sec}\n")
        report_file.write(
            "Additional SSSEP FIR epoch exclusion (disabled in FPVS method): "
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
