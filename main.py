"""Open the SSSEP participant-task and recording-analysis GUI."""

import os


_NATIVE_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def main() -> int:
    """Limit native worker threads, then open the GUI."""

    for env_name in _NATIVE_THREAD_ENV_VARS:
        os.environ[env_name] = "1"

    from sssep_batch.gui import launch_gui

    return launch_gui()


if __name__ == "__main__":
    raise SystemExit(main())
