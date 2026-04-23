"""Batch entrypoint for SSSEP processing."""

from concurrent.futures import ProcessPoolExecutor, as_completed
import glob
import os
from pathlib import Path

import pandas as pd

from sssep_batch.config import BATCH_WORKERS, INPUT_FOLDER, OUTPUT_ROOT
from sssep_batch.logging_utils import ensure_folder, setup_batch_logger
from sssep_batch.pipeline import process_one_bdf


THREAD_LIMIT_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


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


def main() -> None:
    """
    Run the full batch processor.

    The batch runner uses a process pool for file-level parallelism: each
    worker processes one `.bdf` file at a time, and no analysis stage inside a
    single file is parallelized here. The effective worker count is
    `min(BATCH_WORKERS, number_of_files)`.
    """

    configure_native_thread_limits()
    ensure_folder(OUTPUT_ROOT)
    logger = setup_batch_logger(OUTPUT_ROOT)

    bdf_files = sorted(glob.glob(os.path.join(INPUT_FOLDER, "*.bdf")))
    if not bdf_files:
        raise RuntimeError(f"No .bdf files found in: {INPUT_FOLDER}")

    logger.info(f"Found {len(bdf_files)} .bdf file(s) in {INPUT_FOLDER}.")
    selected_workers = max(1, min(BATCH_WORKERS, len(bdf_files)))
    logger.info(
        f"Using file-level parallel processing with {selected_workers} worker(s)."
    )

    indexed_results: list[dict[str, object] | None] = [None] * len(bdf_files)
    with ProcessPoolExecutor(max_workers=selected_workers) as executor:
        future_to_file = {
            executor.submit(process_one_bdf, bdf_file, OUTPUT_ROOT): (index, bdf_file)
            for index, bdf_file in enumerate(bdf_files)
        }
        for future in as_completed(future_to_file):
            index, bdf_file = future_to_file[future]
            try:
                result = future.result()
            except Exception as exc:
                result = make_worker_crash_result(bdf_file, OUTPUT_ROOT, exc)
            indexed_results[index] = result
            status = result.get("status", "unknown")
            if status == "success":
                logger.info(f"COMPLETED: {result['file_name']}")
            else:
                logger.error(
                    f"FAILED: {result['file_name']} | "
                    f"stage={result.get('failed_stage', 'unknown')} | "
                    f"error={result.get('error', 'unknown')}"
                )

    all_results = [result for result in indexed_results if result is not None]

    batch_summary = pd.DataFrame(all_results)
    batch_summary_path = Path(OUTPUT_ROOT) / "batch_processing_summary.csv"
    batch_summary.to_csv(batch_summary_path, index=False)

    logger.info("=" * 78)
    logger.info("BATCH PROCESSING COMPLETE")
    logger.info("=" * 78)
    logger.info(f"Batch summary saved to: {batch_summary_path}")
    logger.info("\n" + batch_summary.to_string(index=False))
