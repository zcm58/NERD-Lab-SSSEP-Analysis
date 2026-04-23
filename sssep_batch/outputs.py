"""Report and summary writing."""

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


def write_summary_csv(
    output_folder: Path,
    file_stem: str,
    summary_rows: list[dict[str, object]],
) -> Path:
    """Write the per-file summary CSV."""
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
) -> None:
    """Write the per-file processing report."""
    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write("Targeted BioSemi SSSEP Processing Report\n")
        report_file.write("=" * 44 + "\n\n")
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
    """Write the per-file error report."""
    with open(error_path, "w", encoding="utf-8") as error_file:
        error_file.write("Targeted BioSemi SSSEP Processing Error\n")
        error_file.write("=" * 39 + "\n\n")
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
