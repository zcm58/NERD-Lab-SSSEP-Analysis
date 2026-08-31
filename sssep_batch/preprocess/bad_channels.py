"""Detect unusually noisy EEG channels and interpolate them when possible.

This module uses excess kurtosis as a simple automatic bad-channel detector.
Channels with very unusual kurtosis are marked bad, written to
`bad_channel_metrics.csv`, and interpolated if the recording has a montage.
Interpolation uses spherical splines and the positions of all retained good
EEG channels to estimate each bad channel's signal.
"""

from pathlib import Path
from typing import Callable

import mne
import numpy as np
import pandas as pd
from scipy.stats import kurtosis

from sssep_batch.config import KURTOSIS_REJECT_Z, KURTOSIS_TRIM_PROPORTION


def detect_and_interpolate_bad_channels_by_kurtosis(
    raw: mne.io.BaseRaw,
    filename_for_log: str,
    output_folder: Path,
    log_func: Callable[[str], None],
    debug_enabled: bool = False,
) -> pd.DataFrame:
    """Detect high-kurtosis EEG channels, interpolate them, and save metrics."""

    if not KURTOSIS_REJECT_Z:
        log_func(f"Skip Kurtosis for {filename_for_log} (no threshold).")
        metrics = pd.DataFrame()
        metrics.to_csv(output_folder / "bad_channel_metrics.csv", index=False)
        return metrics

    log_func(
        f"Kurtosis rejection for {filename_for_log} "
        f"(abs(Z) > {KURTOSIS_REJECT_Z})..."
    )

    bad_k_auto: list[str] = []
    metrics = pd.DataFrame()

    eeg_picks = mne.pick_types(
        raw.info,
        eeg=True,
        stim=False,
        exclude=raw.info["bads"],
    )

    if len(eeg_picks) >= 2:
        data = raw.get_data(picks=eeg_picks)
        k_values = kurtosis(data, axis=1, fisher=True, bias=False)
        k_values = np.nan_to_num(k_values, copy=False)

        n_k = len(k_values)
        trim_count = int(np.floor(n_k * KURTOSIS_TRIM_PROPORTION))
        z_scores = np.full(n_k, np.nan, dtype=float)

        if n_k - 2 * trim_count > 1:
            k_sorted = np.sort(k_values)
            k_trimmed = k_sorted[trim_count: n_k - trim_count]
            m_trimmed = float(np.mean(k_trimmed))
            s_trimmed = float(np.std(k_trimmed))
            log_func(
                f"Trimmed Norm for {filename_for_log}: "
                f"Mean={m_trimmed:.3f}, Std={s_trimmed:.3f} "
                f"(N_trimmed={len(k_trimmed)})"
            )
            if s_trimmed > 1e-9:
                z_scores = (k_values - m_trimmed) / s_trimmed
                bad_idx = np.where(np.abs(z_scores) > KURTOSIS_REJECT_Z)[0]
                ch_names_pick = [raw.info["ch_names"][i] for i in eeg_picks]
                bad_k_auto = [ch_names_pick[i] for i in bad_idx]
            else:
                log_func(
                    f"Kurtosis Trimmed Std Dev near zero for {filename_for_log}."
                )
        else:
            log_func(
                f"Not enough data for Kurtosis trimmed stats in "
                f"{filename_for_log} (N_k={n_k})."
            )

        ch_names_pick = [raw.info["ch_names"][i] for i in eeg_picks]
        metrics = pd.DataFrame(
            {
                "channel": ch_names_pick,
                "excess_kurtosis": k_values,
                "kurtosis_z": z_scores,
                "bad_by_kurtosis": [ch in bad_k_auto for ch in ch_names_pick],
                "interpolated": False,
            }
        )

        if bad_k_auto:
            log_func(
                f"Bad by Kurtosis for {filename_for_log}: "
                f"{bad_k_auto} (Count: {len(bad_k_auto)})"
            )
        else:
            log_func(f"No channels bad by Kurtosis for {filename_for_log}.")

        if debug_enabled:
            print(
                f"[KURTOSIS] {filename_for_log}: "
                f"n_bad={len(bad_k_auto)} bad_chs={bad_k_auto}"
            )
    else:
        log_func(
            f"Skip Kurtosis for {filename_for_log} "
            f"(< 2 good EEG channels; n_picks={len(eeg_picks)})."
        )
        if debug_enabled:
            print(
                f"[KURTOSIS] {filename_for_log}: skip "
                f"(n_eeg_picks={len(eeg_picks)})"
            )

    new_bads = [b for b in bad_k_auto if b not in raw.info["bads"]]
    if new_bads:
        raw.info["bads"].extend(new_bads)

    interpolation_success = False
    if raw.info["bads"] and raw.get_montage():
        try:
            interp_targets = list(raw.info["bads"])
            log_func(f"Interpolating bads in {filename_for_log}: {interp_targets}")
            if debug_enabled:
                print(
                    f"[INTERP] {filename_for_log}: "
                    f"interpolated_chs={interp_targets}"
                )
            raw.interpolate_bads(
                reset_bads=True,
                mode="accurate",
                verbose=False,
            )
            interpolation_success = True
            log_func(f"Interpolation OK for {filename_for_log}.")
        except Exception as exc:
            log_func(f"Warn: Interpolation failed for {filename_for_log}: {exc}")
            if debug_enabled:
                print(
                    f"[INTERP] {filename_for_log}: FAILED "
                    f"bads={raw.info.get('bads', [])}"
                )
    elif raw.info["bads"]:
        log_func(
            f"Warn: No montage for {filename_for_log}, cannot interpolate. "
            f"Bads remain: {raw.info['bads']}"
        )
        if debug_enabled:
            print(
                f"[INTERP] {filename_for_log}: no montage; "
                f"bads={raw.info['bads']}"
            )
    else:
        log_func(f"No bads to interpolate in {filename_for_log}.")
        if debug_enabled:
            print(f"[INTERP] {filename_for_log}: no bads")

    if not metrics.empty and interpolation_success:
        metrics.loc[metrics["bad_by_kurtosis"], "interpolated"] = True

    metrics.to_csv(output_folder / "bad_channel_metrics.csv", index=False)

    return metrics
