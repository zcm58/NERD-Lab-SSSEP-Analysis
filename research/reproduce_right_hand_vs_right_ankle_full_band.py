"""Reproduce the full 25–27 Hz analysis: Think right hand versus think right ankle without importing the SSSEP application.

Run this file in PyCharm with the project's Python 3.13 environment. With no
arguments it asks for the original BDF folder and a parent results folder.
Every run creates a new results folder and preserves earlier outputs.

Dependencies: mne==1.9.0, numpy==2.3.1, scipy==1.16.0,
matplotlib==3.10.3, pandas==2.3.0. No other project files are required.

Both FFT methods are exported: time-average trials before FFT (canonical),
and FFT each trial then average amplitudes (diagnostic). Primary response:
mean amplitude over all 11 saved bins from 25 through 27 Hz, raw and minus
outside-band background from
23–24.4 and 27.6–29 Hz. Negative corrected amplitudes remain signed.
Statistics are participant-paired, two-sided and uncorrected. Historical
fixed/matched-peak analyses are separate outputs, not the pooled primary result.

Find the full-band diagnostic comparison in paired_statistics_uncorrected.csv:
method=phase_insensitive, metric=pooled_raw_amplitude_uv,
comparison=Spatial interaction. Its p-value is uncorrected for multiple tests.
This file is separate from the two-bin 25.4/26.4 Hz reproduction.

Optional: --cache full_task_spectra.npz --output PATH skips BDF processing.
A full cache created by either script can be reused by both scripts. --help
lists optional numerical verification flags. See research/README.md for use.
"""
from __future__ import annotations

# Optional settings for right-click Run. Leave None to use folder selection.
# For example: BDF_FOLDER = r"D:/EEG/BDF"
BDF_FOLDER = None
CACHE_FILE = None
OUTPUT_PARENT = None
REFERENCE_CSV = None
WORKERS = 3

# Analysis settings and ROI definitions are frozen for this reproduction.
CONFIG = {'name': 'right_hand_vs_right_ankle_full_band',
 'slug': 'right_hand_vs_right_ankle_full_band',
 'title': 'Think right hand versus think right ankle',
 'codes': (21, 22),
 'condition_labels': ['Think right hand', 'Think right ankle'],
 'rois': {'Hand_left': ['C1', 'C3', 'C5', 'CP1', 'CP3', 'CP5'],
          'Ankle_vertex': ['FCz', 'Cz', 'CPz'],
          'Right_control': ['C2', 'C4', 'C6', 'CP2', 'CP4', 'CP6'],
          'Narrow_hand': ['FC3', 'C3', 'CP3'],
          'Narrow_vertex': ['Cz']},
 'primary_rois': ['Hand_left', 'Ankle_vertex'],
 'interaction_weights': {'Hand_left': 1, 'Ankle_vertex': -1},
 'historical_interactions': {'Hand_minus_right_interaction': {'Hand_left': 1, 'Right_control': -1},
                             'Narrow_topographic_interaction': {'Narrow_hand': 1, 'Narrow_vertex': -1}},
 'roi_display_names': {'Hand_left': 'Left lateral hand-area scalp',
                       'Ankle_vertex': 'Top-midline ankle/foot scalp',
                       'Right_control': 'Right central comparison'},
 'marker_label': 'Ankle TENS: nominal 26 Hz',
 'frequency_note': 'The user confirmed that the former left-hand unit stayed at 26 Hz when moved to the '
                   'right ankle. The right-hand frequency is unknown; actual pulse rates were not '
                   'measured. Hand attention is expected over left-central scalp and ankle attention '
                   'nearer the vertex.'}

# BEGIN EMBEDDED RECORDING METHOD
"""Embeddable standalone raw SSSEP processing; no application imports or writes.

This is the fixed fpvs_amplitude_epoch_crop_c4_interp_v3 recording method.
The caller owns file discovery, output folders, analysis and the __main__ guard.
Call process_recording(path, codes) directly, or process_recordings(paths, codes)
from inside a Windows-safe ``if __name__ == '__main__':`` entry point.
"""

# Keep these assignments before importing NumPy/SciPy/MNE in each final script.
import os
for _thread_variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_thread_variable] = "1"

import ast
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import re
import warnings

import mne
import numpy as np
import scipy
from scipy.stats import kurtosis

RAW_PROCESSING_METHOD = "fpvs_amplitude_epoch_crop_c4_interp_v3"
RAW_FPVS_REFERENCE_COMMIT = "185d803f0056daebee04e5f28cc6b554c47336ce"
RAW_PARAMETERS = {
    "montage_name": "biosemi64", "scalp_channel_count": 64,
    "reference_channels": ("EXG1", "EXG2"), "stim_channel": "Status",
    "filter_highpass_hz": 0.1, "filter_lowpass_hz": 50.0,
    "fir_base_length": 8449, "target_sample_rate_hz": 256.0,
    "kurtosis_reject_z": 5.0, "kurtosis_trim_proportion": 0.10,
    "forced_bad_channels": ("C4",), "epoch_seconds": 6.0,
    "crop_start_seconds": 1.0, "crop_end_seconds": 0.0,
    "expected_epochs_per_code": 30,
}


def _raw_load(path):
    """First64 original channels plus EXG1/2 and Status, in recording order."""
    header = mne.io.read_raw_bdf(str(path), preload=False, stim_channel="Status", verbose=False)
    try:
        names = list(header.ch_names)
    finally:
        header.close()
    wanted = {name.casefold() for name in names[:64]}
    wanted.update(name.casefold() for name in ("EXG1", "EXG2", "Status"))
    include = [name for name in names if name.casefold() in wanted]
    return mne.io.read_raw_bdf(str(path), preload=True, stim_channel="Status",
                               include=include, verbose=False)


def _raw_channel_setup(raw, name, log, quality):
    if len(raw.ch_names) < 64:
        raise RuntimeError(f"{name}: expected at least64 loaded channels, found{len(raw.ch_names)}.")
    scalp = list(raw.ch_names[:64])
    present = {ch.casefold(): ch for ch in raw.ch_names}
    refs = {present[ch.casefold()] for ch in ("EXG1", "EXG2") if ch.casefold() in present}
    exg = {present[f"exg{i}"] for i in range(1, 9) if f"exg{i}" in present}
    to_misc, to_eeg = {ch: "misc" for ch in exg - refs}, {ch: "eeg" for ch in refs}
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r"The unit for channel\(s\) .* has changed from .* to .*\.", category=RuntimeWarning)
            if to_misc:
                raw.set_channel_types(to_misc)
            if to_eeg:
                raw.set_channel_types(to_eeg)
            if "status" in present:
                raw.set_channel_types({present["status"]: "stim"})
        quality["channel_typing_applied"] = True
        log(f"EXG typing: EEG references={sorted(refs)}; misc={sorted(to_misc)}.")
    except Exception as exc:
        quality["channel_typing_applied"] = False
        log(f"Warning: EXG/stim typing adjustment failed: {exc}")
    try:
        montage = mne.channels.make_standard_montage("biosemi64")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            raw.set_montage(montage, on_missing="warn", match_case=False, verbose=False)
        for warning in caught:
            match = re.search(r"channels missing from the montage are:\s*(\[[^\]]*\])", str(warning.message))
            missing = set(ast.literal_eval(match.group(1))) if match else set()
            if missing and missing.issubset(("EXG1", "EXG2")):
                continue
            log(f"Warning: Montage: {warning.message}")
        quality["montage_applied"] = True
        log("Applied biosemi64 montage for scalp electrode positions.")
    except Exception as exc:
        quality["montage_applied"] = False
        log(f"Warning: Montage error: {exc}")
    quality["initial_reference_applied"] = False
    if all(ch in raw.ch_names for ch in ("EXG1", "EXG2")):
        try:
            types = dict(zip(raw.ch_names, raw.get_channel_types()))
            to_eeg = {ch: "eeg" for ch in ("EXG1", "EXG2") if types[ch] != "eeg"}
            if to_eeg:
                raw.set_channel_types(to_eeg)
            raw.set_eeg_reference(ref_channels=["EXG1", "EXG2"], projection=False, verbose=False)
            quality["initial_reference_applied"] = True
            log("Applied EXG1/EXG2 initial reference.")
        except Exception as exc:
            log(f"Warn: Initial reference failed for {name}: {exc}")
    else:
        log(f"Skip initial referencing for {name}: reference channels missing.")
    drop = [ch for ch in ("EXG1", "EXG2") if ch in raw.ch_names]
    if drop:
        raw.drop_channels(drop)
    keep = [ch for ch in scalp if ch in raw.ch_names]
    if "Status" in raw.ch_names and "Status" not in keep:
        keep.append("Status")
    raw.pick_channels(keep, ordered=False)
    log(f"Kept{len(raw.ch_names)}channels; Status present={'Status' in raw.ch_names}.")


