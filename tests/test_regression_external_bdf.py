"""Optional real-data regression test for a user-provided `.bdf` file.

The repository intentionally does not store EEG binary fixtures. This test only
runs when `SSSEP_TEST_BDF` points to a local file, so normal development and CI
can run the suite without private data.
"""

import os
from pathlib import Path

import pandas as pd
import pytest

from sssep_batch.config import ACTIVE_EVENT_CODES
from sssep_batch.pipeline import process_one_bdf


def test_external_bdf_regression_fixture(tmp_path):
    """Process one external `.bdf` file and check core output files/columns."""
    fixture_path = os.environ.get("SSSEP_TEST_BDF")
    if not fixture_path:
        pytest.skip("Set SSSEP_TEST_BDF to run the external .bdf regression test.")

    bdf_path = Path(fixture_path)
    if not bdf_path.exists():
        pytest.skip(f"Configured SSSEP_TEST_BDF does not exist: {bdf_path}")

    result = process_one_bdf(bdf_path, tmp_path)

    assert result["status"] == "success"

    summary_path = Path(result["summary_csv"])
    report_path = Path(result["output_folder"]) / f"{bdf_path.stem}_processing_report.txt"
    assert summary_path.exists()
    assert report_path.exists()

    summary_df = pd.read_csv(summary_path)
    assert not summary_df.empty
    assert set(summary_df["trigger_code"]) == set(ACTIVE_EVENT_CODES)
    assert {
        "file_name",
        "trigger_code",
        "trigger_label",
        "status",
        "usable_epochs",
        "processing_method",
        "sssep_fft_nearest_amplitude_uv",
        "fft_channels",
    }.issubset(summary_df.columns)
    assert (summary_df["processing_method"] == "fpvs_amplitude_v1").all()
    assert (summary_df["status"] == "success").any()
    assert not any("power" in field or "welch" in field for field in summary_df.columns)
