"""Batch entrypoint for SSSEP processing."""

from concurrent.futures import ProcessPoolExecutor, as_completed
import os
from pathlib import Path
from typing import Callable

import pandas as pd

from sssep_batch.config import BATCH_WORKERS, INPUT_FOLDER, OUTPUT_ROOT
from sssep_batch.logging_utils import ensure_folder, setup_batch_logger


THREAD_LIMIT_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

ProgressCallback = Callable[[dict[str, object]], None]


class BatchValidationError(RuntimeError):
    """Raised when user-selected batch folders are not ready to process."""


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
    folder_text = "" if folder is None else str(folder).strip()
    if not folder_text:
        raise BatchValidationError(f"Choose an {label} folder before processing.")
    return Path(folder_text)


def discover_bdf_files(input_folder: str | Path | None) -> list[Path]:
    """Return sorted `.bdf` files from a user-selected input folder."""
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

    bdf_files = sorted(input_path.glob("*.bdf"))
    if not bdf_files:
        raise BatchValidationError(
            "No .bdf files were found in the selected input folder. Choose a "
            f"folder that contains BioSemi .bdf files.\n\nSelected folder: {input_path}"
        )
    return bdf_files


def validate_batch_request(
    input_folder: str | Path | None,
    output_root: str | Path | None,
) -> tuple[Path, Path, list[Path]]:
    """Validate the selected folders before any processing starts."""
    input_path = _folder_path(input_folder, "input")
    output_path = _folder_path(output_root, "output")

    if output_path.exists() and not output_path.is_dir():
        raise BatchValidationError(
            "Output path is an existing file. Choose a folder where the "
            f"analysis outputs should be saved.\n\nSelected path: {output_path}"
        )

    bdf_files = discover_bdf_files(input_path)
    return input_path, output_path, bdf_files


def _notify_progress(
    progress_callback: ProgressCallback | None,
    *,
    phase: str,
    message: str,
    completed: int,
    total: int,
) -> None:
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
    """Build a failure result when a worker process crashes before returning."""
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
) -> dict[str, object]:
    """
    Run the full batch processor for the selected folders.

    The batch runner uses a process pool for file-level parallelism: each
    worker processes one `.bdf` file at a time, and no analysis stage inside a
    single file is parallelized here. The effective worker count is
    `min(BATCH_WORKERS, number_of_files)`.
    """

    configure_native_thread_limits()
    input_path, output_path, bdf_files = validate_batch_request(input_folder, output_root)
    ensure_folder(output_path)
    logger = setup_batch_logger(output_path)

    total_files = len(bdf_files)
    logger.info(f"Input folder: {input_path}")
    logger.info(f"Output folder: {output_path}")
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
            future = executor.submit(process_one_bdf, bdf_file, output_path)
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
