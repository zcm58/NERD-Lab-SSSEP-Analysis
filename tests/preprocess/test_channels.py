"""Tests for channel validation and analysis-channel selection.

These tests focus on the lightweight parts of channel setup: required-channel
errors, the BioSemi first-64-channel convention, and requested analysis labels.
"""

import pytest

from sssep_batch.preprocess import channels


def test_require_channels_raises_for_missing_channels(raw_builder):
    """Missing required channels should raise an explicit runtime error."""
    raw = raw_builder(["Cz", "Pz"], ["eeg", "eeg"])

    with pytest.raises(RuntimeError, match="Missing required channel"):
        channels.require_channels(raw, ["Status"], "stim checks")


def test_get_scalp_channels_returns_first_64_channels(raw_builder):
    """The first 64 channel names should be treated as BioSemi scalp EEG."""
    ch_names = [f"Ch{i:02d}" for i in range(64)] + ["EXG1", "EXG2", "Status"]
    ch_types = ["eeg"] * 66 + ["stim"]
    raw = raw_builder(ch_names, ch_types, n_times=10)

    scalp = channels.get_scalp_channels(raw)

    assert scalp == ch_names[:64]


def test_validate_analysis_channels_uses_requested_list(monkeypatch, raw_builder):
    """Configured analysis channels should be returned when all are present."""
    raw = raw_builder(["Pz", "Cz", "Status"], ["eeg", "eeg", "stim"])
    monkeypatch.setattr(channels, "ANALYSIS_CHANNELS", ["Pz", "Cz"])

    analysis = channels.validate_analysis_channels(raw)

    assert analysis == ["Pz", "Cz"]


def test_validate_analysis_channels_raises_when_requested_channel_is_missing(
    monkeypatch,
    raw_builder,
):
    """Missing requested analysis channels should stop instead of being ignored."""
    raw = raw_builder(["Pz", "Status"], ["eeg", "stim"])
    monkeypatch.setattr(channels, "ANALYSIS_CHANNELS", ["Pz", "Cz"])

    with pytest.raises(RuntimeError, match="Some requested ANALYSIS_CHANNELS were missing"):
        channels.validate_analysis_channels(raw)
