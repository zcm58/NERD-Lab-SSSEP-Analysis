"""Check participant and group single-electrode FFT amplitude plots."""

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pytest

from sssep_batch.analysis import plotting
from sssep_batch.analysis.saved_fft import FftProvenance, RoiSpectrum, SavedEvent
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
        "Trigger code average",
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


@pytest.mark.parametrize("active_label", ["Participant cue average", "Group cue average"])
@pytest.mark.parametrize(("target_hz", "scale"), [(26.0, 1), (17.5, 1), (None, 1), (26.0, 0)])
def test_immediate_fft_marker_uses_actual_tens_frequency(
    monkeypatch, tmp_path, active_label, target_hz, scale,
):
    figures = []
    monkeypatch.setattr(plotting.plt, "savefig", lambda *_args, **_kwargs: figures.append(plotting.plt.gcf()))
    spectrum = make_spectrum(scale)
    before = spectrum.amplitude_uv.copy()

    plotting.plot_spectrum(
        spectrum, None, "Cue FFT", tmp_path / "cue.png", target_hz,
        CHANNELS, "C3", active_label=active_label,
    )

    axes = figures[0].axes[0]
    markers = [line for line in axes.lines if line.get_label() == "TENS Unit Stimulation Frequency"]
    if target_hz is None:
        assert markers == []
    else:
        assert len(markers) == 1
        assert markers[0].get_linestyle() == "--"
        assert list(markers[0].get_xdata()) == [target_hz, target_hz]
        assert "TENS Unit Stimulation Frequency" in [text.get_text() for text in axes.get_legend().texts]
    if scale == 0:
        assert axes.get_ylim() == (0.0, 1.0)
    np.testing.assert_array_equal(axes.lines[0].get_ydata(), before[0])
    np.testing.assert_array_equal(spectrum.amplitude_uv, before)


@pytest.mark.parametrize("participant_id", [None, "P01"])
@pytest.mark.parametrize(
    ("saved_target", "override", "scale", "expected"),
    [(26.0, None, 1, 26.0), (17.5, None, 1, 17.5), (10.0, 26.0, 1, 26.0),
     (None, None, 1, None), (None, 26.0, 0, 26.0)],
)
def test_saved_fft_marker_uses_override_without_changing_spectrum(
    monkeypatch, tmp_path, participant_id, saved_target, override, scale, expected,
):
    spectrum = RoiSpectrum(
        event=SavedEvent("cue", 11, "BothHands Left Hand", saved_target),
        participant_id=participant_id,
        requested_channels=("C3", "C4"), used_channels=("C3", "C4"),
        contributing_participant_ids=("P01",) if participant_id else ("P01", "P02"),
        frequencies=np.array([0.0, 10.0, 26.0, 50.0]),
        amplitude_uv=scale * np.array([0.0, 2.0, 6.0, 1.0]),
        participant_contributions=(),
        provenance=FftProvenance(
            processing_method="test", fft_schema_version=1, fpvs_reference_commit="reference",
            montage_name="standard_1005", sampling_rate_hz=100.0, analysis_window_sec=1.0,
            epoch_window_sec=1.0, fft_crop_start_sec=0.0, fft_crop_end_sec=0.0,
            plot_fmin_hz=3.0, plot_fmax_hz=50.0,
        ),
    )
    before = spectrum.amplitude_uv.copy()
    figures = []
    monkeypatch.setattr(plotting.plt.Figure, "savefig", lambda figure, *_args, **_kwargs: figures.append(figure))

    plotting.plot_saved_roi_spectrum(
        spectrum, "Central", tmp_path / "roi.png", stimulation_hz=override,
    )

    axes = figures[0].axes[0]
    markers = [line for line in axes.lines if line.get_label() == "TENS Unit Stimulation Frequency"]
    if expected is None:
        assert markers == []
    else:
        assert len(markers) == 1
        assert markers[0].get_linestyle() == "--"
        assert list(markers[0].get_xdata()) == [expected, expected]
        assert "TENS Unit Stimulation Frequency" in [text.get_text() for text in axes.get_legend().texts]
    if scale == 0:
        assert axes.get_ylim() == (0.0, 1.0)
    np.testing.assert_array_equal(axes.lines[0].get_ydata(), before)
    np.testing.assert_array_equal(spectrum.amplitude_uv, before)
    assert spectrum.event.target_hz == saved_target
