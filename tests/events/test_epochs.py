"""Tests for cutting fixed analysis windows from event sample numbers.

The raw data is synthetic and small, which lets the tests directly check how
many epochs are kept, rejected as out-of-bounds, and projected before FFT.
"""

import mne
import numpy as np

from sssep_batch.events.epochs import extract_epochs_for_code


def test_extract_epochs_for_code_keeps_in_bounds_windows(raw_builder):
    """Events with complete in-bounds windows should become usable epochs."""
    raw = raw_builder(["Cz", "Pz"], ["eeg", "eeg"], sfreq=10.0, n_times=100)
    events = np.array([[20, 0, 1], [40, 0, 1]], dtype=int)

    epoch_set = extract_epochs_for_code(
        raw=raw,
        events=events,
        code=1,
        picks=["Cz", "Pz"],
        window_sec=1.0,
    )

    assert epoch_set.epochs.shape == (2, 2, 10)
    assert epoch_set.skipped_epochs == 0
    assert epoch_set.out_of_bounds_epochs == 0
    assert epoch_set.edge_excluded_epochs == 0


def test_extract_epochs_only_rejects_out_of_bounds_windows(raw_builder):
    """FPVS parity adds no extra FIR boundary exclusion to complete trials."""
    raw = raw_builder(["Cz", "Pz"], ["eeg", "eeg"], sfreq=10.0, n_times=100)
    events = np.array([[5, 0, 1], [20, 0, 1], [95, 0, 1]], dtype=int)

    epoch_set = extract_epochs_for_code(
        raw=raw,
        events=events,
        code=1,
        picks=["Cz", "Pz"],
        window_sec=1.0,
    )

    assert epoch_set.epochs.shape == (2, 2, 10)
    assert epoch_set.skipped_epochs == 1
    assert epoch_set.out_of_bounds_epochs == 1
    assert epoch_set.edge_excluded_epochs == 0


def test_epoch_samples_account_for_first_samp_and_do_not_replace_nonfinite():
    data = np.arange(100, dtype=float)[None, :]
    data[0, 22] = np.nan
    raw = mne.io.RawArray(data, mne.create_info(["Cz"], 10.0, ["eeg"]), first_samp=100, verbose=False)
    result = extract_epochs_for_code(raw, np.array([[120, 0, 1]]), 1, ["Cz"], 1.0)
    np.testing.assert_array_equal(result.epochs[0], data[:, 20:30])


def test_epochs_preserve_fpvs_projector_application_after_raw_reference(raw_builder):
    names = mne.channels.make_standard_montage("biosemi64").ch_names
    data = np.random.default_rng(842).normal(scale=1e-6, size=(65, 1024))
    data[-1] = 0
    raw = raw_builder(names + ["Status"], ["eeg"] * 64 + ["stim"], sfreq=256, data=data)
    raw.set_eeg_reference("average", projection=True, verbose=False)
    raw.apply_proj(verbose=False)
    unprojected = raw.get_data(start=128, stop=640)[None, :]
    expected = mne.EpochsArray(
        unprojected.copy(), raw.info.copy(), baseline=None, verbose=False,
    ).pick("eeg", exclude="bads").get_data()
    assert not np.array_equal(expected, unprojected[:, :64])
    actual = extract_epochs_for_code(raw, np.array([[128, 0, 1]]), 1, names, 2.0)
    np.testing.assert_array_equal(actual.epochs, expected)
