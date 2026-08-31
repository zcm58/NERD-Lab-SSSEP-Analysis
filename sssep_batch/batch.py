"""Run batches of `.bdf` files and write the batch-level summary.

This module is the bridge between the launcher and the per-file processing
pipeline. It performs beginner-friendly preflight checks, finds `.bdf` files,
limits native math-library threads, starts one worker process per file up to
`BATCH_WORKERS`, collects results, and writes `batch_processing_summary.csv`.

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
from typing import Callable

import pandas as pd

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
    MAX_INDIVIDUAL_PLOTS,
    OUTPUT_ROOT,
    PLOT_CHANNEL,
    TRIGGER_HZ_MAP,
    TRIGGER_LABELS,
)
from sssep_batch.logging_utils import ensure_folder, setup_batch_logger
from sssep_batch.models import AnalysisProtocol


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
    if not isinstance(MAX_INDIVIDUAL_PLOTS, int) or MAX_INDIVIDUAL_PLOTS < 0:
        problems.append("MAX_INDIVIDUAL_PLOTS cannot be negative.")
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
    """Build a normal-looking failure row for an unexpected worker crash."""
    bdf_path = Path(bdf_file)
    return {
        "file_name": bdf_path.name,
        "status": "failed",
        "failed_stage": "worker_crash",
        "output_folder": str(Path(output_root) / bdf_path.stem),
        "error": f"Worker crashed before returning a result: {exc}",
        "error_file": "",
    }


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

    batch_summary = pd.DataFrame(all_results)
    batch_summary_path = output_path / "batch_processing_summary.csv"
    batch_summary.to_csv(batch_summary_path, index=False)

    logger.info("=" * 78)
    logger.info("BATCH PROCESSING COMPLETE")
    logger.info("=" * 78)
    logger.info(f"Batch summary saved to: {batch_summary_path}")
    logger.info("\n" + batch_summary.to_string(index=False))

    final_status = "success" if failed_count == 0 else "completed_with_failures"
    _notify_progress(
        progress_callback,
        phase="complete",
        message=f"Batch summary saved to: {batch_summary_path}",
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
    }


def main() -> dict[str, object]:
    """Run the batch processor using fallback folders from `config.py`."""
    return run_batch(INPUT_FOLDER, OUTPUT_ROOT)
