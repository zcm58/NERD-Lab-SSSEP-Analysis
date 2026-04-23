"""Plot and CSV helpers for spectra."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sssep_batch.config import FIXED_HZ_LINES, FMAX, FMIN
from sssep_batch.models import Spectrum


def spectrum_to_dataframe(
    active: Spectrum,
    baseline: Spectrum | None,
) -> pd.DataFrame:
    """Convert an active spectrum, and optionally baseline spectrum, to a table."""

    df = pd.DataFrame(
        {
            "frequency_hz": active.freqs,
            "active_power": active.power,
        }
    )
    if baseline is not None and len(baseline.freqs) == len(active.freqs):
        df["baseline_power"] = baseline.power
    return df


def plot_spectrum(
    active: Spectrum,
    baseline: Spectrum | None,
    title: str,
    outpath: Path,
    target_hz: float | None,
) -> None:
    """Save a spectrum plot for one trigger condition."""

    plt.figure(figsize=(14, 6))
    plt.plot(active.freqs, active.power, linewidth=1.8, label="Active")

    if baseline is not None and len(baseline.freqs) == len(active.freqs):
        plt.plot(
            baseline.freqs,
            baseline.power,
            linestyle="--",
            linewidth=1.4,
            label="Gap/Break baseline",
        )

    y_max = float(np.nanmax(active.power)) if len(active.power) else 1.0
    if baseline is not None and len(baseline.power):
        y_max = max(y_max, float(np.nanmax(baseline.power)))
    y_text = y_max * 0.98 if y_max > 0 else 1.0

    for hz in FIXED_HZ_LINES:
        plt.axvline(hz, linestyle=":", linewidth=1.0)
        plt.text(hz + 0.10, y_text, f"{hz:g} Hz", rotation=90, va="top", fontsize=8)

    if target_hz is not None:
        plt.axvline(target_hz, linestyle="-", linewidth=1.8)
        plt.text(
            target_hz + 0.15,
            y_max * 0.88 if y_max > 0 else 1.0,
            f"Expected {target_hz:g} Hz",
            rotation=90,
            va="top",
            fontsize=9,
        )

    plt.title(title)
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Power")
    plt.xlim(FMIN, FMAX)
    plt.ylim(0, y_max * 1.08 if y_max > 0 else 1.0)
    plt.xticks(np.arange(np.ceil(FMIN), np.floor(FMAX) + 1, 1))
    plt.grid(True, axis="y", alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=300)
    plt.close()
