import numpy as np
import pytest

from sssep_batch.preprocess import filtering


def test_validate_filter_settings_accepts_safe_cutoffs(monkeypatch):
    monkeypatch.setattr(filtering, "LOWCUT", 3.0)
    monkeypatch.setattr(filtering, "HIGHCUT", 50.0)
    monkeypatch.setattr(filtering, "TRIGGER_HZ_MAP", {1: 10.0, 2: 45.0})

    filtering.validate_filter_settings(256.0)


def test_validate_filter_settings_rejects_highcut_below_target(monkeypatch):
    monkeypatch.setattr(filtering, "LOWCUT", 3.0)
    monkeypatch.setattr(filtering, "HIGHCUT", 40.0)
    monkeypatch.setattr(filtering, "TRIGGER_HZ_MAP", {1: 10.0, 2: 45.0})

    with pytest.raises(RuntimeError, match="HIGHCUT=40.0 Hz is too low"):
        filtering.validate_filter_settings(256.0)


def test_get_fir_edge_margin_samples_matches_half_filter_length():
    assert filtering.get_fir_edge_margin_samples(256.0, 3.0, 50.0) == 4224
    assert filtering.get_fir_edge_margin_samples(256.0, None, None) == 0


def test_downsample_if_needed_returns_original_events_when_no_resample(raw_builder):
    raw = raw_builder(["Cz"], ["eeg"], sfreq=128.0, n_times=256)
    events = np.array([[64, 0, 1]], dtype=int)
    log_lines: list[str] = []

    returned_events = filtering.downsample_if_needed(
        raw=raw,
        filename_for_log="no_resample.bdf",
        downsample_rate=256,
        log_func=log_lines.append,
        events=events,
    )

    assert raw.info["sfreq"] == 128.0
    assert returned_events is events


def test_downsample_if_needed_resamples_raw_and_events(raw_builder):
    raw = raw_builder(["Cz"], ["eeg"], sfreq=512.0, n_times=512)
    events = np.array([[128, 0, 1], [384, 0, 2]], dtype=int)
    log_lines: list[str] = []

    returned_events = filtering.downsample_if_needed(
        raw=raw,
        filename_for_log="resample.bdf",
        downsample_rate=256,
        log_func=log_lines.append,
        events=events,
    )

    assert raw.info["sfreq"] == pytest.approx(256.0)
    assert returned_events is not None
    assert returned_events.shape == events.shape
    assert returned_events[:, 2].tolist() == [1, 2]
    assert returned_events[:, 0].max() < raw.n_times
