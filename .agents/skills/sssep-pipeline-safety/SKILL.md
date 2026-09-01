---
name: sssep-pipeline-safety
description: Use when changing or reviewing SSSEP processing behavior, including sssep_batch/pipeline.py, analysis, events, preprocess, batch parallelism, config constants that affect math, event timing, filtering, epochs, spectra, metrics, or real-data regression risk.
---

# SSSEP Pipeline Safety

## Overview

Use this workflow to keep processing changes behavior-preserving unless the user
explicitly asks for an analysis change.

## Workflow

1. Read `AGENTS.md`, `architecture.md`, `sssep_batch/AGENTS.md`, and the
   relevant module tests before editing. For reference-method work, also read
   `docs/fpvs-parity.md`.
2. State whether the task is intended to change mathematical output. If unclear,
   stop and ask.
3. Identify the smallest module that owns the behavior. Keep `pipeline.py` as
   orchestration only.
4. Preserve these invariants:
   - The current method is `fpvs_amplitude_epoch_crop_v2`, based on FPVS commit
     `185d803f0056daebee04e5f28cc6b554c47336ce`; the old power/Welch method was
     intentionally replaced.
   - Load the reference BioSemi channel subset and apply `standard_1005`
     before preprocessing, then EXG reference/drop and scalp-plus-Status
     retention.
   - Apply the scaled-duration 0.1–50 Hz FIR at the original sampling rate,
     downsample to 256 Hz, screen/interpolate bad channels at kurtosis threshold
     5, and apply the final average reference. Keep the reference's logged
     warning-and-continue behavior explicit.
   - Detect `Status` events after preprocessing with the reference MNE options.
     Require complete SSSEP onset windows (default 15 seconds), with no extra
     FIR edge exclusion or EEG zero replacement. Before same-cue averaging and
     FFT calculation, remove 2.5 seconds from each end. At 256 Hz, the default
     retains samples 640:3200: 2560 samples, or 10 seconds. This SSSEP-specific
     crop is distinct from the FPVS visual-oddball 1.2 Hz marker crop.
   - Exclude unresolved bad channels. Average trials in float64 per electrode,
     convert to microvolts, and compute the first `N // 2 + 1` bins of
     `abs(FFT(mean_epoch_uv)) / N * 2`, including reference DC/Nyquist scaling.
     Do not add a Hann taper, detrending, power squaring, or Welch PSD.
   - Preserve full per-electrode nonnegative-frequency amplitude CSVs.
     Plots/summaries average the configured ROI's available electrode
     amplitudes afterward and report actual channel lists.
   - File-level parallelism stays in `batch.py`.
   - Native thread caps stay at `1` per worker.
   - `MAX_INDIVIDUAL_PLOTS` affects amplitude PNGs only, not metrics or CSVs.
   - Each batch creates a unique run folder and preserves past results.
5. Add or update focused tests for changed math, event timing, filtering, epoch,
   spectrum, metric, or batch behavior.
6. Compile touched modules with `.\.venv\Scripts\python.exe -m py_compile`
   and run `.\.venv\Scripts\python.exe -m pytest -q` when code changes.
7. If math was not meant to change and a local `.bdf` fixture is available, run
   the external regression path or compare representative outputs. Optional
   checks use `SSSEP_TEST_BDF` and `FPVS_REFERENCE_ROOT`; keep both external and
   the reference checkout read-only. Do not launch its GUI/offscreen Qt for
   numerical verification. Compare matching methods, not old power outputs.

## Return

Report files touched, whether math/output contracts changed, verification gates
run, and any skipped regression reason.