def _raw_filter_and_resample(raw, name, log, quality):
    sf = float(raw.info["sfreq"])
    length = 8449
    if sf > 256.0:
        length = int(round((8449 - 1) * (sf / 256.0))) + 1
        if length % 2 == 0:
            length += 1
        length = max(8449, length)
    quality["fir_filter_length"] = length
    preserve = {}
    quality["filter_applied"] = False
    try:
        raw.filter(0.1, 50.0, method="fir", phase="zero-double", fir_window="hamming",
                   fir_design="firwin", l_trans_bandwidth=0.1, h_trans_bandwidth=0.1,
                   filter_length=length, skip_by_annotation="edge", verbose=False)
        if raw.info.get("highpass") is not None:
            preserve["highpass"] = float(raw.info["highpass"])
        if raw.info.get("lowpass") is not None:
            preserve["lowpass"] = float(raw.info["lowpass"])
        quality["filter_applied"] = True
        log(f"Filter OK for{name}; original sfreq={sf:g}, FIR length={length}.")
    except Exception as exc:
        log(f"Warn: Filter failed for{name}: {exc}")
    quality["resample_applied_or_unneeded"] = sf <= 256.0
    if sf > 256.0:
        try:
            raw.resample(256.0, npad="auto", window="hann", verbose=False)
            if preserve:
                try:
                    with raw.info._unlock():
                        for key, value in preserve.items():
                            raw.info[key] = value
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    log(f"Warn: Could not restore filter metadata for{name}.")
            quality["resample_applied_or_unneeded"] = True
            log(f"Resampled{name}to{float(raw.info['sfreq']):g}Hz.")
        except Exception as exc:
            log(f"Warn: Resampling failed for{name}: {exc}")
    else:
        log(f"No downsampling needed for{name}(sfreq={sf:g}).")


def _raw_bad_channels(raw, name, log, quality):
    eeg_names = {raw.ch_names[i].casefold(): raw.ch_names[i]
                 for i in mne.pick_types(raw.info, eeg=True, stim=False, exclude=[])}
    policy = [eeg_names["c4"]] if "c4" in eeg_names else []
    if not policy:
        log(f"Warn: Policy electrode'C4'is not an EEG channel in{name}; it cannot be interpolated.")
    raw.info["bads"].extend(ch for ch in policy if ch not in raw.info["bads"])
    log(f"Bad by policy for{name}: {policy}")
    picks = mne.pick_types(raw.info, eeg=True, stim=False, exclude=raw.info["bads"])
    automatic, metrics = [], []
    if len(picks) >= 2:
        values = kurtosis(raw.get_data(picks=picks), axis=1, fisher=True, bias=False)
        values = np.nan_to_num(values, copy=False)
        count = len(values)
        trim = int(np.floor(count * 0.10))
        z = np.full(count, np.nan, dtype=float)
        if count - 2 * trim > 1:
            ordered = np.sort(values)
            trimmed = ordered[trim:count - trim]
            mean, std = float(np.mean(trimmed)), float(np.std(trimmed))
            log(f"Trimmed kurtosis for{name}: Mean={mean:.3f}, Std={std:.3f}, N={len(trimmed)}.")
            if std > 1e-9:
                z = (values - mean) / std
                bad_indices = np.where(np.abs(z) > 5.0)[0]
                picked_names = [raw.info["ch_names"][i] for i in picks]
                automatic = [picked_names[i] for i in bad_indices]
            else:
                log(f"Kurtosis Trimmed Std Dev near zero for{name}.")
        else:
            log(f"Not enough data for kurtosis trimmed stats in{name}.")
        for ch, value, score in zip((raw.ch_names[i] for i in picks), values, z):
            metrics.append({"channel": ch, "excess_kurtosis": float(value),
                            "kurtosis_z": float(score) if np.isfinite(score) else None,
                            "bad_by_kurtosis": ch in automatic, "bad_by_policy": False,
                            "interpolated": False})
    else:
        log(f"Skip Kurtosis for{name}(<2 good EEG channels;n_picks={len(picks)}).")
    log(f"Bad by Kurtosis for{name}: {automatic}")
    for ch in policy:
        metrics.append({"channel": ch, "excess_kurtosis": None, "kurtosis_z": None,
                        "bad_by_kurtosis": False, "bad_by_policy": True, "interpolated": False})
    raw.info["bads"].extend(ch for ch in automatic if ch not in raw.info["bads"])
    targets = list(raw.info["bads"])
    interpolation_ok = False
    if targets and raw.get_montage():
        try:
            raw.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)
            interpolation_ok = True
            log(f"Interpolation OK for{name}: {targets}")
        except Exception as exc:
            raw.info["bads"] = list(dict.fromkeys([*raw.info["bads"], *targets]))
            log(f"Warn: Interpolation failed for{name}: {exc}")
    elif targets:
        log(f"Warn: No montage for{name}; cannot interpolate. Bads remain:{raw.info['bads']}")
    else:
        log(f"No bads to interpolate in{name}.")
    if interpolation_ok:
        for row in metrics:
            row["interpolated"] = row["channel"] in targets
    quality.update({"forced_bad_channels": policy, "automatic_bad_channels": automatic,
                    "interpolation_targets": targets, "interpolation_succeeded": interpolation_ok,
                    "unresolved_bad_channels": list(raw.info["bads"])})
    return metrics


def _raw_final_reference(raw, name, log, quality):
    quality["final_average_reference_applied"] = False
    try:
        picks = mne.pick_types(raw.info, eeg=True, exclude=raw.info["bads"])
        if len(picks):
            raw.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
            raw.apply_proj(verbose=False)
            quality["final_average_reference_applied"] = True
            log(f"Average reference applied to{name}.")
        else:
            log(f"Skip average ref for{name}: No good EEG channels.")
    except Exception as exc:
        log(f"Warn: Average reference failed for{name}: {exc}")


def _raw_status_events(raw, log, quality):
    try:
        events = mne.find_events(raw, stim_channel="Status", shortest_event=1, verbose=False)
        quality["event_source"] = "Status"
    except Exception:
        events, _ = mne.events_from_annotations(raw, verbose=False)
        quality["event_source"] = "MNE default annotation mapping"
        log("Status event detection failed; using annotation events as in FPVS.")
    if len(events) == 0:
        raise RuntimeError("No trigger events found in Status.")
    quality["found_trigger_codes"] = sorted(np.unique(events[:, 2]).astype(int).tolist())
    log(f"Found trigger codes:{quality['found_trigger_codes']};100is an epoch-end delimiter, not a baseline FFT.")
    return events


