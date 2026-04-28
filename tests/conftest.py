"""Shared pytest fixtures for small synthetic EEG test data.

The tests avoid real `.bdf` files by building tiny in-memory MNE `RawArray`
objects. This keeps the default test suite fast and makes each test easier for
beginners to understand.
"""

import mne
import numpy as np
import pytest


@pytest.fixture
def raw_builder():
    """Return a helper that creates minimal MNE raw objects for tests."""

    def _build(
        ch_names: list[str],
        ch_types: list[str],
        *,
        sfreq: float = 100.0,
        n_times: int = 200,
        data: np.ndarray | None = None,
    ) -> mne.io.RawArray:
        """Build one synthetic raw recording with requested channels and data."""
        if data is None:
            data = np.zeros((len(ch_names), n_times), dtype=float)
        info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)
        return mne.io.RawArray(np.asarray(data, dtype=float), info, verbose=False)

    return _build
