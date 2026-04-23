import numpy as np

from sssep_batch.config import ACTIVE_EVENT_CODES, BASELINE_EVENT_CODE
from sssep_batch.events.status import find_status_events, parse_trigger_label


def test_parse_trigger_label_splits_condition_and_finger():
    assert parse_trigger_label("Think Thumb") == ("Think", "Thumb")
    assert parse_trigger_label("Gap/Break") == ("Gap/Break", "")


def test_find_status_events_filters_to_intended_codes(raw_builder, tmp_path):
    active_code = ACTIVE_EVENT_CODES[0]
    status = np.zeros(120, dtype=float)
    status[10] = active_code
    status[11] = 0
    status[40] = 99
    status[41] = 0
    status[80] = BASELINE_EVENT_CODE
    status[81] = 0

    raw = raw_builder(
        ["Cz", "Pz", "Status"],
        ["eeg", "eeg", "stim"],
        sfreq=256.0,
        n_times=120,
        data=np.vstack([np.zeros(120), np.zeros(120), status]),
    )
    log_lines: list[str] = []

    all_events, intended_events, found_codes = find_status_events(
        raw=raw,
        filename_for_log="synthetic.bdf",
        output_folder=tmp_path,
        log_func=log_lines.append,
    )

    assert set(all_events[:, 2]) == {active_code, 99, BASELINE_EVENT_CODE}
    assert set(intended_events[:, 2]) == {active_code, BASELINE_EVENT_CODE}
    assert found_codes == sorted([active_code, 99, BASELINE_EVENT_CODE])
    assert (tmp_path / "detected_status_events.csv").exists()
