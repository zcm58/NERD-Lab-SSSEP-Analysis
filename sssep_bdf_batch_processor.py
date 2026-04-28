"""
Targeted BioSemi BDF SSSEP Batch Processor
==========================================

This file is kept as a thin compatibility wrapper. The implementation now lives
under the `sssep_batch` package so the processing pipeline is split into smaller
modules with dedicated responsibilities.

Beginner map
------------
- This is the file users run from PyCharm.
- It sets native math-library thread limits before anything heavy imports.
- It then opens the PySide6 launcher from `sssep_batch.gui`.
- It intentionally does not contain analysis logic.

How to run in PyCharm
---------------------
1. In the PyCharm Project pane, right-click `sssep_bdf_batch_processor.py`.
2. Click `Run 'sssep_bdf_batch_processor'`.
3. Choose input and output folders in the launcher, then click Process Data.
"""

import os


# Cap native worker threads before importing scientific libraries. The batch
# runner parallelizes across files, so each worker should not also start a large
# BLAS/OpenMP thread pool.
for env_name in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[env_name] = "1"

from sssep_batch.gui import launch_gui


if __name__ == "__main__":
    # `launch_gui()` returns a process exit code; raising SystemExit passes that
    # code back to Python/PyCharm.
    raise SystemExit(launch_gui())
