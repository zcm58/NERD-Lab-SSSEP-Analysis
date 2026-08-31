"""Check full-frequency electrode exports and microvolt amplitude plots."""

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pytest

from sssep_batch.analysis import plotting
from sssep_batch.models import Spectrum


CHANNELS = ["C3", "Cz", "C4"]
ROI = ["C3", "C4"]


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


def test_frequency_csv_preserves_all_electrodes_and_full_fft_range():
    frame = plotting.spectrum_to_dataframe(make_spectrum(), make_spectrum(0.5), CHANNELS, ROI)

    np.testing.assert_array_equal(frame["frequency_hz"], [0.0, 10.0, 50.0, 128.0])
    np.testing.assert_array_equal(frame["active_mean_amplitude_uv"], [1000.0, 4.0, 2.0, 3000.0])
    assert frame.loc[1, "baseline_mean_amplitude_uv"] == 2.0
    assert frame.loc[1, "active_Cz_amplitude_uv"] == 1000.0
    assert frame.loc[1, "baseline_C4_amplitude_uv"] == 3.0
    assert len(frame.columns) == 9
    assert not any("power" in column for column in frame.columns)


def test_plot_uses_roi_mean_amplitude_units_and_visible_frequency_limits(monkeypatch, tmp_path):
    saved = {}
    def capture_figure(path, **kwargs):
        saved["figure"] = plotting.plt.gcf()
        saved["path"] = path
    monkeypatch.setattr(plotting.plt, "savefig", capture_figure)
    output = tmp_path / "amplitude.png"

    plotting.plot_spectrum(
        make_spectrum(), make_spectrum(0.5), "Amplitude example", output,
        10.0, CHANNELS, ROI,
    )

    axes = saved["figure"].axes[0]
    np.testing.assert_array_equal(axes.lines[0].get_ydata(), [1000.0, 4.0, 2.0, 3000.0])
    np.testing.assert_array_equal(axes.lines[1].get_ydata(), [500.0, 2.0, 1.0, 1500.0])
    assert axes.get_ylabel() == "FFT amplitude (µV)"
    assert axes.get_xlim() == (plotting.FMIN, plotting.FMAX)
    assert axes.get_ylim()[1] == pytest.approx(4.0 * 1.08)
    assert saved["path"] == output
    assert not plotting.plt.fignum_exists(saved["figure"].number)


def test_baseline_frequency_mismatch_fails_instead_of_silently_mislabeling():
    baseline = make_spectrum()
    baseline.freqs = np.array([0.0, 11.0, 50.0, 128.0])
    with pytest.raises(ValueError, match="matching channels and frequency bins"):
        plotting.spectrum_to_dataframe(make_spectrum(), baseline, CHANNELS, ROI)


def test_missing_analysis_channel_fails_instead_of_changing_roi_silently():
    with pytest.raises(ValueError, match="missing from the spectrum"):
        plotting.spectrum_to_dataframe(make_spectrum(), None, CHANNELS, ["Oz"])