def _raw_complete_epochs(raw, events, code, channels):
    sfreq = float(raw.info["sfreq"])
    samples = int(round(6.0 * sfreq))
    extracted, kept = [], []
    selected = events[events[:, 2] == code]
    skipped = 0
    for event in selected:
        start = int(event[0]) - raw.first_samp
        stop = start + samples
        if start < 0 or stop > raw.n_times:
            skipped += 1
            continue
        extracted.append(raw.get_data(start=start, stop=stop))
        kept.append(event)
    if not extracted:
        return np.empty((0, len(channels), samples)), len(selected), skipped
    # Default EpochsArray projection is deliberate, even after raw.apply_proj.
    epochs = mne.EpochsArray(np.stack(extracted, axis=0), raw.info.copy(),
                            events=np.asarray(kept, dtype=int), event_id={str(code): code},
                            tmin=0.0, baseline=None, verbose=False)
    epochs = epochs.pick("eeg", exclude="bads").pick(channels).get_data()
    return epochs, len(selected), skipped


def process_recording(path, codes):
    """Return this recording's full per-electrode spectra; never write files.

    Reproduction requires64 repaired BioSemi channels,256Hz,30 complete6s
    epochs for every requested code and the final1280samples after1s cropping.
    Logged FPVS warning/continue paths run before the strict method check stops
    an incompatible recording; it is never silently published as matching v3.
    """
    path = Path(path)
    codes = tuple(codes)
    if not codes or len(set(codes)) != len(codes) or any(type(c) is not int or c not in (11, 12, 21, 22) for c in codes):
        raise ValueError("codes must be unique integers selected from11,12,21,22.")
    logs, quality = [], {}
    quality["versions"] = {"mne": mne.__version__, "numpy": np.__version__, "scipy": scipy.__version__}
    raw = _raw_load(path)
    original_sfreq = float(raw.info["sfreq"])
    try:
        _raw_channel_setup(raw, path.name, logs.append, quality)
        _raw_filter_and_resample(raw, path.name, logs.append, quality)
        metrics = _raw_bad_channels(raw, path.name, logs.append, quality)
        _raw_final_reference(raw, path.name, logs.append, quality)
        events = _raw_status_events(raw, logs.append, quality)
        picks = mne.pick_types(raw.info, eeg=True, exclude="bads")
        channels = [raw.ch_names[i] for i in picks]
        standard = mne.channels.make_standard_montage("biosemi64").ch_names
        if len(channels) == len(standard) and set(channels) == set(standard):
            channels = standard
        required_flags = ("channel_typing_applied", "montage_applied", "initial_reference_applied",
                          "filter_applied", "resample_applied_or_unneeded", "interpolation_succeeded",
                          "final_average_reference_applied")
        mismatch = [key for key in required_flags if not quality.get(key)]
        if float(raw.info["sfreq"]) != 256.0:
            mismatch.append("sampling_rate_not_256Hz")
        if len(channels) != 64 or set(channels) != set(standard):
            mismatch.append("complete_recognized_biosemi64_channels_required")
        if quality["forced_bad_channels"] != ["C4"] or quality["unresolved_bad_channels"]:
            mismatch.append("mandatory_C4_reconstruction_or_bad_channel_resolution_failed")
        if mismatch:
            raise RuntimeError(f"{path.name}: reproduction method mismatch:{mismatch}.\n" + "\n".join(logs))
        quality["method_match"] = True
        coherent, phase, counts = [], [], {}
        for code in codes:
            epochs, onset_count, skipped = _raw_complete_epochs(raw, events, code, channels)
            counts[int(code)] = int(len(epochs))
            if onset_count != 30 or len(epochs) != 30 or skipped:
                raise RuntimeError(f"{path.name}: trigger{code}requires30 complete epochs; found{onset_count}onsets,{len(epochs)}complete,{skipped}out of bounds.")
            cropped = epochs[..., int(round(1.0 * float(raw.info["sfreq"]))):]
            if cropped.shape != (30, 64, 1280) or not np.isfinite(cropped).all():
                raise RuntimeError(f"{path.name}: trigger{code}does not contain finite30x64x1280FFT input.")
            averaged = np.mean(cropped.astype(np.float64), axis=0)
            averaged_uv = averaged * 1e6
            n = averaged.shape[1]
            bins = n // 2 + 1
            fft = np.fft.fft(averaged_uv, axis=1)
            coherent.append(np.abs(fft[:, :bins]) / n * 2)
            trial_complex = np.fft.fft(cropped.astype(np.float64) * 1e6, axis=-1)[..., :bins] / n * 2
            phase.append(np.mean(np.abs(trial_complex), axis=0, dtype=np.float64))
            logs.append(f"Trigger{code}:30 complete6s epochs; retained5s/1280samples;641FFTbins.")
        frequencies = np.fft.rfftfreq(1280, d=1.0 / 256.0)
        quality["protocol_onset_counts"] = {int(c): int(np.count_nonzero(events[:, 2] == c)) for c in (11, 12, 21, 22)}
        quality["usable_epochs_by_code"] = counts
        quality["warnings"] = [line for line in logs if any(text in line.lower() for text in ("warn", "failed", "skip"))]
        return {"participant_id": path.stem, "source_bdf": str(path.resolve()),
                "processing_method": RAW_PROCESSING_METHOD, "fpvs_reference_commit": RAW_FPVS_REFERENCE_COMMIT,
                "trigger_codes": np.asarray(codes, dtype=int), "channel_names": tuple(channels),
                "frequencies_hz": frequencies, "coherent_amplitude_uv": np.stack(coherent),
                "phase_insensitive_amplitude_uv": np.stack(phase),
                "original_sampling_rate_hz": original_sfreq, "sampling_rate_hz": 256.0,
                "epoch_window_sec": 6.0, "fft_crop_start_sec": 1.0, "fft_crop_end_sec": 0.0,
                "analysis_window_sec": 5.0, "fft_sample_count": 1280,
                "usable_epochs_by_code": counts, "bad_channel_metrics": metrics,
                "logs": logs, "quality": quality}
    finally:
        raw.close()


def _raw_process_job(job):
    return process_recording(*job)


def process_recordings(paths, codes, workers=3):
    """File-level parallelism only; call from the final script's __main__ guard."""
    paths = [Path(path) for path in paths]
    if not paths:
        raise ValueError("No BDF recordings were supplied.")
    if type(workers) is not int or not 1 <= workers <= 3:
        raise ValueError("Use one to three file workers.")
    jobs = [(str(path), tuple(codes)) for path in paths]
    if workers == 1:
        return [_raw_process_job(job) for job in jobs]
    results = {}
    with ProcessPoolExecutor(max_workers=min(workers, len(paths))) as pool:
        futures = {pool.submit(_raw_process_job, job): i for i, job in enumerate(jobs)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [results[i] for i in range(len(paths))]

# END EMBEDDED RECORDING METHOD

"""Self-contained analysis/output functions to embed in either reproduction script.

Public interface: analyze_and_export(dataset, config, output_dir).
dataset is an NPZ-like mapping with participant_ids, trigger_codes, channel_names,
frequencies_hz and coherent_amplitude_uv / phase_insensitive_amplitude_uv arrays
shaped participant x two cues x electrode x frequency.
"""
from pathlib import Path
import json
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from scipy import stats


def _paired_summary(difference):
    difference = np.asarray(difference, dtype=float)
    n = len(difference)
    mean, sd = float(difference.mean()), float(difference.std(ddof=1))
    se = sd / np.sqrt(n)
    margin = float(stats.t.ppf(.975, n - 1) * se)
    if sd:
        t, p = stats.ttest_1samp(difference, 0)
        dz = mean / sd
    else:
        t, p, dz = (0., 1., 0.) if mean == 0 else (None, 0., None)
    if np.all(difference == 0):
        w_statistic, w_p = 0., 1.
    else:
        w_statistic, w_p = stats.wilcoxon(difference, alternative="two-sided", method="auto")
    return {"N": n, "df": n-1, "mean_change_uv": mean, "sd_change_uv": sd,
            "ci95_low_uv": mean-margin, "ci95_high_uv": mean+margin,
            "t_statistic": None if t is None else float(t),
            "p_uncorrected_two_sided": float(p), "paired_dz": dz,
            "wilcoxon_statistic": float(w_statistic), "wilcoxon_p_uncorrected": float(w_p),
            "positive_participants": int(np.count_nonzero(difference > 0))}


def _mean_interval(values):
    values = np.asarray(values, dtype=float)
    mean = float(values.mean())
    error = float(stats.t.ppf(.975, len(values)-1) * stats.sem(values))
    return mean, error


def _write_json(path, value):
    def clean(x):
        if isinstance(x, Path):
            return str(x)
        if isinstance(x, dict):
            return {str(k): clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple, np.ndarray)):
            return [clean(v) for v in x]
        if isinstance(x, (np.integer,)):
            return int(x)
        if isinstance(x, (float, np.floating)):
            return float(x) if np.isfinite(x) else None
        return x
    Path(path).write_text(json.dumps(clean(value), indent=2, allow_nan=False), encoding="utf-8")


