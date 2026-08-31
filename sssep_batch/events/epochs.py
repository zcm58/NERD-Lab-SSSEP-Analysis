"""Cut fixed-length EEG windows around trigger events.

For each trigger code, the pipeline needs repeated windows of EEG data with the
same duration and channel order. This module turns event sample numbers into a
3-D epoch array and counts windows extending outside the recording. It adds
no FIR-edge exclusion or NaN replacement to the FPVS-equivalent EEG.
"""

import mne
import numpy as np

from sssep_batch.config import PRE_EVENT_SEC, TRIGGER_LABELS
from sssep_batch.models import EpochSet


def extract_epochs_for_code(
    raw: mne.io.BaseRaw,
    events: np.ndarray,
    code: int,
    picks: list[str],
    window_sec: float,
) -> EpochSet:
    """
    Extract fixed-length EEG windows after each event of one trigger code.

    `events` uses the standard MNE event shape: sample number, previous value,
    trigger code. Each usable event becomes one epoch with shape
    `(n_channels, n_times)`. The returned `EpochSet` keeps both the data and the
    skip counts so reports can explain missing repetitions. SSSEP trial lengths
    are retained; FPVS's visual-oddball marker crop does not apply to this task.
    """

    sfreq = float(raw.info["sfreq"])
    code_events = events[events[:, 2] == code]
    n_samples = int(round(window_sec * sfreq))
    pre_samples = int(round(PRE_EVENT_SEC * sfreq))

    extracted: list[np.ndarray] = []
    extracted_events: list[np.ndarray] = []
    out_of_bounds_skipped = 0

    for event in code_events:
        event_sample = int(event[0]) - raw.first_samp
        start_sample = event_sample - pre_samples
        stop_sample = start_sample + n_samples

        if start_sample < 0 or stop_sample > raw.n_times:
            out_of_bounds_skipped += 1
            continue

        epoch = raw.get_data(start=start_sample, stop=stop_sample)
        extracted.append(epoch)
        extracted_events.append(event)

    if extracted:
        # FPVS constructs EpochsArray before picking EEG. Its default projector
        # application changes the last floating-point bits even when the raw
        # reference projection was already applied; preserve that operation.
        epochs = mne.EpochsArray(
            np.stack(extracted, axis=0), raw.info.copy(),
            events=np.asarray(extracted_events, dtype=int), event_id={str(code): code},
            tmin=0.0, baseline=None, verbose=False,
        ).pick("eeg", exclude="bads").pick(picks).get_data()
    else:
        epochs = np.empty((0, len(picks), n_samples), dtype=float)

    return EpochSet(
        code=code,
        label=TRIGGER_LABELS.get(code, f"Trigger {code}"),
        epochs=epochs,
        skipped_epochs=out_of_bounds_skipped,
        out_of_bounds_epochs=out_of_bounds_skipped,
        edge_excluded_epochs=0,
    )
