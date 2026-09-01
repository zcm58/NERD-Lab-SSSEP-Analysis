"""Check participant and group single-electrode FFT amplitude plots."""

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pytest

from sssep_batch.analysis import plotting
from sssep_batch.models import Spectrum


CHANNELS = ["C3", "Cz", "C4"]
def make_spectrum(scale=1.0):
    return Spectrum(
        freqs=np.array([0.0, 10.0, 50.0, 128.0]),
        amplitude_uv=scale * np.array([
            [1000.0, 2.0, 1.0, 3000.0],
            [1000.0, 1000.0, 1000.0, 3000.0],
            [1000.0, 6.0, 3.0, 3000.0],
        ]),
        method="test",
    )


def test_plot_uses_selected_electrode_and_visible_frequency_limits(monkeypatch, tmp_path):
    saved = {}
    def capture_figure(path, **kwargs):
        saved["figure"] = plotting.plt.gcf()
        saved["path"] = path
    monkeypatch.setattr(plotting.plt, "savefig", capture_figure)
    output = tmp_path / "amplitude.png"

    plotting.plot_spectrum(
        make_spectrum(), make_spectrum(0.5), "Amplitude example", output,
        10.0, CHANNELS, "C4",
    )

    axes = saved["figure"].axes[0]
    np.testing.assert_array_equal(axes.lines[0].get_ydata(), [1000.0, 6.0, 3.0, 3000.0])
    np.testing.assert_array_equal(axes.lines[1].get_ydata(), [500.0, 3.0, 1.5, 1500.0])
    assert axes.get_title() == "Amplitude example - Electrode C4"
    assert axes.get_ylabel() == "FFT amplitude at C4 (µV)"
    assert [line.get_label() for line in axes.lines[:2]] == [
        "Cue average",
        "Gap/Break baseline",
    ]
    assert axes.get_xlim() == (plotting.FMIN, plotting.FMAX)
    assert axes.get_ylim()[1] == pytest.approx(6.0 * 1.08)
    assert saved["path"] == output
    assert not plotting.plt.fignum_exists(saved["figure"].number)


def test_baseline_frequency_mismatch_fails_instead_of_silently_mislabeling():
    baseline = make_spectrum()
    baseline.freqs = np.array([0.0, 11.0, 50.0, 128.0])
    with pytest.raises(ValueError, match="matching channels and frequency bins"):
        plotting.plot_spectrum(
            make_spectrum(), baseline, "Amplitude example", None,
            10.0, CHANNELS, "C4",
        )


def test_missing_plot_electrode_fails_clearly():
    with pytest.raises(ValueError, match="Plot electrode 'Oz' is missing"):
        plotting.plot_spectrum(
            make_spectrum(), None, "Amplitude example", None,
            10.0, CHANNELS, "Oz",
        )