def analyze_and_export(dataset, config, output_dir):
    """Export frozen pooled-band analyses, old peak checks and scientific PNGs.

    Required config: name, title, condition_labels[2], rois{name:[electrodes]},
    primary_rois[2], interaction_weights{ROI:coefficient}, marker_label,
    frequency_note. Optional: provenance, roi_display_names,
    historical_interactions{label:{ROI:coefficient}} for earlier sensitivities.
    All differences are condition0-condition1; p values and95%t intervals are
    uncorrected. Primary averaging is amplitude, never power or an SNR ratio.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ids = np.asarray(dataset["participant_ids"]).astype(str)
    codes = np.asarray(dataset["trigger_codes"], dtype=int)
    channels = np.asarray(dataset["channel_names"]).astype(str).tolist()
    frequency = np.asarray(dataset["frequencies_hz"], dtype=float)
    n = len(ids)
    assert n >= 2 and len(set(ids)) == n and len(codes) == 2
    assert len(channels) == len(set(channels)) and np.all(np.diff(frequency) > 0)
    methods = {"coherent": np.asarray(dataset["coherent_amplitude_uv"], dtype=float),
               "phase_insensitive": np.asarray(dataset["phase_insensitive_amplitude_uv"], dtype=float)}
    method_names = {"coherent":"FFT after averaging trials (current method)",
                    "phase_insensitive":"Average single-trial FFT amplitude (diagnostic)"}
    for value in methods.values():
        assert value.shape == (n, 2, len(channels), len(frequency))
        assert np.isfinite(value).all() and (value >= 0).all()
    primary = list(config["primary_rois"])
    assert len(primary) == 2 and len(set(primary)) == 2
    rois = config["rois"]
    display = {r:config.get("roi_display_names",{}).get(r,r.replace("_"," ")) for r in rois}
    assert set(primary) <= set(rois)
    weights = config["interaction_weights"]
    assert set(weights) <= set(rois)
    historical_interactions = config.get("historical_interactions", {})
    assert all(set(w) <= set(rois) for w in historical_interactions.values())
    picks = {}
    for roi, wanted in rois.items():
        missing = [ch for ch in wanted if ch not in channels]
        if missing:
            raise ValueError(f"ROI {roi!r} requires missing electrodes: {missing}")
        assert wanted and len(set(wanted)) == len(wanted)
        picks[roi] = [channels.index(ch) for ch in wanted]
    tol = 1e-9
    signal = (frequency >= 25-tol) & (frequency <= 27+tol)
    background = (((frequency >= 23-tol) & (frequency <= 24.4+tol)) |
                  ((frequency >= 27.6-tol) & (frequency <= 29+tol)))
    if signal.sum() != 11 or background.sum() != 16:
        raise ValueError("This frozen analysis requires all 11 signal bins at 25–27 Hz and 16 background bins at 23–24.4/27.6–29 Hz.")
    assert not np.any(signal & background)
    np.testing.assert_allclose(frequency[signal], np.arange(25, 27.01, .2), rtol=0, atol=tol)
    roi_spectra = {m:{r:v[:,:,idx,:].mean(axis=2) for r,idx in picks.items()} for m,v in methods.items()}
    channel_metrics, roi_metrics = {}, {}
    records, participant_records = [], []
    metrics = ("pooled_raw_amplitude_uv", "background_corrected_amplitude_uv")
    for method, values in methods.items():
        raw = values[...,signal].mean(axis=-1)
        bg = values[...,background].mean(axis=-1)
        channel_metrics[method] = {metrics[0]:raw, "background_mean_amplitude_uv":bg, metrics[1]:raw-bg}
        # Preserve signed background subtraction, including negative estimates.
        np.testing.assert_array_equal(channel_metrics[method][metrics[1]], raw-bg)
        roi_metrics[method] = {metric:{r:a[:,:,idx].mean(axis=2) for r,idx in picks.items()}
                               for metric,a in channel_metrics[method].items()}
        for roi in rois:
            for pi,pid in enumerate(ids):
                for ci,code in enumerate(codes):
                    participant_records.append({"method":method,"participant_id":pid,"roi":roi,
                        "trigger_code":int(code),"condition":config["condition_labels"][ci],
                        **{metric:float(roi_metrics[method][metric][roi][pi,ci]) for metric in channel_metrics[method]}})
        for metric in metrics:
            for roi, values in roi_metrics[method][metric].items():
                records.append({"method":method,"metric":metric,"comparison":roi,"role":"roi_cue_change",
                    "condition0_mean_uv":float(values[:,0].mean()),"condition1_mean_uv":float(values[:,1].mean()),
                    **_paired_summary(values[:,0]-values[:,1])})
            interaction = sum(float(w)*(roi_metrics[method][metric][r][:,0]-roi_metrics[method][metric][r][:,1])
                              for r,w in weights.items())
            records.append({"method":method,"metric":metric,"comparison":"Spatial interaction","role":"spatial_interaction",
                            "condition0_mean_uv":None,"condition1_mean_uv":None,**_paired_summary(interaction)})
    frame_stats = pd.DataFrame(records)
    frame_stats.to_csv(out/"paired_statistics_uncorrected.csv", index=False)
    pd.DataFrame(participant_records).to_csv(out/"participant_pooled_values.csv", index=False)

    # Historical peak analyses are separate from the newly frozen pooled metric.
    near = np.flatnonzero(signal)
    pooled = sum(roi_spectra["phase_insensitive"][r] for r in primary)/2
    matched_indices = near[np.argmax(pooled.mean(axis=1)[:,near], axis=1)]
    selections = {"participant_matched_peak":matched_indices}
    for hz in (25.4, 26., 26.4):
        index = np.flatnonzero(np.isclose(frequency, hz, rtol=0, atol=tol))
        if len(index) != 1:
            raise ValueError(f"Historical frequency {hz:g}Hz is unavailable on the source grid.")
        selections[f"fixed_{hz:g}_Hz"] = np.full(n, index[0])
    historical_values, historical_stats = [], []
    for method in methods:
        for selection, indices in selections.items():
            selected_roi = {r:np.stack([a[pi,:,indices[pi]] for pi in range(n)]) for r,a in roi_spectra[method].items()}
            for roi, values in selected_roi.items():
                historical_stats.append({"method":method,"selection":selection,"comparison":roi,"role":"roi_cue_change",
                    "condition0_mean_uv":float(values[:,0].mean()),"condition1_mean_uv":float(values[:,1].mean()),
                    **_paired_summary(values[:,0]-values[:,1])})
                for pi,pid in enumerate(ids):
                    historical_values.append({"method":method,"selection":selection,"participant_id":pid,"roi":roi,
                        "frequency_hz":float(frequency[indices[pi]]),"condition0_amplitude_uv":float(values[pi,0]),
                        "condition1_amplitude_uv":float(values[pi,1])})
            interaction = sum(float(w)*(selected_roi[r][:,0]-selected_roi[r][:,1]) for r,w in weights.items())
            historical_stats.append({"method":method,"selection":selection,"comparison":"Spatial interaction","role":"spatial_interaction",
                "condition0_mean_uv":None,"condition1_mean_uv":None,**_paired_summary(interaction)})
            for label, old_weights in historical_interactions.items():
                difference = sum(float(w)*(selected_roi[r][:,0]-selected_roi[r][:,1]) for r,w in old_weights.items())
                historical_stats.append({"method":method,"selection":selection,"comparison":label,"role":"historical_spatial_sensitivity",
                    "condition0_mean_uv":None,"condition1_mean_uv":None,**_paired_summary(difference)})
    pd.DataFrame(historical_values).to_csv(out/"historical_peak_values.csv", index=False)
    pd.DataFrame(historical_stats).to_csv(out/"historical_peak_statistics_uncorrected.csv", index=False)

    colors = ("#2458a6", "#c45a12")
    figures, omitted, map_metadata = [], [], {}
    for lower,upper in ((3,40),(24,30)):
        fig,axes = plt.subplots(2,2,figsize=(12,8),sharex=True,sharey="row")
        visible = (frequency >= lower-tol) & (frequency <= upper+tol)
        for row, method in enumerate(methods):
            maximum = max(float(roi_spectra[method][r].mean(axis=0)[:,visible].max()) for r in primary)
            for col,roi in enumerate(primary):
                ax = axes[row,col]
                ax.axvspan(25,27,color="#e4c36e",alpha=.30,zorder=0)
                for a,b in ((23,24.4),(27.6,29)):
                    ax.axvspan(a,b,color="#8c949f",alpha=.18,zorder=0)
                for ci in range(2):
                    ax.plot(frequency[visible],roi_spectra[method][roi].mean(axis=0)[ci,visible],
                            color=colors[ci],ls="-" if ci==0 else "--",lw=1.5)
                ax.axvline(26,color="#68595c",ls=":",lw=1)
                ax.set(xlim=(lower,upper),ylim=(0,maximum*1.08),title=display[roi] if row==0 else "")
                if col==0:
                    ax.set_ylabel("FFT of trial mean (µV)" if row==0 else "Mean trial amplitude (µV)")
                if row==1:
                    ax.set_xlabel("Frequency (Hz)")
                ax.spines[["top","right"]].set_visible(False)
                ax.grid(axis="y",alpha=.15)
        fig.suptitle(config["title"]+f" (N={n})\nTop: current cue-averaged FFT · bottom: mean single-trial magnitude",fontsize=14,y=.985)
        handles = [Line2D([],[],color=colors[i],ls="-" if i==0 else "--",label=label) for i,label in enumerate(config["condition_labels"])]
        handles += [Line2D([],[],color="#d5ae4e",lw=8,alpha=.5,label="Signal: 25–27 Hz (11 bins)"),
                    Line2D([],[],color="#8c949f",lw=8,alpha=.4,label="Background: 23–24.4, 27.6–29 Hz (16 bins)"),
                    Line2D([],[],color="#68595c",ls=":",label=config["marker_label"])]
        fig.legend(handles=handles,loc="upper center",bbox_to_anchor=(.5,.91),ncol=3,frameon=False,fontsize=9)
        fig.subplots_adjust(left=.085,right=.98,top=.77,bottom=.18,hspace=.16,wspace=.12)
        fig.text(.5,.025,"Raw spectra; shaded bands define pooled means. Background correction subtracts the outside-band mean, retaining negative values.\n"
                 +textwrap.fill(config["frequency_note"],125)+"\nC4 is interpolated; diagnostic magnitudes include non-phase-locked signal and noise.",
                 ha="center",va="bottom",fontsize=9)
        filename = f"spectra_{lower}_{upper}Hz.png"
        fig.savefig(out/filename,dpi=180); plt.close(fig); figures.append(filename)

    for method in methods:
        fig,axes = plt.subplots(2,3,figsize=(14,8.5))
        for row,metric in enumerate(metrics):
            all_primary = np.concatenate([roi_metrics[method][metric][r].ravel() for r in primary])
            low = min(0.,float(all_primary.min()))
            high = float(all_primary.max())
            pad = max((high-low)*.15, 1e-5)
            for col,roi in enumerate(primary):
                ax,values = axes[row,col],roi_metrics[method][metric][roi]
                jitter = np.linspace(-.06,.06,n)
                for pi in range(n):
                    ax.plot(np.array([0.,1.])+jitter[pi],values[pi],color="#bcc4ce",lw=.6,alpha=.65,zorder=1)
                for ci in range(2):
                    ax.scatter(np.full(n,ci)+jitter,values[:,ci],color=colors[ci],s=17,alpha=.7,zorder=2)
                    mean,error = _mean_interval(values[:,ci])
                    ax.errorbar(ci,mean,yerr=error,fmt="D",mfc="white",mec="#18212d",ecolor="#18212d",capsize=5,zorder=4)
                record = frame_stats[(frame_stats.method==method)&(frame_stats.metric==metric)&(frame_stats.comparison==roi)].iloc[0]
                ax.text(.03,.98,f"Cue difference = {record.mean_change_uv:+.4f} µV\nPaired t p = {record.p_uncorrected_two_sided:.4g} (uncorrected)",
                        transform=ax.transAxes,va="top",fontsize=9)
                ax.set(xticks=[0,1],xticklabels=[textwrap.fill(x,18) for x in config["condition_labels"]],
                       xlim=(-.25,1.25),ylim=(low-pad if low<0 else 0,high+2*pad),title=display[roi])
                ax.set_ylabel("Mean 25–27 Hz amplitude (µV)" if row==0 else "Background-corrected amplitude (µV)")
            ax = axes[row,2]
            difference = sum(float(w)*(roi_metrics[method][metric][r][:,0]-roi_metrics[method][metric][r][:,1]) for r,w in weights.items())
            summary = _paired_summary(difference)
            ax.scatter(np.linspace(-.10,.10,n),np.sort(difference),color="#65758b",s=20,alpha=.7)
            ax.errorbar(0,summary["mean_change_uv"],yerr=[[summary["mean_change_uv"]-summary["ci95_low_uv"]],
                          [summary["ci95_high_uv"]-summary["mean_change_uv"]]],fmt="D",color="#18212d",capsize=6,zorder=4)
            ax.axhline(0,color="#7a666a",ls=":")
            ax.set(xticks=[0],xticklabels=["Spatial interaction"],xlim=(-.5,.5),title="Difference between regional cue changes",
                   ylabel="Paired difference of changes (µV)")
            ax.text(.03,.98,f"Mean = {summary['mean_change_uv']:+.4f} µV\nPaired t p = {summary['p_uncorrected_two_sided']:.4g} (uncorrected)",
                    transform=ax.transAxes,va="top",fontsize=9)
            for ax in axes[row]:
                if row==1:
                    ax.axhline(0,color="#7a666a",ls=":",lw=.8)
                ax.spines[["top","right"]].set_visible(False)
                ax.grid(axis="y",alpha=.15)
        fig.suptitle(config["title"]+f" · {method_names[method]} (N={n})\nTop: pooled raw amplitude · bottom: pooled amplitude minus outside-band background",fontsize=13,y=.985)
        fig.subplots_adjust(left=.075,right=.98,top=.83,bottom=.20,hspace=.48,wspace=.30)
        interaction_text = "; ".join(f"{r}:{w:+g}" for r,w in weights.items())
        fig.text(.5,.025,"Lines connect participants; diamonds are means with 95% t intervals. All differences are first cue minus second cue.\n"
                 f"Interaction weights on regional cue changes: {interaction_text}. Interaction panels use their own signed y-axis.\n"
                 "All statistics/intervals are uncorrected. C4 is interpolated. Negative background-corrected estimates are retained.",ha="center",va="bottom",fontsize=9)
        filename = f"paired_pooled_{method}.png"
        fig.savefig(out/filename,dpi=180); plt.close(fig); figures.append(filename)

    if len(channels)==64:
        import mne
        from mne.channels.layout import _find_topomap_coords
        info = mne.create_info(channels,256,"eeg")
        try:
            info.set_montage(mne.channels.make_standard_montage("biosemi64"),match_case=False)
        except ValueError as exc:
            omitted.append(f"Scalp maps unavailable: {exc}")
        else:
            positions = _find_topomap_coords(info,np.arange(64))
            for method in methods:
                group = channel_metrics[method][metrics[1]].mean(axis=0)
                delta = (channel_metrics[method][metrics[1]][:,0]-channel_metrics[method][metrics[1]][:,1]).mean(axis=0)
                amp_limit,delta_limit = max(float(abs(group).max()),1e-12),max(float(abs(delta).max()),1e-12)
                fig,axes = plt.subplots(1,3,figsize=(13,5.6))
                images,titles = [],[]
                for ci,ax in enumerate(axes):
                    values,limit = (group[ci],amp_limit) if ci<2 else (delta,delta_limit)
                    im,_ = mne.viz.plot_topomap(values,info,axes=ax,show=False,vlim=(-limit,limit),cmap="RdBu_r",
                              image_interp="linear",extrapolate="head",contours=5,sensors=True)
                    images.append(im)
                    for ch in ("C3","C4","Cz"):
                        x,y = positions[channels.index(ch)]
                        ax.annotate(ch,(x,y),xytext=(0,6),textcoords="offset points",ha="center",fontsize=8,
                                    bbox={"facecolor":"white","alpha":.8,"edgecolor":"none","pad":.5})
                    ax.text(.01,.5,"L",transform=ax.transAxes,fontweight="bold")
                    ax.text(.98,.5,"R",transform=ax.transAxes,ha="right",fontweight="bold")
                    titles.append((ax,config["condition_labels"][ci] if ci<2 else "First cue − second cue"))
                fig.subplots_adjust(left=.025,right=.865,top=.78,bottom=.27,wspace=.14)
                for ax,label in titles:
                    pos=ax.get_position(); fig.text(pos.x0+pos.width/2,pos.y1+.025,label,ha="center",fontsize=11)
                fig.suptitle(config["title"]+f" · pooled background-corrected amplitude (N={n})\n"+method_names[method],fontsize=13,y=.98)
                cax1=fig.add_axes([.895,.52,.018,.23]); cax2=fig.add_axes([.895,.18,.018,.23])
                fig.colorbar(images[0],cax=cax1).set_label("Amplitude minus background (µV)",fontsize=9)
                fig.colorbar(images[2],cax=cax2).set_label("Cue difference (µV)",fontsize=9)
                fig.text(.5,.025,"Signal: mean 25–27 Hz; background: mean 23–24.4 plus 27.6–29 Hz. Signed subtraction; no power conversion or ratio.\n"
                         "Cue maps share one zero-centered scale; difference map has its own scale. Nose up, L/R label scalp sides.\n"
                         "C4 is interpolated. Descriptive scalp maps, not cortical source maps or electrode-level significance tests.",ha="center",fontsize=9)
                filename=f"pooled_background_corrected_scalp_{method}.png"
                fig.savefig(out/filename,dpi=180); plt.close(fig); figures.append(filename)
                map_metadata[method]={"condition_scale_uv":[-amp_limit,amp_limit],"difference_scale_uv":[-delta_limit,delta_limit],
                    "condition_channel_means_uv":group.tolist(),"difference_channel_means_uv":delta.tolist()}
    else:
        omitted.append("Scalp maps require all64BioSemi channels; spectra and ROI statistics remain available.")

    results = {"name":config["name"],"title":config["title"],"N":n,"participant_ids":ids.tolist(),"trigger_codes":codes.tolist(),
        "condition_labels":config["condition_labels"],"roi_channels":rois,"primary_rois":primary,"interaction_weights":weights,
        "historical_interactions":historical_interactions,
        "signal_bins_hz":frequency[signal].tolist(),"background_bins_hz":frequency[background].tolist(),
        "primary_metric":"Mean of all 11 signal-bin amplitudes at 25–27 Hz minus the mean of 16 background-bin amplitudes, per participant/cue/electrode then ROI mean; negative values retained.",
        "sum_equivalent":"Multiplying raw or corrected means by 11 yields the full-band amplitude sum or background-corrected sum, with identical paired statistics; no power or PSD conversion.",
        "statistics":"Two-sided participant-paired t tests, df=N-1; uncorrected95%t confidence intervals and paired dz. Wilcoxon signed-rank is secondary and uncorrected.",
        "matched_selection":"Historical only: one25–27Hz bin perparticipant chosen from equally weighted primary ROImeans, pooled bothcues, meantrialmagnitude; same bin used for bothmethods/allcells.",
        "historical_matched_frequencies_hz":frequency[matched_indices].tolist(),"paired_statistics":records,
        "historical_statistics":historical_stats,"figures":figures,"omitted_figures":omitted,"scalp_maps":map_metadata,
        "frequency_note":config["frequency_note"],"provenance":config.get("provenance",{}),
        "limits":["Full 25–27 Hz pooling is exploratory; statistics are uncorrected for multiple comparisons.",
                  "A nearby peak/band alone cannot identify its stimulator or establish a neural response.",
                  "Scalp ROIs are proxies, not cortical source localizers. C4 is reconstructed.",
                  "Meantrialmagnitudes include non-phase-locked EEG/noise; canonical trialmeans can cancel phase-inconsistent responses."]}
    _write_json(out/"analysis_results.json",results)
    lines=["# "+config["title"],"",f"N={n}; all p-values and95%confidence intervals are uncorrected.","",
        "Primary response: mean amplitude over all 11 bins from 25 through 27 Hz, inclusive. Background: mean amplitude over 23–24.4 and 27.6–29 Hz (16 bins). Subtract that background once; retain negative values. No power or ratio is calculated.","",
        config["frequency_note"],"","Differences below are first condition minus second: "+" versus ".join(config["condition_labels"])+".","",
        "| Method | Measure | Region/contrast | Change,µV |95%tCI | Uncorrected p | Wilcoxon p |",
        "|---|---|---|---:|---|---:|---:|"]
    for record in records:
        if record["comparison"] not in primary+["Spatial interaction"]:
            continue
        lines.append(f"|{record['method']}|{record['metric']}|{record['comparison']}|{record['mean_change_uv']:+.6f}|[{record['ci95_low_uv']:+.6f},{record['ci95_high_uv']:+.6f}]|{record['p_uncorrected_two_sided']:.6g}|{record['wilcoxon_p_uncorrected']:.6g}|")
    lines += ["","Interaction weights: "+json.dumps(weights)+". One region reaching a threshold while another does not is not evidence that their effects differ.","",
        "Historical25.4/26/26.4Hz and participant-matched peak checks are retained separately in historical_peak_values.csv and historical_peak_statistics_uncorrected.csv. They do not define the new pooled response.","",
        "Plots:",""]+[f"- [{name}]({name})" for name in figures]
    lines += ["","Interpretation limits: scalp maps do not establish cortical sources; stimulation artifact remains possible. Both methods are shown because averaging waveforms and averaging per-trial amplitudes answer different questions. No method change is made to the application."]
    if omitted:
        lines += ["","Unavailable plots: "+"; ".join(omitted)]
    (out/"RESULTS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return results

"""Driver embedded separately in each self-contained reproduction script."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import platform
import sys
import traceback


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat_snapshot(path):
    value = Path(path).stat()
    return {"size": value.st_size, "mtime_ns": value.st_mtime_ns}


