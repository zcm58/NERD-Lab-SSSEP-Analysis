"""Filesystem and logging helpers."""

import logging
from pathlib import Path
from typing import Callable


def ensure_folder(path: str | Path) -> None:
    """Create a folder if it does not already exist."""
    Path(path).mkdir(parents=True, exist_ok=True)


def setup_batch_logger(output_root: str | Path) -> logging.Logger:
    """
    Create a logger that writes messages to both the console and a log file.
    """

    ensure_folder(output_root)
    logger = logging.getLogger("sssep_bdf_processor")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(
        Path(output_root) / "sssep_batch_processing.log",
        mode="w",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def make_file_log_func(report_lines: list[str]) -> Callable[[str], None]:
    """
    Build a simple logging function for one BDF file.
    """

    def _log(message: str) -> None:
        report_lines.append(message)

    return _log
