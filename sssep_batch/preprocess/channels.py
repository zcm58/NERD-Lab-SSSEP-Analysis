"""Channel validation and setup."""

from typing import Callable, Iterable

import mne

from sssep_batch.config import (
    ANALYSIS_CHANNELS,
    MONTAGE_NAME,
    REFERENCE_CHANNELS,
    SCALP_CHANNEL_COUNT,
    STIM_CHANNEL,
)


def require_channels(raw: mne.io.BaseRaw, required: Iterable[str], purpose: str) -> None:
    """Confirm that required channels exist in the BDF file."""
    missing = [name for name in required if name not in raw.ch_names]
    if missing:
        raise RuntimeError(
            f"Missing required channel(s) for {purpose}: {missing}. "
            f"Available channels include: {raw.ch_names[:20]}..."
        )


def get_scalp_channels(raw: mne.io.BaseRaw) -> list[str]:
    """Return the first 64 channel names as scalp EEG channels."""
    if len(raw.ch_names) < SCALP_CHANNEL_COUNT:
        raise RuntimeError(
            f"Expected at least {SCALP_CHANNEL_COUNT} channels, but found "
            f"only {len(raw.ch_names)}."
        )
    return list(raw.ch_names[:SCALP_CHANNEL_COUNT])


def validate_analysis_channels(raw: mne.io.BaseRaw) -> list[str]:
    """Check which EEG channels should be used for the final SSSEP analysis."""
    if ANALYSIS_CHANNELS:
        found = [ch for ch in ANALYSIS_CHANNELS if ch in raw.ch_names]
        missing = [ch for ch in ANALYSIS_CHANNELS if ch not in raw.ch_names]
        if not found:
            raise RuntimeError(
                "None of the requested ANALYSIS_CHANNELS were found. "
                f"Requested: {ANALYSIS_CHANNELS}"
            )
        if missing:
            raise RuntimeError(
                "Some requested ANALYSIS_CHANNELS were missing. Because you said "
                "you can ensure labels are correct, this script stops here so the "
                f"file can be fixed. Missing: {missing}"
            )
        return found

    eeg_picks = mne.pick_types(raw.info, eeg=True, stim=False, exclude=[])
    return [raw.ch_names[idx] for idx in eeg_picks]


def set_known_channel_types(
    raw: mne.io.BaseRaw,
    scalp_channels: list[str],
    log_func: Callable[[str], None],
) -> None:
    """Tell MNE which channels are EEG and which channel is the stimulus channel."""
    ch_type_map: dict[str, str] = {}
    for ch in scalp_channels:
        ch_type_map[ch] = "eeg"
    for ch in REFERENCE_CHANNELS:
        ch_type_map[ch] = "eeg"
    ch_type_map[STIM_CHANNEL] = "stim"

    raw.set_channel_types(ch_type_map, verbose=False)
    log_func(
        "Channel types set: first 64 channels=EEG, "
        f"{REFERENCE_CHANNELS}=EEG references, {STIM_CHANNEL}=stim."
    )


def apply_exg_reference_and_drop(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    log_func: Callable[[str], None],
) -> None:
    """Apply EXG1/EXG2 as the EEG reference and then drop those channels."""
    require_channels(raw, REFERENCE_CHANNELS, "EXG1/EXG2 referencing")

    log_func(
        f"Applying reference pair [{REFERENCE_CHANNELS[0]}, "
        f"{REFERENCE_CHANNELS[1]}] on {filename_for_log}..."
    )
    raw.set_eeg_reference(
        ref_channels=list(REFERENCE_CHANNELS),
        projection=False,
        verbose=False,
    )

    custom_ref_flag = raw.info.get("custom_ref_applied", None)
    log_func(
        f"AUDIT: custom_ref_applied={custom_ref_flag} "
        f"pair=[{REFERENCE_CHANNELS[0]},{REFERENCE_CHANNELS[1]}]"
    )

    refs_to_drop = [ch for ch in REFERENCE_CHANNELS if ch in raw.ch_names]
    if refs_to_drop:
        raw.drop_channels(refs_to_drop)
        for ch in refs_to_drop:
            log_func(f"Dropped {ch} after initial referencing.")


def keep_scalp_and_status_channels(
    raw: mne.io.BaseRaw,
    scalp_channels: list[str],
    filename_for_log: str,
    log_func: Callable[[str], None],
) -> None:
    """Keep the 64 scalp EEG channels and the Status channel."""
    keep = [ch for ch in scalp_channels if ch in raw.ch_names]
    if STIM_CHANNEL in raw.ch_names:
        keep.append(STIM_CHANNEL)
    else:
        raise RuntimeError(f"Cannot keep channels because {STIM_CHANNEL} is missing.")

    raw.pick_channels(keep, ordered=True)
    log_func(
        f"Kept {len(keep)} channels for {filename_for_log}: "
        f"{len(keep) - 1} scalp EEG + {STIM_CHANNEL}."
    )


def apply_biosemi_montage(
    raw: mne.io.BaseRaw,
    log_func: Callable[[str], None],
) -> None:
    """Apply the standard BioSemi 64-channel electrode layout."""
    montage = mne.channels.make_standard_montage(MONTAGE_NAME)
    raw.set_montage(montage, on_missing="ignore", verbose=False)
    log_func(f"Applied {MONTAGE_NAME} montage for scalp electrode positions.")
