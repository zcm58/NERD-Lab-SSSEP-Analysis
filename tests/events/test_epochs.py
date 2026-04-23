import numpy as np

from sssep_batch.events.epochs import extract_epochs_for_code


def test_extract_epochs_for_code_keeps_in_bounds_windows(raw_builder):
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


def test_extract_epochs_for_code_tracks_out_of_bounds_and_edge_exclusions(raw_builder):
    raw = raw_builder(["Cz", "Pz"], ["eeg", "eeg"], sfreq=10.0, n_times=100)
    events = np.array([[5, 0, 1], [20, 0, 1], [95, 0, 1]], dtype=int)

    epoch_set = extract_epochs_for_code(
        raw=raw,
        events=events,
        code=1,
        picks=["Cz", "Pz"],
        window_sec=1.0,
        edge_margin_samples=10,
    )

    assert epoch_set.epochs.shape == (1, 2, 10)
    assert epoch_set.skipped_epochs == 2
    assert epoch_set.out_of_bounds_epochs == 1
    assert epoch_set.edge_excluded_epochs == 1
