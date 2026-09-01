"""Run batches of `.bdf` files and write the batch-level summary.

This module is the bridge between the launcher and the per-file processing
pipeline. It performs beginner-friendly preflight checks, finds `.bdf` files,
limits native math-library threads, starts one worker process per file up to
`BATCH_WORKERS`, collects participant spectra, and writes the batch summary,
consolidated FFT tables, and equal-participant group plots.

The important design rule is that parallelism happens across files only. A
single file's filtering, epoch extraction, metrics, plots, and reports all stay
inside `pipeline.py` and its domain-specific helper modules.
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import importlib.util
from math import isfinite
from numbers import Real
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
import traceback
from typing import Callable

import numpy as np
import pandas as pd

from sssep_batch.analysis.grouping import (
    GroupSpectrum,
    average_group_spectra,
    group_spectra_to_dataframe,
    participant_spectra_to_dataframe,
)
from sssep_batch.analysis.protocol import default_analysis_protocol
from sssep_batch.config import (
    ACTIVE_EVENT_CODES,
    BATCH_WORKERS,
    BASELINE_EVENT_CODE,
    DOWNSAMPLE_RATE,
    EVENT_DURATION_SEC,
    EXPECTED_REPETITIONS_PER_TRIGGER,
    FMAX,
    FMIN,
    HIGHCUT,
    INPUT_FOLDER,
    LOWCUT,
    OUTPUT_ROOT,
    PLOT_CHANNEL,
    PROCESSING_METHOD,
    SAVE_CSV_SUMMARIES,
    SAVE_PLOTS,
    TRIGGER_HZ_MAP,
    TRIGGER_LABELS,
)
from sssep_batch.logging_utils import ensure_folder, setup_batch_logger
from sssep_batch.models import AnalysisProtocol, ParticipantSpectrum, Spectrum
from sssep_batch.outputs import write_error_report


THREAD_LIMIT_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

ProgressCallback = Callable[[dict[str, object]], None]

REQUIRED_PACKAGE_IMPORTS = {
    "MNE": "mne",
    "NumPy": "numpy",
    "SciPy": "scipy",
    "matplotlib": "matplotlib",
    "pandas": "pandas",
    "PySide6": "PySide6",
}


class BatchValidationError(RuntimeError):
    """User-facing setup problem that should be shown without a traceback."""


def configure_native_thread_limits() -> None:
    """
    Cap math-library thread fanout before worker processes are spawned.

    The batch runner uses multiple worker processes to handle separate `.bdf`
    files in parallel. Without these limits, each worker can also try to start
    its own BLAS/OpenMP thread pool, which can lead to CPU oversubscription and
    slower overall throughput.
    """
    for env_name in THREAD_LIMIT_ENV_VARS:
        os.environ[env_name] = "1"


def _folder_path(folder: str | Path | None, label: str) -> Path:
    """Convert a GUI/config folder value into a `Path`, rejecting blanks."""
    folder_text = "" if folder is None else str(folder).strip()
    if not folder_text:
        raise BatchValidationError(f"Choose an {label} folder before processing.")
    return Path(folder_text)


def discover_bdf_files(input_folder: str | Path | None) -> list[Path]:
    """Return sorted `.bdf` files or raise a beginner-readable folder error."""
    input_path = _folder_path(input_folder, "input")
    if not input_path.exists():
        raise BatchValidationError(
            "Input folder does not exist. Choose a folder that contains "
            f"BioSemi .bdf files.\n\nSelected folder: {input_path}"
        )
    if not input_path.is_dir():
        raise BatchValidationError(
            "Input path is not a folder. Choose a folder that contains "
            f"BioSemi .bdf files.\n\nSelected path: {input_path}"
        )

    bdf_files = sorted(path for path in input_path.glob("*.bdf") if path.is_file())
    if not bdf_files:
        raise BatchValidationError(
            "No .bdf files were found in the selected input folder. Choose a "
            f"folder that contains BioSemi .bdf files.\n\nSelected folder: {input_path}"
        )
    return bdf_files


def validate_required_packages() -> None:
    """Check that packages from `requirements.txt` are importable."""
    missing = [
        package_name
        for package_name, import_name in REQUIRED_PACKAGE_IMPORTS.items()
        if importlib.util.find_spec(import_name) is None
    ]
    if missing:
        missing_text = ", ".join(missing)
        raise BatchValidationError(
            "Required Python packages are missing from the active environment: "
            f"{missing_text}.\n\n"
            "What to try next: open the PyCharm terminal, confirm it starts "
            "with (.venv), then run: pip install -r requirements.txt"
        )


def validate_config_settings() -> None:
    """Check obvious beginner-editable config mistakes before processing.

    This is not a full scientific validation of the analysis plan. It catches
    common setup mistakes that would otherwise produce confusing Python errors,
    such as text where a number is expected or a trigger code with no label.
    """
    problems: list[str] = []
    if not isinstance(BATCH_WORKERS, int) or BATCH_WORKERS < 1:
        problems.append("BATCH_WORKERS must be a whole number of 1 or more.")
    if DOWNSAMPLE_RATE is not None and (
        not isinstance(DOWNSAMPLE_RATE, Real)
        or not isfinite(DOWNSAMPLE_RATE) or DOWNSAMPLE_RATE < 0
    ):
        problems.append("DOWNSAMPLE_RATE must be positive, or 0/None to disable downsampling.")
    lowcut_valid = LOWCUT is None or (
        isinstance(LOWCUT, Real) and isfinite(LOWCUT) and LOWCUT >= 0
    )
    highcut_valid = HIGHCUT is None or (
        isinstance(HIGHCUT, Real) and isfinite(HIGHCUT) and HIGHCUT > 0
    )
    if not lowcut_valid:
        problems.append("LOWCUT must be positive, or 0/None to disable the high-pass filter.")
    if not highcut_valid:
        problems.append("HIGHCUT must be positive, or None to disable the low-pass filter.")
    if lowcut_valid and highcut_valid and LOWCUT is not None and HIGHCUT is not None:
        if LOWCUT >= HIGHCUT:
            problems.append("HIGHCUT must be greater than LOWCUT.")
    if not all(isinstance(value, Real) and isfinite(value) for value in (FMIN, FMAX)):
        problems.append("FMIN and FMAX must be finite numbers.")
    elif FMIN < 0 or FMAX <= FMIN:
        problems.append("FMIN must be nonnegative and FMAX must be greater than FMIN.")
    if (
        not isinstance(EXPECTED_REPETITIONS_PER_TRIGGER, int)
        or EXPECTED_REPETITIONS_PER_TRIGGER < 1
    ):
        problems.append("EXPECTED_REPETITIONS_PER_TRIGGER must be 1 or more.")
    if (
        not isinstance(EVENT_DURATION_SEC, Real)
        or isinstance(EVENT_DURATION_SEC, bool)
        or not isfinite(EVENT_DURATION_SEC)
        or EVENT_DURATION_SEC <= 0
    ):
        problems.append("EVENT_DURATION_SEC must be a finite number above zero.")
    if not isinstance(PLOT_CHANNEL, str) or not PLOT_CHANNEL.strip():
        problems.append("PLOT_CHANNEL must be a non-empty electrode label, such as 'Cz'.")
    if not ACTIVE_EVENT_CODES:
        problems.append("ACTIVE_EVENT_CODES must include at least one trigger code.")
    elif len(ACTIVE_EVENT_CODES) != len(set(ACTIVE_EVENT_CODES)):
        problems.append("ACTIVE_EVENT_CODES must not contain duplicate trigger codes.")

    missing_labels = [code for code in ACTIVE_EVENT_CODES if code not in TRIGGER_LABELS]
    missing_freqs = [code for code in ACTIVE_EVENT_CODES if code not in TRIGGER_HZ_MAP]
    if missing_labels:
        problems.append(f"TRIGGER_LABELS is missing active trigger code(s): {missing_labels}.")
    if missing_freqs:
        problems.append(f"TRIGGER_HZ_MAP is missing active trigger code(s): {missing_freqs}.")
    invalid_freqs = [
        code
        for code in ACTIVE_EVENT_CODES
        if code in TRIGGER_HZ_MAP
        and TRIGGER_HZ_MAP[code] is not None
        and (
            not isinstance(TRIGGER_HZ_MAP[code], Real)
            or isinstance(TRIGGER_HZ_MAP[code], bool)
            or not isfinite(TRIGGER_HZ_MAP[code])
            or TRIGGER_HZ_MAP[code] <= 0
        )
    ]
    if invalid_freqs:
        problems.append(
            "TRIGGER_HZ_MAP values must be positive finite numbers or None; "
            f"check code(s): {invalid_freqs}."
        )
    if BASELINE_EVENT_CODE not in TRIGGER_LABELS:
        problems.append(
            f"TRIGGER_LABELS is missing baseline trigger code {BASELINE_EVENT_CODE}."
        )

    if problems:
        problem_text = "\n".join(f"- {problem}" for problem in problems)
        raise BatchValidationError(
            "Some settings in sssep_batch/config.py need attention before "
            f"processing can start:\n\n{problem_text}\n\n"
            "What to try next: undo the last config edit or compare this file "
            "against the documented examples in config.py."
        )


def validate_plot_channel_selection(plot_channel: object) -> str:
    """Return a clean electrode label or raise a beginner-visible error."""
    if not isinstance(plot_channel, str) or not plot_channel.strip():
        raise BatchValidationError(
            "The FFT plot electrode must be a channel label such as 'Cz', 'C3', or 'C4'."
        )
    return plot_channel.strip()


def validate_analysis_protocol_selection(
    analysis_protocol: AnalysisProtocol | None,
) -> AnalysisProtocol:
    """Return explicit batch event settings or the validated config defaults."""

    try:
        selected = analysis_protocol or default_analysis_protocol()
    except (TypeError, ValueError, KeyError) as exc:
        raise BatchValidationError(
            f"The task analysis settings are invalid: {exc}"
        ) from exc
    if not isinstance(selected, AnalysisProtocol):
        raise BatchValidationError(
            "The task analysis settings must be an AnalysisProtocol value."
        )
    return selected


def ensure_output_folder_ready(output_path: Path) -> None:
    """Create and probe the output folder so permission errors are clear."""
    try:
        ensure_folder(output_path)
        with NamedTemporaryFile(prefix=".sssep_write_test_", dir=output_path) as probe:
            probe.write(b"ok\n")
            probe.flush()
    except OSError as exc:
        raise BatchValidationError(
            "The output folder could not be created or written to. Choose a "
            "folder where you have permission to save files.\n\n"
            f"Selected folder: {output_path}\n"
            f"System error: {exc}"
        ) from exc


def create_run_output_folder(output_root: Path) -> Path:
    """Atomically create a new run folder without reusing earlier results."""
    prefix = datetime.now().strftime("run_%Y%m%d_%H%M%S_")
    return Path(mkdtemp(prefix=prefix, dir=output_root))


def validate_batch_request(
    input_folder: str | Path | None,
    output_root: str | Path | None,
) -> tuple[Path, Path, list[Path]]:
    """Validate input/output folder paths and discover files to process."""
    input_path = _folder_path(input_folder, "input")
    output_path = _folder_path(output_root, "output")

    if output_path.exists() and not output_path.is_dir():
        raise BatchValidationError(
            "Output path is an existing file. Choose a folder where the "
            f"analysis outputs should be saved.\n\nSelected path: {output_path}"
        )

    bdf_files = discover_bdf_files(input_path)
    return input_path, output_path, bdf_files


def run_preflight_checks(
    input_folder: str | Path | None,
    output_root: str | Path | None,
) -> dict[str, object]:
    """Run all preflight checks before any `.bdf` processing starts."""
    input_path, output_path, bdf_files = validate_batch_request(
        input_folder,
        output_root,
    )
    ensure_output_folder_ready(output_path)
    validate_required_packages()
    validate_config_settings()
    return {
        "status": "ready",
        "input_folder": str(input_path),
        "output_folder": str(output_path),
        "bdf_file_count": len(bdf_files),
        "bdf_files": [str(path) for path in bdf_files],
        "packages": "ok",
        "config": "ok",
    }


def _notify_progress(
    progress_callback: ProgressCallback | None,
    *,
    phase: str,
    message: str,
    completed: int,
    total: int,
) -> None:
    """Send a structured progress event to the GUI if a callback was provided."""
    if progress_callback is None:
        return
    progress_callback(
        {
            "phase": phase,
            "message": message,
            "completed": completed,
            "total": total,
        }
    )


def get_process_one_bdf():
    """Import the heavy per-file processor only when processing starts."""
    from sssep_batch.pipeline import process_one_bdf

    return process_one_bdf


def make_worker_crash_result(
    bdf_file: str,
    output_root: str | Path,
    exc: Exception,
) -> dict[str, object]:
    """Write a durable per-file report for an unexpected worker crash."""

    bdf_path = Path(bdf_file)
    output_folder = Path(output_root) / bdf_path.stem
    ensure_folder(output_folder)
    error_path = output_folder / "ERROR.txt"
    crash_error = RuntimeError(f"Worker crashed before returning a result: {exc}")
    write_error_report(
        error_path=error_path,
        bdf_path=bdf_path,
        stage="worker_crash",
        exc=crash_error,
        error_text="".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ),
        report_lines=[
            "The batch parent detected an unexpected worker-process failure.",
            "No normal per-file result was returned by the worker.",
        ],
    )
    return {
        "file_name": bdf_path.name,
        "status": "failed",
        "failed_stage": "worker_crash",
        "output_folder": str(output_folder),
        "error": str(crash_error),
        "error_file": str(error_path),
        "processing_method": PROCESSING_METHOD,
    }


def _selected_group_channel(
    group: GroupSpectrum,
    channel: str,
) -> tuple[Spectrum, int] | None:
    """Return a one-electrode group spectrum and its participant count."""

    if channel not in group.channel_names:
        return None
    index = group.channel_names.index(channel)
    return (
        Spectrum(
            freqs=group.spectrum.freqs,
            amplitude_uv=group.spectrum.amplitude_uv[[index]],
            method=group.spectrum.method,
        ),
        group.channel_participant_counts[index],
    )


def run_batch(
    input_folder: str | Path | None,
    output_root: str | Path | None,
    progress_callback: ProgressCallback | None = None,
    plot_channel: str = PLOT_CHANNEL,
    analysis_protocol: AnalysisProtocol | None = None,
) -> dict[str, object]:
    """
    Run the full batch processor for the selected folders.

    Every run writes into a new child folder of the selected output root.
    The returned output_folder identifies that run, not the selected root.

    The batch runner uses a process pool for file-level parallelism: each
    worker processes one `.bdf` file at a time, and no analysis stage inside a
    single file is parallelized here. The effective worker count is
    `min(BATCH_WORKERS, number_of_files)`.

    The returned dictionary is used by the GUI to show final status and by tests
    to confirm that successes and failures were counted correctly.
    """

    selected_plot_channel = validate_plot_channel_selection(plot_channel)
    selected_protocol = validate_analysis_protocol_selection(analysis_protocol)
    configure_native_thread_limits()
    preflight = run_preflight_checks(input_folder, output_root)
    input_path = Path(str(preflight["input_folder"]))
    output_path = create_run_output_folder(Path(str(preflight["output_folder"])))
    bdf_files = [Path(path) for path in preflight["bdf_files"]]
    logger = setup_batch_logger(output_path)

    total_files = len(bdf_files)
    logger.info(f"Input folder: {input_path}")
    logger.info(f"Output folder: {output_path}")
    logger.info(f"FFT plot electrode: {selected_plot_channel}")
    logger.info(
        "Task analysis protocol: triggers=%s, duration=%g s, expected repetitions=%d",
        list(selected_protocol.active_event_codes),
        selected_protocol.event_duration_sec,
        selected_protocol.expected_repetitions_per_trigger,
    )
    logger.info("Preflight checks passed: folders, packages, and config are ready.")
    logger.info(f"Found {total_files} .bdf file(s) in {input_path}.")
    _notify_progress(
        progress_callback,
        phase="discovered",
        message=f"Found {total_files} .bdf file(s).",
        completed=0,
        total=total_files,
    )

    selected_workers = max(1, min(BATCH_WORKERS, total_files))
    logger.info(
        f"Using file-level parallel processing with {selected_workers} worker(s)."
    )

    indexed_results: list[dict[str, object] | None] = [None] * total_files
    indexed_spectra: list[tuple[ParticipantSpectrum, ...] | None] = [None] * total_files
    process_one_bdf = get_process_one_bdf()
    with ProcessPoolExecutor(max_workers=selected_workers) as executor:
        future_to_file = {}
        for index, bdf_file in enumerate(bdf_files):
            logger.info(f"QUEUED {index + 1}/{total_files}: {bdf_file.name}")
            _notify_progress(
                progress_callback,
                phase="queued",
                message=f"Queued {index + 1}/{total_files}: {bdf_file.name}",
                completed=0,
                total=total_files,
            )
            future = executor.submit(
                process_one_bdf,
                bdf_file,
                output_path,
                selected_plot_channel,
                selected_protocol,
            )
            future_to_file[future] = (index, bdf_file)

        completed_count = 0
        success_count = 0
        failed_count = 0
        for future in as_completed(future_to_file):
            index, bdf_file = future_to_file[future]
            try:
                result = future.result()
            except Exception as exc:
                result = make_worker_crash_result(str(bdf_file), output_path, exc)
            payload = result.pop("_participant_spectra", ())
            indexed_spectra[index] = (
                tuple(payload)
                if isinstance(payload, (tuple, list))
                else (payload,)
            )
            indexed_results[index] = result
            completed_count += 1
            status = result.get("status", "unknown")
            if status == "success":
                success_count += 1
                message = f"COMPLETED {completed_count}/{total_files}: {result['file_name']}"
                logger.info(message)
                phase = "file_completed"
            else:
                failed_count += 1
                message = (
                    f"FAILED {completed_count}/{total_files}: {result['file_name']} | "
                    f"stage={result.get('failed_stage', 'unknown')} | "
                    f"error={result.get('error', 'unknown')}"
                )
                logger.error(message)
                phase = "file_failed"
            _notify_progress(
                progress_callback,
                phase=phase,
                message=message,
                completed=completed_count,
                total=total_files,
            )

    all_results = [result for result in indexed_results if result is not None]
    participant_plot_count = sum(
        int(result.get("participant_plot_count", 0) or 0) for result in all_results
    )
    participant_plot_failures = sum(
        int(result.get("participant_plot_failures", 0) or 0)
        for result in all_results
    )
    participant_spectra = tuple(
        spectrum
        for file_spectra in indexed_spectra
        if file_spectra is not None
        for spectrum in file_spectra
    )

    batch_summary = pd.DataFrame(all_results)
    batch_summary_path = output_path / "batch_processing_summary.csv"
    batch_summary.to_csv(batch_summary_path, index=False)

    group_output_status = "disabled"
    group_output_error = ""
    group_output_error_file = ""
    participant_fft_csv = ""
    group_fft_csv = ""
    group_plots_folder = ""
    group_plot_files: list[str] = []
    group_plot_skipped_trigger_codes: list[int] = []
    group_plot_warnings: list[str] = []
    group_plot_errors: list[str] = []
    group_plot_error_file = ""
    participant_fft_csv_status = "disabled" if not SAVE_CSV_SUMMARIES else "pending"
    group_fft_csv_status = "disabled" if not SAVE_CSV_SUMMARIES else "pending"
    group_plot_status = "disabled" if not SAVE_PLOTS else "pending"

    group_outputs_requested = SAVE_CSV_SUMMARIES or SAVE_PLOTS
    if group_outputs_requested and not participant_spectra and success_count == 0:
        group_output_status = "skipped_no_usable_spectra"
        if SAVE_CSV_SUMMARIES:
            participant_fft_csv_status = "skipped_no_usable_spectra"
            group_fft_csv_status = "skipped_no_usable_spectra"
        if SAVE_PLOTS:
            group_plot_status = "skipped_no_usable_spectra"
        logger.warning("Group outputs skipped because no recording produced usable FFT spectra.")
    elif group_outputs_requested:
        try:
            if not participant_spectra:
                raise RuntimeError(
                    "Successful recording results did not include participant FFT spectra."
                )

            _notify_progress(
                progress_callback,
                phase="group_outputs",
                message="Creating consolidated FFT tables and group plots...",
                completed=total_files,
                total=total_files,
            )
            if SAVE_CSV_SUMMARIES:
                participant_fft_path = output_path / "participant_fft_amplitudes.csv"
                participant_frames = [
                    participant_spectra_to_dataframe((record,))
                    for record in participant_spectra
                ]
                pd.concat(participant_frames, ignore_index=True, sort=False).to_csv(
                    participant_fft_path, index=False
                )
                participant_fft_csv = str(participant_fft_path)
                participant_fft_csv_status = "success"
                logger.info(f"Participant FFT table saved to: {participant_fft_path}")

            groups = average_group_spectra(participant_spectra)
            if SAVE_CSV_SUMMARIES:
                group_fft_path = output_path / "group_fft_amplitudes.csv"
                group_spectra_to_dataframe(groups).to_csv(group_fft_path, index=False)
                group_fft_csv = str(group_fft_path)
                group_fft_csv_status = "success"
                logger.info(f"Group FFT table saved to: {group_fft_path}")

            if SAVE_PLOTS:
                from sssep_batch.analysis.plotting import plot_spectrum

                groups_by_event = {
                    (group.event_type, group.trigger_code): group for group in groups
                }
                baseline_records_by_participant = {
                    record.participant_id: record
                    for record in participant_spectra
                    if record.event_type == "baseline"
                    and record.trigger_code == selected_protocol.baseline_event_code
                }

                group_plots_path = output_path / "group_plots"
                ensure_folder(group_plots_path)
                group_plots_folder = str(group_plots_path)
                plot_error_details: list[str] = []
                for trigger in selected_protocol.active_triggers:
                    cue_group = groups_by_event.get(("cue", trigger.code))
                    if cue_group is None:
                        group_plot_skipped_trigger_codes.append(trigger.code)
                        logger.warning(
                            "Group plot skipped for trigger %d (%s): no participant "
                            "spectrum was available.",
                            trigger.code,
                            trigger.label,
                        )
                        continue
                    selected_cue = _selected_group_channel(
                        cue_group, selected_plot_channel
                    )
                    if selected_cue is None:
                        group_plot_skipped_trigger_codes.append(trigger.code)
                        logger.warning(
                            "Group plot skipped for trigger %d (%s): electrode %s was "
                            "unavailable for every contributing participant.",
                            trigger.code,
                            trigger.label,
                            selected_plot_channel,
                        )
                        continue

                    cue_spectrum, cue_count = selected_cue
                    baseline_spectrum = None
                    baseline_label = "Gap/Break group mean"
                    cue_plot_records = [
                        record
                        for record in participant_spectra
                        if record.event_type == "cue"
                        and record.trigger_code == trigger.code
                        and selected_plot_channel in record.channel_names
                    ]
                    matched_baseline_records = [
                        baseline_records_by_participant.get(record.participant_id)
                        for record in cue_plot_records
                    ]
                    missing_baseline_participants = [
                        cue_record.participant_id
                        for cue_record, baseline_record in zip(
                            cue_plot_records, matched_baseline_records
                        )
                        if baseline_record is None
                        or selected_plot_channel not in baseline_record.channel_names
                    ]
                    if missing_baseline_participants:
                        baseline_warning = (
                            f"Group baseline omitted for trigger {trigger.code} "
                            f"({trigger.label}): selected-electrode baseline data were "
                            "missing for cue participant(s) "
                            f"{missing_baseline_participants}."
                        )
                        group_plot_warnings.append(baseline_warning)
                        logger.warning(baseline_warning)
                    elif matched_baseline_records:
                        baseline_amplitudes = np.stack(
                            [
                                baseline_record.spectrum.amplitude_uv[
                                    baseline_record.channel_names.index(
                                        selected_plot_channel
                                    )
                                ]
                                for baseline_record in matched_baseline_records
                                if baseline_record is not None
                            ]
                        )
                        baseline_spectrum = Spectrum(
                            freqs=cue_spectrum.freqs,
                            amplitude_uv=np.mean(
                                baseline_amplitudes.astype(np.float64, copy=False),
                                axis=0,
                            )[None, :],
                            method=cue_spectrum.method,
                        )
                        baseline_label = (
                            f"Gap/Break group mean (matched N={cue_count})"
                        )
                    plot_path = group_plots_path / (
                        f"group_cue_{trigger.code:03d}_fft_amplitude.png"
                    )
                    try:
                        plot_spectrum(
                            active=cue_spectrum,
                            baseline=baseline_spectrum,
                            title=(
                                f"Group - Cue {trigger.code} {trigger.label} - FFT amplitude"
                            ),
                            outpath=plot_path,
                            target_hz=trigger.target_hz,
                            channel_names=[selected_plot_channel],
                            plot_channel=selected_plot_channel,
                            active_label=f"Cue group mean (N={cue_count})",
                            baseline_label=baseline_label,
                        )
                    except Exception as exc:
                        message = (
                            f"Group plot failed for trigger {trigger.code} "
                            f"({trigger.label}): {exc}"
                        )
                        group_plot_errors.append(message)
                        group_plot_skipped_trigger_codes.append(trigger.code)
                        plot_error_details.append(
                            f"{message}\n\n{traceback.format_exc()}"
                        )
                        logger.error(message)
                        try:
                            plot_path.unlink(missing_ok=True)
                        except OSError as cleanup_exc:
                            logger.error(
                                "Could not remove incomplete group plot %s: %s",
                                plot_path,
                                cleanup_exc,
                            )
                        continue
                    group_plot_files.append(str(plot_path))

                if plot_error_details:
                    plot_error_path = output_path / "GROUP_PLOT_ERRORS.txt"
                    plot_error_path.write_text(
                        "One or more group cue plots failed. Consolidated FFT CSV "
                        "files and successful plots were preserved.\n\n"
                        + "\n\n".join(plot_error_details),
                        encoding="utf-8",
                    )
                    group_plot_error_file = str(plot_error_path)
                    group_plot_status = "completed_with_failures"
                elif group_plot_skipped_trigger_codes or group_plot_warnings:
                    group_plot_status = "success_with_warnings"
                else:
                    group_plot_status = "success"
                logger.info(
                    "Created %d group plot(s), one per usable cue for electrode %s.",
                    len(group_plot_files),
                    selected_plot_channel,
                )

            group_output_status = (
                "success_with_warnings"
                if (
                    group_plot_skipped_trigger_codes
                    or group_plot_warnings
                    or group_plot_errors
                )
                else "success"
            )
        except Exception as exc:
            group_output_status = "failed"
            if participant_fft_csv_status == "pending":
                participant_fft_csv_status = "failed"
            if group_fft_csv_status == "pending":
                group_fft_csv_status = "failed"
            if group_plot_status == "pending":
                group_plot_status = "failed"
            group_output_error = str(exc) or type(exc).__name__
            group_error_path = output_path / "GROUP_OUTPUT_ERROR.txt"
            group_error_path.write_text(
                "Group output creation failed.\n\n"
                "Per-recording result folders and batch_processing_summary.csv "
                "were preserved. Any consolidated CSVs completed before this "
                "error were also preserved.\n\n"
                f"Error: {group_output_error}\n\n"
                f"{traceback.format_exc()}",
                encoding="utf-8",
            )
            group_output_error_file = str(group_error_path)
            logger.error(
                "Group output creation failed; per-recording outputs were preserved. "
                "See %s. Error: %s",
                group_error_path,
                group_output_error,
            )

    logger.info("=" * 78)
    logger.info("BATCH PROCESSING COMPLETE")
    logger.info("=" * 78)
    logger.info(f"Batch summary saved to: {batch_summary_path}")
    logger.info("\n" + batch_summary.to_string(index=False))

    final_status = (
        "success"
        if (
            failed_count == 0
            and group_output_status != "failed"
            and not group_plot_errors
        )
        else "completed_with_failures"
    )
    completion_message = (
        f"Batch summary saved to: {batch_summary_path}. "
        f"Group outputs: {group_output_status}."
    )
    _notify_progress(
        progress_callback,
        phase="complete",
        message=completion_message,
        completed=total_files,
        total=total_files,
    )
    return {
        "status": final_status,
        "input_folder": str(input_path),
        "output_folder": str(output_path),
        "summary_csv": str(batch_summary_path),
        "total_files": total_files,
        "succeeded": success_count,
        "failed": failed_count,
        "results": all_results,
        "participant_plot_count": participant_plot_count,
        "participant_plot_failures": participant_plot_failures,
        "group_output_status": group_output_status,
        "participant_fft_csv": participant_fft_csv,
        "group_fft_csv": group_fft_csv,
        "group_plots_folder": group_plots_folder,
        "group_plot_files": group_plot_files,
        "group_plot_count": len(group_plot_files),
        "group_plot_skipped_trigger_codes": group_plot_skipped_trigger_codes,
        "group_plot_status": group_plot_status,
        "group_plot_warnings": group_plot_warnings,
        "group_plot_errors": group_plot_errors,
        "group_plot_error_file": group_plot_error_file,
        "participant_fft_csv_status": participant_fft_csv_status,
        "group_fft_csv_status": group_fft_csv_status,
        "group_output_error": group_output_error,
        "group_output_error_file": group_output_error_file,
    }


def main() -> dict[str, object]:
    """Run the batch processor using fallback folders from `config.py`."""
    return run_batch(INPUT_FOLDER, OUTPUT_ROOT)
