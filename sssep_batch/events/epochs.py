"""Cut fixed-length EEG windows around trigger events.

For each trigger code, the pipeline needs repeated windows of EEG data with the
same duration and channel order. This module turns event sample numbers into a
3-D epoch array and records why any event was skipped, such as being too close
to the file boundary or inside the FIR filter edge margin.
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
    edge_margin_samples: int = 0,
) -> EpochSet:
    """
    Extract fixed-length EEG windows after each event of one trigger code.

    `events` uses the standard MNE event shape: sample number, previous value,
    trigger code. Each usable event becomes one epoch with shape
    `(n_channels, n_times)`. The returned `EpochSet` keeps both the data and the
    skip counts so reports can explain missing repetitions.
    """

    sfreq = float(raw.info["sfreq"])
    code_events = events[events[:, 2] == code]
    n_samples = int(round(window_sec * sfreq))
    pre_samples = int(round(PRE_EVENT_SEC * sfreq))

    extracted: list[np.ndarray] = []
    out_of_bounds_skipped = 0
    edge_margin_skipped = 0

    for event in code_events:
        event_sample = int(event[0])
        start_sample = event_sample - pre_samples
        stop_sample = start_sample + n_samples

        if start_sample < 0 or stop_sample > raw.n_times:
            out_of_bounds_skipped += 1
            continue

        if (
            edge_margin_samples > 0
            and (
                start_sample < edge_margin_samples
                or stop_sample > raw.n_times - edge_margin_samples
            )
        ):
            edge_margin_skipped += 1
            continue

        epoch = raw.get_data(picks=picks, start=start_sample, stop=stop_sample)
        epoch = np.nan_to_num(epoch, nan=0.0, posinf=0.0, neginf=0.0)
        extracted.append(epoch)

    if extracted:
        epochs = np.stack(extracted, axis=0)
    else:
        epochs = np.empty((0, len(picks), n_samples), dtype=float)

    return EpochSet(
        code=code,
        label=TRIGGER_LABELS.get(code, f"Trigger {code}"),
        epochs=epochs,
        skipped_epochs=out_of_bounds_skipped + edge_margin_skipped,
        out_of_bounds_epochs=out_of_bounds_skipped,
        edge_excluded_epochs=edge_margin_skipped,
    )
