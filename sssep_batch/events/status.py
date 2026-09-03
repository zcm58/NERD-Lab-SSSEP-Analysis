"""Find and document trigger events from the BioSemi `Status` channel.

BioSemi recordings store trigger codes in a special stimulus channel named
`Status`. This module extracts those events after preprocessing, keeps only the
active trigger codes and the configured baseline/delimiter code, and writes a small audit
CSV so users can see which raw trigger codes were present.
"""

from pathlib import Path
from typing import Callable

import mne
import numpy as np
import pandas as pd

from sssep_batch.config import (
    ACTIVE_EVENT_CODES,
    BASELINE_EVENT_CODE,
    STIM_CHANNEL,
)


def parse_trigger_label(label: str) -> tuple[str, str]:
    """Split labels like `Think Thumb` into condition and finger parts."""
    parts = label.split(maxsplit=1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return label, ""


def find_status_events(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    output_folder: Path,
    log_func: Callable[[str], None],
    *,
    active_event_codes: tuple[int, ...] | list[int] | None = None,
    baseline_event_code: int = BASELINE_EVENT_CODE,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """
    Find trigger events from the BioSemi Status channel and keep intended codes.

    The returned tuple contains all raw Status events, the subset used by this
    analysis, and a sorted list of every trigger code found in the file. The
    event samples are on the final sampling grid, matching FPVS's active runner.
    """

    selected_active_codes = (
        tuple(ACTIVE_EVENT_CODES)
        if active_event_codes is None
        else tuple(active_event_codes)
    )

    try:
        all_events = mne.find_events(
            raw, stim_channel=STIM_CHANNEL, shortest_event=1, verbose=False,
        )
    except Exception:
        # The active FPVS runner uses MNE's default annotation mapping here.
        all_events, _ = mne.events_from_annotations(raw, verbose=False)
        log_func("Status event detection failed; using annotation events as in FPVS.")

    if len(all_events) == 0:
        raise RuntimeError(f"No trigger events found in {STIM_CHANNEL}.")

    found_codes = sorted(np.unique(all_events[:, 2]).astype(int).tolist())
    intended_codes = set((*selected_active_codes, baseline_event_code))
    intended_mask = np.isin(all_events[:, 2], list(intended_codes))
    intended_events = all_events[intended_mask]

    if len(intended_events) == 0:
        raise RuntimeError(
            "Events were found, but none matched the intended trigger codes. "
            f"Found codes: {found_codes}. Intended codes: {sorted(intended_codes)}."
        )

    missing_active = [code for code in selected_active_codes if code not in found_codes]
    baseline_found = baseline_event_code in found_codes

    log_func(f"Found Status trigger codes in {filename_for_log}: {found_codes}")
    log_func(f"Active trigger codes missing from file: {missing_active if missing_active else 'None'}")
    log_func(f"Baseline trigger {baseline_event_code} found: {baseline_found}")

    event_rows = pd.DataFrame(
        {
            "sample": all_events[:, 0],
            "previous_value": all_events[:, 1],
            "trigger_code": all_events[:, 2],
            "intended_for_analysis_or_baseline": intended_mask,
        }
    )
    event_rows.to_csv(output_folder / "detected_status_events.csv", index=False)

    return all_events, intended_events, found_codes
