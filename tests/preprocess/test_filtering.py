"""Numerical and failure-behavior checks for FPVS-compatible filtering."""

import numpy as np
import pytest

from sssep_batch.preprocess import filtering


@pytest.mark.parametrize("lowcut,highcut", [(0.1, 50.0), (3.0, 40.0), (None, None)])
def test_validate_filter_settings_accepts_ordered_cutoffs(monkeypatch, lowcut, highcut):
    """FPVS does not add SSSEP target-frequency rejection to cutoff validation."""
    monkeypatch.setattr(filtering, "LOWCUT", lowcut)
    monkeypatch.setattr(filtering, "HIGHCUT", highcut)
    filtering.validate_filter_settings(256.0)


@pytest.mark.parametrize("lowcut", [50.0, 51.0])
def test_validate_filter_settings_rejects_inverted_cutoffs(monkeypatch, lowcut):
    monkeypatch.setattr(filtering, "LOWCUT", lowcut)
    monkeypatch.setattr(filtering, "HIGHCUT", 50.0)
    with pytest.raises(ValueError, match="high-pass must be below low-pass"):
        filtering.validate_filter_settings(256.0)


@pytest.mark.parametrize(
    "sfreq,target,expected",
    [(256.0, 256, 8449), (2048.0, 256, 67585), (512.0, 256, 16897),
     (128.0, 256, 8449), (512.0, None, 8449), (512.0, 0, 8449),
     (1000.1, 256, 33005)],
)
def test_filter_length_preserves_duration_and_odd_length(sfreq, target, expected):
    assert filtering._scaled_filter_length(
        8449, current_sfreq=sfreq, downsample_rate=target
    ) == expected


def test_filter_then_resample_matches_fpvs_mne_calls(monkeypatch, raw_builder):
    """Compare samples, Status and metadata with the exact reference MNE calls."""
    monkeypatch.setattr(filtering, "DOWNSAMPLE_RATE", 256)
    data = np.random.default_rng(716).normal(scale=1e-6, size=(3, 32768))
    data[2] = 0
    data[2, 1024:1032] = 100
    raw = raw_builder(["Cz", "Pz", "Status"], ["eeg", "eeg", "stim"],
                      sfreq=512.0, data=data)
    expected = raw.copy()
    expected.filter(
        0.1, 50.0, method="fir", phase="zero-double", fir_window="hamming",
        fir_design="firwin", l_trans_bandwidth=0.1, h_trans_bandwidth=0.1,
        filter_length=16897, skip_by_annotation="edge", verbose=False,
    )
    metadata = filtering.apply_basic_fir_filter(raw, "sample.bdf", 0.1, 50.0, lambda _: None)
    np.testing.assert_array_equal(raw.get_data(), expected.get_data())
    np.testing.assert_array_equal(raw.get_data(picks="Status")[0], data[2])
    assert metadata == {"highpass": 0.1, "lowpass": 50.0}

    expected.resample(256, npad="auto", window="hann", verbose=False)
    with expected.info._unlock():
        expected.info.update(metadata)
    filtering.downsample_if_needed(
        raw, "sample.bdf", 256, lambda _: None, filter_info_to_preserve=metadata
    )
    np.testing.assert_array_equal(raw.get_data(), expected.get_data())
    assert raw.info["sfreq"] == 256.0
    assert raw.info["highpass"] == expected.info["highpass"]
    assert raw.info["lowpass"] == expected.info["lowpass"]


@pytest.mark.parametrize("target", [None, 0, 128, 256])
def test_downsample_noop_preserves_samples(raw_builder, target):
    raw = raw_builder(["Cz"], ["eeg"], sfreq=128.0, n_times=256)
    before = raw.get_data().copy()
    filtering.downsample_if_needed(raw, "sample.bdf", target, lambda _: None)
    np.testing.assert_array_equal(raw.get_data(), before)
    assert raw.info["sfreq"] == 128.0


def test_filter_failure_warns_and_continues(monkeypatch, raw_builder):
    raw = raw_builder(["Cz"], ["eeg"])
    logs = []

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic filter failure")

    monkeypatch.setattr(raw, "filter", fail)
    assert filtering.apply_basic_fir_filter(raw, "sample.bdf", 0.1, 50.0, logs.append) == {}
    assert any("Warn: Filter failed" in line for line in logs)


def test_resample_failure_warns_and_continues(monkeypatch, raw_builder):
    raw = raw_builder(["Cz"], ["eeg"], sfreq=512.0)
    logs = []

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic resampling failure")

    monkeypatch.setattr(raw, "resample", fail)
    filtering.downsample_if_needed(raw, "sample.bdf", 256, logs.append)
    assert raw.info["sfreq"] == 512.0
    assert any("Warn: Resampling failed" in line for line in logs)
