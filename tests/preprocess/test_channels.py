"""Tests for channel validation and analysis-channel selection.

These tests focus on the lightweight parts of channel setup: required-channel
errors, the BioSemi first-64-channel convention, and requested analysis labels.
"""

import warnings

import mne
import numpy as np
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


def test_channel_types_match_fpvs_exg_policy_without_overriding_scalp(raw_builder):
    names = ["Cz", "Pz", "exg1", "EXG2", "eXg3", "status"]
    raw = raw_builder(names, ["misc", "eeg", "misc", "eeg", "eeg", "misc"])
    before = raw.get_data().copy()
    channels.set_known_channel_types(raw, names, lambda _: None)
    assert raw.get_channel_types() == ["misc", "eeg", "eeg", "eeg", "misc", "stim"]
    np.testing.assert_array_equal(raw.get_data(), before)


def test_channel_typing_allows_missing_references(raw_builder):
    raw = raw_builder(["Cz", "Pz", "Status"], ["eeg", "eeg", "stim"])
    logs = []
    channels.set_known_channel_types(raw, ["Cz", "Pz"], logs.append)
    channels.apply_exg_reference_and_drop(raw, "sample.bdf", logs.append)
    assert raw.ch_names == ["Cz", "Pz", "Status"]
    assert any("Skip initial referencing" in line for line in logs)


def test_channel_keep_allows_missing_status_for_annotation_events(raw_builder):
    raw = raw_builder(["Cz", "Pz"], ["eeg", "eeg"])
    logs = []
    channels.keep_scalp_and_status_channels(raw, ["Cz", "Pz"], "sample.bdf", logs.append)
    assert raw.ch_names == ["Cz", "Pz"]
    assert "2 EEG; Status present=False" in logs[-1]


def test_fft_channels_use_fpvs_standard_order_for_complete_montage(raw_builder):
    standard = mne.channels.make_standard_montage("biosemi64").ch_names
    names = list(reversed(standard)) + ["Status"]
    data = np.repeat(np.arange(65, dtype=float)[:, None], 10, axis=1)
    raw = raw_builder(names, ["eeg"] * 64 + ["stim"], data=data)
    ordered = channels.get_fft_channels(raw)
    assert ordered == standard
    np.testing.assert_array_equal(raw.get_data(picks=ordered)[:, 0], np.arange(63, -1, -1))


def test_fft_channel_subset_excludes_bads_and_preserves_recording_order(raw_builder):
    names = list(reversed(mne.channels.make_standard_montage("biosemi64").ch_names))
    raw = raw_builder(names + ["Status"], ["eeg"] * 64 + ["stim"])
    raw.info["bads"] = ["Cz"]
    assert channels.get_fft_channels(raw) == [name for name in names if name != "Cz"]


def test_unknown_64_fft_channels_keep_actual_names(raw_builder):
    names = [f"Unknown{index}" for index in range(64)]
    raw = raw_builder(names, ["eeg"] * 64)
    assert channels.get_fft_channels(raw) == names


def test_montage_matches_fpvs_loader_before_reference(monkeypatch, raw_builder):
    monkeypatch.setattr(channels, "MONTAGE_NAME", "standard_1005")
    raw = raw_builder(["cz", "Pz", "EXG1", "EXG2", "Status"],
                      ["eeg", "eeg", "eeg", "eeg", "stim"])
    expected = raw.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        expected.set_montage("standard_1005", on_missing="warn", match_case=False, verbose=False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        channels.apply_biosemi_montage(raw, lambda _: None)
    assert not caught  # Missing reference positions are expected before dropping EXG1/2.
    for actual, reference in zip(raw.info["chs"], expected.info["chs"]):
        np.testing.assert_array_equal(actual["loc"], reference["loc"])


def test_montage_does_not_suppress_missing_scalp_warning(monkeypatch, raw_builder):
    monkeypatch.setattr(channels, "MONTAGE_NAME", "standard_1005")
    raw = raw_builder(["Cz", "Unknown", "EXG1", "EXG2"], ["eeg"] * 4)
    with pytest.warns(RuntimeWarning, match="Unknown"):
        channels.apply_biosemi_montage(raw, lambda _: None)


def test_initial_reference_matches_mne_then_drops_references(raw_builder):
    data = np.random.default_rng(501).normal(scale=1e-6, size=(5, 200))
    data[4] = 100
    raw = raw_builder(["Cz", "Pz", "EXG1", "EXG2", "Status"],
                      ["eeg", "eeg", "eeg", "eeg", "stim"], data=data)
    expected = raw.copy()
    expected.set_eeg_reference(ref_channels=["EXG1", "EXG2"], projection=False, verbose=False)
    expected.drop_channels(["EXG1", "EXG2"])
    channels.apply_exg_reference_and_drop(raw, "sample.bdf", lambda _: None)
    assert raw.ch_names == expected.ch_names
    np.testing.assert_array_equal(raw.get_data(), expected.get_data())


def test_initial_reference_failure_warns_and_still_drops_refs(monkeypatch, raw_builder):
    raw = raw_builder(["Cz", "EXG1", "EXG2"], ["eeg"] * 3)

    def fail(**kwargs):
        raise RuntimeError("synthetic reference failure")

    monkeypatch.setattr(raw, "set_eeg_reference", fail)
    logs = []
    channels.apply_exg_reference_and_drop(raw, "sample.bdf", logs.append)
    assert raw.ch_names == ["Cz"]
    assert any("Initial reference failed" in line for line in logs)


def test_final_reference_matches_projector_and_excludes_remaining_bads(raw_builder):
    data = np.random.default_rng(502).normal(scale=1e-6, size=(4, 200))
    data[3] = 100
    raw = raw_builder(["Cz", "Pz", "Fz", "Status"],
                      ["eeg", "eeg", "eeg", "stim"], data=data)
    raw.info["bads"] = ["Fz"]
    expected = raw.copy()
    expected.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    expected.apply_proj(verbose=False)
    channels.apply_final_average_reference(raw, "sample.bdf", lambda _: None)
    np.testing.assert_array_equal(raw.get_data(), expected.get_data())
    np.testing.assert_allclose(raw.get_data(picks=["Cz", "Pz"]).mean(axis=0), 0, atol=1e-20)
    np.testing.assert_array_equal(raw.get_data(picks="Status")[0], data[3])
    assert raw.info["bads"] == ["Fz"]
    assert all(proj["active"] for proj in raw.info["projs"])


def test_final_reference_skips_when_all_eeg_channels_are_bad(raw_builder):
    raw = raw_builder(["Cz"], ["eeg"])
    raw.info["bads"] = ["Cz"]
    logs = []
    channels.apply_final_average_reference(raw, "sample.bdf", logs.append)
    assert raw.info["projs"] == []
    assert any("No good EEG channels" in line for line in logs)


def test_final_reference_failure_warns_and_continues(monkeypatch, raw_builder):
    raw = raw_builder(["Cz", "Pz"], ["eeg", "eeg"])

    def fail(**kwargs):
        raise RuntimeError("synthetic average-reference failure")

    monkeypatch.setattr(raw, "set_eeg_reference", fail)
    logs = []
    channels.apply_final_average_reference(raw, "sample.bdf", logs.append)
    assert any("Average reference failed" in line for line in logs)