def _choose_directory(title):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            chosen = filedialog.askdirectory(parent=root, title=title)
        finally:
            root.destroy()
    except Exception as exc:
        raise RuntimeError("Folder selection is unavailable; use --bdf-folder/--output or edit the settings at the top of this file.") from exc
    if not chosen:
        raise KeyboardInterrupt("Folder selection cancelled.")
    return Path(chosen).expanduser().resolve()


def _reject_project_data_path(path):
    """Keep new recordings/results outside this application's checkout."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "sssep_batch").is_dir() and (candidate / "main.py").is_file():
            if Path(path).resolve().is_relative_to(candidate):
                raise ValueError(f"Choose a data/results location outside the application repository: {path}")
            break


def _new_run_folder(parent):
    parent = Path(parent).expanduser().resolve()
    _reject_project_data_path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stem = CONFIG["slug"] + "_" + datetime.now().strftime("%Y-%m-%d_%H%M%S")
    number = 1
    while True:
        target = parent / (stem if number == 1 else f"{stem}_{number}")
        try:
            target.mkdir()
            return target
        except FileExistsError:
            number += 1


def validate_dataset(dataset):
    """Reject ambiguous identities, malformed spectra and incompatible grids."""
    required = ("participant_ids", "trigger_codes", "channel_names", "frequencies_hz",
                "coherent_amplitude_uv", "phase_insensitive_amplitude_uv")
    missing = [key for key in required if key not in dataset]
    if missing:
        raise ValueError(f"The spectra cache is missing {missing}. ROI-only/selected-bin files cannot replace the full spectra cache.")
    ids = np.asarray(dataset["participant_ids"]).astype(str)
    codes = np.asarray(dataset["trigger_codes"])
    names = np.asarray(dataset["channel_names"]).astype(str)
    frequency = np.asarray(dataset["frequencies_hz"], dtype=float)
    if ids.ndim != 1 or len(ids) < 2 or any(not value.strip() for value in ids):
        raise ValueError("At least two distinct participant identities are required for paired comparisons.")
    if len({value.casefold() for value in ids}) != len(ids):
        raise ValueError("Duplicate participant identities are not independent participants.")
    if codes.ndim != 1 or len(set(codes.tolist())) != len(codes) or not set(CONFIG["codes"]).issubset(set(codes.tolist())):
        raise ValueError(f"Cache trigger codes must uniquely include {CONFIG['codes']}.")
    if names.ndim != 1 or len(names) != 64 or len(set(names.tolist())) != 64:
        raise ValueError("The reproduction requires 64 uniquely named, usable scalp electrodes.")
    if set(names.tolist()) != set(mne.channels.make_standard_montage("biosemi64").ch_names):
        raise ValueError("The cache must contain the complete recognized BioSemi64 scalp channel set.")
    expected = np.fft.rfftfreq(1280, 1 / 256)
    if frequency.shape != expected.shape or not np.array_equal(frequency, expected):
        raise ValueError("Expected all 641 FFT bins for a five-second window at 256 Hz (0.2 Hz spacing).")
    shape = (len(ids), len(codes), len(names), len(frequency))
    for key in required[-2:]:
        values = np.asarray(dataset[key], dtype=np.float64)
        if values.shape != shape or not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError(f"{key} must contain finite nonnegative amplitudes with shape {shape}.")
    for roi, requested in CONFIG["rois"].items():
        missing = sorted(set(requested) - set(names.tolist()))
        if missing:
            raise ValueError(f"ROI {roi!r} is missing electrodes {missing}; no zero filling or silent ROI changes are allowed.")


def _select_dataset(dataset, participants=None):
    validate_dataset(dataset)
    ids = np.asarray(dataset["participant_ids"]).astype(str)
    codes = np.asarray(dataset["trigger_codes"])
    order = np.argsort(ids)
    if participants:
        requested = set(participants)
        absent = sorted(requested - set(ids.tolist()))
        if absent:
            raise ValueError(f"Requested participants are absent: {absent}")
        order = np.asarray([index for index in order if ids[index] in requested])
    cue_indices = [codes.tolist().index(code) for code in CONFIG["codes"]]
    selected = {"participant_ids": ids[order], "trigger_codes": np.asarray(CONFIG["codes"]),
                "channel_names": np.asarray(dataset["channel_names"]).astype(str),
                "frequencies_hz": np.asarray(dataset["frequencies_hz"], dtype=float)}
    for key in ("coherent_amplitude_uv", "phase_insensitive_amplitude_uv"):
        selected[key] = np.asarray(dataset[key], dtype=np.float64)[order][:, cue_indices]
    validate_dataset(selected)
    return selected


def _load_cache(path):
    with np.load(path, allow_pickle=False) as saved:
        dataset = {key: saved[key].copy() for key in saved.files}
    validate_dataset(dataset)
    metadata = dataset.get("capture_metadata_json")
    if metadata is not None:
        metadata = json.loads(str(np.asarray(metadata).item()))
        if metadata.get("processing_method") != RAW_PROCESSING_METHOD:
            raise ValueError("Cached processing method differs from the C4-reconstructed method used in this analysis.")
        if metadata.get("parameters") != json.loads(json.dumps(RAW_PARAMETERS)):
            raise ValueError("Cached preprocessing parameters do not match this fixed reproduction method.")
        counts = metadata.get("trial_counts", {})
        for pid in np.asarray(dataset["participant_ids"]).astype(str):
            for code in np.asarray(dataset["trigger_codes"]).tolist():
                if counts.get(pid, {}).get(str(code)) != 30:
                    raise ValueError(f"Cache metadata does not confirm 30 usable epochs for {pid}, trigger code {code}.")
    else:
        print("Legacy diagnostic cache: array structure is checked; source processing provenance must be verified separately.", flush=True)
    return dataset


def _capture_bdfs(folder, workers, participants, output):
    if type(workers) is not int or workers not in (1, 2, 3):
        raise ValueError("Use one to three file workers.")
    folder = Path(folder).expanduser().resolve()
    _reject_project_data_path(folder)
    if not folder.is_dir():
        raise ValueError(f"BDF input folder does not exist: {folder}")
    sources = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.casefold() == ".bdf"), key=lambda p: p.name.casefold())
    if participants:
        sources = [p for p in sources if p.stem in set(participants)]
        absent = set(participants) - {p.stem for p in sources}
        if absent:
            raise ValueError(f"No BDF file was found for {sorted(absent)}")
    if len(sources) < 2:
        raise ValueError("Select a folder containing at least two participant BDF files.")
    if len({p.stem.casefold() for p in sources}) != len(sources):
        raise ValueError("Each BDF must have a distinct participant filename.")
    source_stats = {str(p): _stat_snapshot(p) for p in sources}
    records, errors = [], []
    # Capture both task conditions once; either standalone script can reuse this cache.
    all_codes = (11, 12, 21, 22)
    with ProcessPoolExecutor(max_workers=min(workers, len(sources))) as executor:
        futures = {executor.submit(process_recording, p, all_codes): p for p in sources}
        for future in as_completed(futures):
            path = futures[future]
            try:
                result = future.result()
                records.append(result)
                details = output / "processing_details"
                details.mkdir(exist_ok=True)
                serializable = {key: value for key, value in result.items() if key not in
                                ("coherent_amplitude_uv", "phase_insensitive_amplitude_uv", "frequencies_hz")}
                serializable["trigger_codes"] = np.asarray(serializable["trigger_codes"]).tolist()
                (details / (path.stem + ".json")).write_text(json.dumps(serializable, indent=2), encoding="utf-8")
                print(f"Processed {len(records)}/{len(sources)}: {path.name}", flush=True)
            except Exception as exc:
                errors.append({"participant_id": path.stem, "error": str(exc), "traceback": traceback.format_exc()})
                print(f"FAILED: {path.name}: {exc}", flush=True)
    if any(_stat_snapshot(Path(path)) != before for path, before in source_stats.items()):
        raise RuntimeError("An input recording changed during processing; no group result will be published.")
    if errors:
        (output / "processing_errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
        raise RuntimeError(f"{len(errors)} recording(s) failed. See processing_errors.json; no group analysis was published.")
    records.sort(key=lambda result: result["participant_id"])
    names = list(records[0]["channel_names"])
    frequency = np.asarray(records[0]["frequencies_hz"])
    for record in records:
        if list(record["channel_names"]) != names or not np.array_equal(record["frequencies_hz"], frequency):
            raise ValueError("Participants have different channel orders or frequency grids; analysis stopped.")
    capture_meta = {"processing_method": RAW_PROCESSING_METHOD, "parameters": RAW_PARAMETERS,
                    "fpvs_reference_commit": RAW_FPVS_REFERENCE_COMMIT,
                    "source_bdf_stats": source_stats, "native_threads_per_worker": 1,
                    "trial_counts": {r["participant_id"]: r["usable_epochs_by_code"] for r in records}}
    dataset = {"participant_ids": np.asarray([r["participant_id"] for r in records]),
                "trigger_codes": np.asarray(all_codes), "channel_names": np.asarray(names),
                "frequencies_hz": frequency, "capture_metadata_json": np.asarray(json.dumps(capture_meta))}
    for key in ("coherent_amplitude_uv", "phase_insensitive_amplitude_uv"):
        dataset[key] = np.stack([record[key] for record in records])
    validate_dataset(dataset)
    np.savez_compressed(output / "full_task_spectra.npz", **dataset)
    return dataset, capture_meta


def _verify_reference_csv(dataset, path):
    before = _file_sha256(path)
    frame = pd.read_csv(path, float_precision="round_trip")
    if set(frame.processing_method.dropna()) != {RAW_PROCESSING_METHOD}:
        raise ValueError("Reference CSV must use the C4-reconstructed v3 processing method.")
    columns = [str(ch) + "_amplitude_uv" for ch in dataset["channel_names"]]
    maximum = 0.0
    for pi, pid in enumerate(dataset["participant_ids"].astype(str)):
        for ci, code in enumerate(dataset["trigger_codes"]):
            rows = frame[frame.participant_id.eq(pid) & frame.trigger_code.eq(code)].sort_values("frequency_hz")
            if len(rows) != 641 or rows.frequency_hz.duplicated().any():
                raise ValueError(f"Reference CSV is incomplete/duplicated for {pid}, trigger code {code}.")
            np.testing.assert_array_equal(rows.frequency_hz.to_numpy(), dataset["frequencies_hz"])
            expected = rows[columns].to_numpy(dtype=float).T
            actual = dataset["coherent_amplitude_uv"][pi, ci]
            np.testing.assert_array_equal(actual, expected)
            maximum = max(maximum, float(np.max(abs(actual - expected))))
    if _file_sha256(path) != before:
        raise RuntimeError("Reference CSV changed during verification.")
    return {"path": str(Path(path).resolve()), "sha256": before, "maximum_error_uv": maximum}


def _verify_reference_diagnostic(dataset, path):
    with np.load(path, allow_pickle=False) as source:
        expected = {key: source[key] for key in source.files}
    ids = np.asarray(expected["participant_ids"]).astype(str).tolist()
    codes = np.asarray(expected["trigger_codes"]).tolist()
    np.testing.assert_array_equal(dataset["frequencies_hz"], expected["frequencies_hz"])
    maximum = 0.0
    for pi, pid in enumerate(dataset["participant_ids"].astype(str)):
        for ci, code in enumerate(dataset["trigger_codes"].tolist()):
            ei, ec = ids.index(pid), codes.index(code)
            for method in ("coherent", "phase_insensitive"):
                actual = dataset[method + "_amplitude_uv"][pi, ci]
                if method + "_amplitude_uv" in expected:
                    names = np.asarray(expected["channel_names"]).astype(str).tolist()
                    wanted = [names.index(str(ch)) for ch in dataset["channel_names"]]
                    value = expected[method + "_amplitude_uv"][ei, ec][wanted]
                else:
                    # Earlier both-hands diagnostics retained complete spectra for the two primary ROIs.
                    value = expected[method + "_roi_amplitude_uv"][ei, ec]
                    actual = np.stack([actual[[dataset["channel_names"].tolist().index(ch) for ch in CONFIG["rois"][roi]]].mean(axis=0)
                                       for roi in CONFIG["primary_rois"]])
                np.testing.assert_allclose(actual, value, rtol=0, atol=2e-15)
                maximum = max(maximum, float(np.max(abs(actual - value))))
    return {"path": str(Path(path).resolve()), "sha256": _file_sha256(path), "maximum_error_uv": maximum}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--bdf-folder", type=Path, help="Original participant BDF folder; processed with the embedded fixed preprocessing snapshot.")
    mode.add_argument("--cache", type=Path, help="Reusable full-electrode spectra NPZ; no BDF processing is needed.")
    parser.add_argument("--output", type=Path, help="Parent results folder; a unique new run is always created.")
    parser.add_argument("--workers", type=int, default=WORKERS, choices=(1, 2, 3))
    parser.add_argument("--participant", action="append", help="Optional participant filename stem; repeat to select a subset.")
    parser.add_argument("--reference-csv", type=Path, help="Optional canonical participant FFT CSV; requires exact coherent reproduction.")
    parser.add_argument("--verify-diagnostic", type=Path, help="Optional earlier full/ROI diagnostic NPZ for a numerical cross-check.")
    args = parser.parse_args(argv)
    cache = args.cache or (Path(CACHE_FILE) if CACHE_FILE else None)
    bdf_folder = args.bdf_folder or (Path(BDF_FOLDER) if BDF_FOLDER else None)
    if args.bdf_folder:
        cache = None
    if args.cache:
        bdf_folder = None
    if cache is None and bdf_folder is None:
        bdf_folder = _choose_directory("Choose the participant BDF folder")
    parent = args.output or (Path(OUTPUT_PARENT) if OUTPUT_PARENT else _choose_directory("Choose a parent folder for reproduction results"))
    output = _new_run_folder(parent)
    manifest = {"status": "running", "analysis": CONFIG["name"], "started_utc": datetime.now(timezone.utc).isoformat(),
        "script": str(Path(__file__).resolve()), "script_sha256": _file_sha256(__file__),
        "python": sys.version, "platform": platform.platform(),
        "packages": {package: importlib.metadata.version(package) for package in ("mne", "numpy", "scipy", "pandas", "matplotlib")},
        "output_folder": str(output), "configuration": CONFIG}
    manifest_path = output / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    try:
        if cache:
            dataset = _load_cache(cache)
            manifest["input_cache"] = {"path": str(cache.resolve()), "sha256": _file_sha256(cache)}
        else:
            dataset, manifest["capture"] = _capture_bdfs(bdf_folder, args.workers, args.participant, output)
        dataset = _select_dataset(dataset, args.participant)
        reference = args.reference_csv or (Path(REFERENCE_CSV) if REFERENCE_CSV else None)
        if reference:
            manifest["canonical_verification"] = _verify_reference_csv(dataset, reference)
        if args.verify_diagnostic:
            manifest["diagnostic_verification"] = _verify_reference_diagnostic(dataset, args.verify_diagnostic)
        config = dict(CONFIG)
        config["provenance"] = {"processing_method": RAW_PROCESSING_METHOD,
                                "reference_csv": manifest.get("canonical_verification"),
                                "diagnostic_npz": manifest.get("diagnostic_verification"),
                                "input_cache": manifest.get("input_cache")}
        analyze_and_export(dataset, config, output)
        manifest.update({"status": "complete", "participants": dataset["participant_ids"].astype(str).tolist(),
                         "participant_count": len(dataset["participant_ids"]), "completed_utc": datetime.now(timezone.utc).isoformat()})
        print(f"Reproduction complete: {output}", flush=True)
    except KeyboardInterrupt:
        manifest.update({"status": "cancelled", "completed_utc": datetime.now(timezone.utc).isoformat()})
        raise
    except Exception as exc:
        manifest.update({"status": "failed", "error": str(exc), "traceback": traceback.format_exc()})
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        raise SystemExit(130)
