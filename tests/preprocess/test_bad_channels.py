"""Check FPVS kurtosis, spherical interpolation and disabled/failure behavior."""

import mne
import numpy as np
import pytest
from scipy.stats import kurtosis

from sssep_batch.preprocess import bad_channels


def _recording(*, montage=True):
    names = mne.channels.make_standard_montage("biosemi64").ch_names
    data = np.random.default_rng(908).normal(scale=1e-6, size=(64, 4096))
    data[names.index("Pz"), 57] = 1e-3
    raw = mne.io.RawArray(data, mne.create_info(names, 256.0, "eeg"), verbose=False)
    if montage:
        raw.set_montage("standard_1005", match_case=False, verbose=False)
    raw.info["bads"] = ["Cz"]
    return raw


def test_kurtosis_and_interpolation_match_fpvs_reference(monkeypatch, tmp_path):
    """Manual bads are excluded from statistics and included in interpolation."""
    monkeypatch.setattr(bad_channels, "FORCED_BAD_CHANNELS", ())
    monkeypatch.setattr(bad_channels, "KURTOSIS_REJECT_Z", 5.0)
    monkeypatch.setattr(bad_channels, "KURTOSIS_TRIM_PROPORTION", 0.1)
    raw = _recording()
    expected = raw.copy()
    names = [name for name in raw.ch_names if name != "Cz"]
    values = np.nan_to_num(kurtosis(raw.get_data(picks=names), axis=1, fisher=True, bias=False))
    trimmed = np.sort(values)[6:-6]  # floor(63 * 0.1) from each tail
    scores = (values - trimmed.mean()) / trimmed.std(ddof=0)
    identified = [name for name, score in zip(names, scores) if abs(score) > 5.0]
    assert "Pz" in identified
    expected.info["bads"].extend(identified)
    expected.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)

    metrics = bad_channels.detect_and_interpolate_bad_channels_by_kurtosis(
        raw, "sample.bdf", tmp_path, lambda _: None
    )

    assert metrics["channel"].tolist() == names
    np.testing.assert_array_equal(metrics["excess_kurtosis"], values)
    np.testing.assert_array_equal(metrics["kurtosis_z"], scores)
    assert metrics.loc[metrics["bad_by_kurtosis"], "channel"].tolist() == identified
    assert metrics.loc[metrics["bad_by_kurtosis"], "interpolated"].all()
    np.testing.assert_array_equal(raw.get_data(), expected.get_data())
    assert raw.info["bads"] == []
    assert (tmp_path / "bad_channel_metrics.csv").exists()


@pytest.mark.parametrize("threshold", [None, 0])
def test_disabled_threshold_skips_detection_and_existing_bad_interpolation(
    monkeypatch, tmp_path, threshold
):
    monkeypatch.setattr(bad_channels, "FORCED_BAD_CHANNELS", ())
    monkeypatch.setattr(bad_channels, "KURTOSIS_REJECT_Z", threshold)
    raw = _recording()
    before = raw.get_data().copy()
    calls = []
    monkeypatch.setattr(raw, "interpolate_bads", lambda **kwargs: calls.append(kwargs))
    logs = []
    metrics = bad_channels.detect_and_interpolate_bad_channels_by_kurtosis(
        raw, "sample.bdf", tmp_path, logs.append
    )
    assert metrics.empty
    assert calls == []
    assert raw.info["bads"] == ["Cz"]
    np.testing.assert_array_equal(raw.get_data(), before)
    assert any("no threshold" in line for line in logs)


def test_missing_montage_preserves_flagged_channels_and_warns(monkeypatch, tmp_path):
    monkeypatch.setattr(bad_channels, "FORCED_BAD_CHANNELS", ("C4",))
    monkeypatch.setattr(bad_channels, "KURTOSIS_REJECT_Z", 5.0)
    raw = _recording(montage=False)
    before = raw.get_data().copy()
    logs = []
    metrics = bad_channels.detect_and_interpolate_bad_channels_by_kurtosis(
        raw, "sample.bdf", tmp_path, logs.append
    )
    assert {"Cz", "Pz", "C4"}.issubset(raw.info["bads"])
    assert not metrics["interpolated"].any()
    np.testing.assert_array_equal(raw.get_data(), before)
    assert any("No montage" in line for line in logs)


