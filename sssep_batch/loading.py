"""Read the same BioSemi channel subset as FPVS Toolbox's active loader."""

from pathlib import Path

import mne

from sssep_batch.config import REFERENCE_CHANNELS, SCALP_CHANNEL_COUNT, STIM_CHANNEL


def load_bdf(bdf_path: str | Path) -> mne.io.BaseRaw:
    """Read first-N channels plus references and Status in original file order.

    FPVS uses a disk-backed preload; an in-memory preload here has the same
    float64 samples and avoids leaving temporary recording files behind.
    """
    header = mne.io.read_raw_bdf(
        str(bdf_path), preload=False, stim_channel=STIM_CHANNEL, verbose=False
    )
    try:
        names = list(header.ch_names)
    finally:
        header.close()
    wanted = {name.casefold() for name in names[:SCALP_CHANNEL_COUNT]}
    wanted.update(name.casefold() for name in (*REFERENCE_CHANNELS, STIM_CHANNEL))
    include = [name for name in names if name.casefold() in wanted]
    return mne.io.read_raw_bdf(
        str(bdf_path), preload=True, stim_channel=STIM_CHANNEL,
        include=include, verbose=False,
    )
