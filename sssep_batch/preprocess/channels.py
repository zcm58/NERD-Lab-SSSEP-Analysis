"""Validate and prepare channel metadata before filtering and analysis.

Beginners can think of this module as the "make sure the recording looks like
the expected BioSemi setup" step. It checks required channels, tells MNE which
channels are EEG versus stimulus channels, applies the EXG reference, keeps the
intended scalp channels, and applies the BioSemi electrode layout.
"""

import ast
import re
import warnings
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
    """Stop early if a required channel is missing from the recording."""
    missing = [name for name in required if name not in raw.ch_names]
    if missing:
        raise RuntimeError(
            f"Missing required channel(s) for {purpose}: {missing}. "
            f"Available channels include: {raw.ch_names[:20]}..."
        )


def get_scalp_channels(raw: mne.io.BaseRaw) -> list[str]:
    """Return the first 64 channel names, which this experiment treats as scalp EEG."""
    if len(raw.ch_names) < SCALP_CHANNEL_COUNT:
        raise RuntimeError(
            f"Expected at least {SCALP_CHANNEL_COUNT} channels, but found "
            f"only {len(raw.ch_names)}."
        )
    return list(raw.ch_names[:SCALP_CHANNEL_COUNT])


def validate_analysis_channels(raw: mne.io.BaseRaw) -> list[str]:
    """Return the final analysis channels or stop if a requested channel is absent."""
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


def get_fft_channels(raw: mne.io.BaseRaw) -> list[str]:
    """Use FPVS's complete BioSemi order, otherwise preserve actual good labels.

    A complete recognized montage is ordered like FPVS's 64-channel export.
    Subsets and unknown labels keep their recording order. Unlike FPVS's legacy
    unknown-64 branch, this never replaces unknown electrode names with guessed
    BioSemi labels.
    """
    picks = mne.pick_types(raw.info, eeg=True, exclude="bads")
    names = [raw.ch_names[index] for index in picks]
    standard = mne.channels.make_standard_montage("biosemi64").ch_names
    if len(names) == len(standard) and set(names) == set(standard):
        return standard
    return names


def set_known_channel_types(
    raw: mne.io.BaseRaw,
    scalp_channels: list[str],
    log_func: Callable[[str], None],
) -> None:
    """Match FPVS's EXG/stim typing while preserving other loaded channel types.

    ``scalp_channels`` remains accepted by existing callers; the FPVS loader
    does not override the types of the first 64 channels as a group.
    """
    present = {name.casefold(): name for name in raw.ch_names}
    refs = {present[name.casefold()] for name in REFERENCE_CHANNELS if name.casefold() in present}
    exg = {present[f"exg{index}"] for index in range(1, 9) if f"exg{index}" in present}
    to_misc = {name: "misc" for name in exg - refs}
    to_eeg = {name: "eeg" for name in refs}
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"The unit for channel\(s\) .* has changed from .* to .*\.",
                category=RuntimeWarning,
            )
            if to_misc:
                raw.set_channel_types(to_misc)
            if to_eeg:
                raw.set_channel_types(to_eeg)
            stim = present.get(STIM_CHANNEL.casefold())
            if stim:
                raw.set_channel_types({stim: "stim"})
        log_func(f"EXG typing: EEG references={sorted(refs)}; misc={sorted(to_misc)}.")
    except Exception as exc:
        log_func(f"Warning: EXG/stim typing adjustment failed: {exc}")


def apply_exg_reference_and_drop(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    log_func: Callable[[str], None],
) -> None:
    """Apply the EXG1/EXG2 reference pair, then remove those reference channels."""
    if all(ch in raw.ch_names for ch in REFERENCE_CHANNELS):
        try:
            ch_types = dict(zip(raw.ch_names, raw.get_channel_types()))
            to_eeg = {ch: "eeg" for ch in REFERENCE_CHANNELS if ch_types[ch] != "eeg"}
            if to_eeg:
                raw.set_channel_types(to_eeg)
            log_func(f"Applying reference pair {list(REFERENCE_CHANNELS)} on {filename_for_log}...")
            raw.set_eeg_reference(
                ref_channels=list(REFERENCE_CHANNELS),
                projection=False,
                verbose=False,
            )
            log_func(f"AUDIT: custom_ref_applied=True pair={list(REFERENCE_CHANNELS)}")
        except Exception as exc:
            log_func(f"Warn: Initial reference failed for {filename_for_log}: {exc}")
    else:
        log_func(f"Skip initial referencing for {filename_for_log}: reference channels missing.")

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
    """Drop unrelated channels so later steps see scalp EEG plus Status only."""
    keep = [ch for ch in scalp_channels if ch in raw.ch_names]
    if STIM_CHANNEL in raw.ch_names and STIM_CHANNEL not in keep:
        keep.append(STIM_CHANNEL)

    raw.pick_channels(keep, ordered=False)
    eeg_count = raw.get_channel_types().count("eeg")
    log_func(
        f"Kept {len(raw.ch_names)} channels for {filename_for_log}: "
        f"{eeg_count} EEG; {STIM_CHANNEL} present={STIM_CHANNEL in raw.ch_names}."
    )


def apply_biosemi_montage(
    raw: mne.io.BaseRaw,
    log_func: Callable[[str], None],
) -> None:
    """Apply the configured FPVS montage before initial reference and channel drop."""
    try:
        montage = mne.channels.make_standard_montage(MONTAGE_NAME)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            raw.set_montage(montage, on_missing="warn", match_case=False, verbose=False)
        for warning in caught:
            match = re.search(r"channels missing from the montage are:\s*(\[[^\]]*\])", str(warning.message))
            missing = set(ast.literal_eval(match.group(1))) if match else set()
            if missing and missing.issubset(REFERENCE_CHANNELS):
                continue
            warnings.warn(warning.message, category=warning.category, stacklevel=2)
        log_func(f"Applied {MONTAGE_NAME} montage for scalp electrode positions.")
    except Exception as exc:
        log_func(f"Warning: Montage error: {exc}")


def apply_final_average_reference(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    log_func: Callable[[str], None],
) -> None:
    """Apply the FPVS final average-reference projector after interpolation."""
    try:
        eeg_picks = mne.pick_types(raw.info, eeg=True, exclude=raw.info["bads"])
        if len(eeg_picks) > 0:
            raw.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
            raw.apply_proj(verbose=False)
            log_func(f"Average reference applied to {filename_for_log}.")
        else:
            log_func(f"Skip average ref for {filename_for_log}: No good EEG channels.")
    except Exception as exc:
        log_func(f"Warn: Average reference failed for {filename_for_log}: {exc}")