def test_interpolation_failure_warns_without_claiming_success(monkeypatch, tmp_path):
    monkeypatch.setattr(bad_channels, "FORCED_BAD_CHANNELS", ("C4",))
    monkeypatch.setattr(bad_channels, "KURTOSIS_REJECT_Z", 5.0)
    raw = _recording()
    before = raw.get_data().copy()

    def fail(**kwargs):
        raw.info["bads"] = []  # Even partial failures must retain unresolved bads.
        raise RuntimeError("synthetic interpolation failure")

    monkeypatch.setattr(raw, "interpolate_bads", fail)
    logs = []
    metrics = bad_channels.detect_and_interpolate_bad_channels_by_kurtosis(
        raw, "sample.bdf", tmp_path, logs.append
    )
    assert {"Cz", "Pz", "C4"}.issubset(raw.info["bads"])
    assert not metrics["interpolated"].any()
    np.testing.assert_array_equal(raw.get_data(), before)
    assert any("Interpolation failed" in line for line in logs)


def test_policy_channel_excluded_from_detection_and_all_interpolation_training(
    monkeypatch, tmp_path
):
    """A huge C4 cannot influence statistics or the repair of another bad channel."""
    monkeypatch.setattr(bad_channels, "FORCED_BAD_CHANNELS", ("C4",))
    monkeypatch.setattr(bad_channels, "KURTOSIS_REJECT_Z", 5.0)
    monkeypatch.setattr(bad_channels, "KURTOSIS_TRIM_PROPORTION", 0.1)
    raw = _recording()
    raw._data[raw.ch_names.index("C4")] *= 1e8
    expected = raw.copy()
    expected.info["bads"].append("C4")
    names = [name for name in raw.ch_names if name not in {"Cz", "C4"}]
    values = np.nan_to_num(kurtosis(raw.get_data(picks=names), axis=1, fisher=True, bias=False))
    trimmed = np.sort(values)[6:-6]
    scores = (values - trimmed.mean()) / trimmed.std(ddof=0)
    identified = [name for name, score in zip(names, scores) if abs(score) > 5.0]
    assert "Pz" in identified
    expected.info["bads"].extend(identified)
    expected.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)
    logs = []

    metrics = bad_channels.detect_and_interpolate_bad_channels_by_kurtosis(
        raw, "sample.bdf", tmp_path, logs.append
    )

    policy = metrics[metrics["bad_by_policy"]]
    assert policy["channel"].tolist() == ["C4"]
    assert policy["excess_kurtosis"].isna().all()
    assert policy["kurtosis_z"].isna().all()
    assert not policy["bad_by_kurtosis"].any()
    assert policy["interpolated"].all()
    inspected = metrics[~metrics["bad_by_policy"]]
    assert inspected["channel"].tolist() == names
    np.testing.assert_array_equal(inspected["excess_kurtosis"], values)
    np.testing.assert_array_equal(inspected["kurtosis_z"], scores)
    assert metrics.loc[metrics["bad_by_kurtosis"], "channel"].tolist() == identified
    assert metrics.loc[metrics["bad_by_kurtosis"], "interpolated"].all()
    np.testing.assert_array_equal(raw.get_data(), expected.get_data())
    assert raw.info["bads"] == []
    assert any("Bad by policy" in line and "C4" in line for line in logs)


@pytest.mark.parametrize("threshold", [None, 0])
def test_policy_channel_repaired_even_when_automatic_detection_is_disabled(
    monkeypatch, tmp_path, threshold
):
    monkeypatch.setattr(bad_channels, "FORCED_BAD_CHANNELS", ("C4",))
    monkeypatch.setattr(bad_channels, "KURTOSIS_REJECT_Z", threshold)
    raw = _recording()
    expected = raw.copy()
    expected.info["bads"].append("C4")
    expected.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)

    metrics = bad_channels.detect_and_interpolate_bad_channels_by_kurtosis(
        raw, "sample.bdf", tmp_path, lambda _: None
    )

    assert metrics["channel"].tolist() == ["C4"]
    assert metrics["bad_by_policy"].all()
    assert metrics["interpolated"].all()
    assert not metrics["bad_by_kurtosis"].any()
    np.testing.assert_array_equal(raw.get_data(), expected.get_data())
    assert raw.info["bads"] == []


def test_missing_policy_channel_warns_without_relabeling_other_electrodes(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(bad_channels, "FORCED_BAD_CHANNELS", ("C4",))
    raw = _recording()
    raw.drop_channels(["C4"])
    logs = []

    metrics = bad_channels.detect_and_interpolate_bad_channels_by_kurtosis(
        raw, "sample.bdf", tmp_path, logs.append
    )

    assert "C4" not in raw.ch_names
    assert "C4" not in metrics["channel"].tolist()
    assert not metrics["bad_by_policy"].any()
    assert any("Policy electrode 'C4' is not an EEG channel" in line for line in logs)
