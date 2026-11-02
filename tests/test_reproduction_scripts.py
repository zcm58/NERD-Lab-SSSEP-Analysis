"""Scientific and lifecycle contracts for the independent research scripts."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

import mne
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ["reproduce_left_vs_right_hand", "reproduce_right_hand_vs_right_ankle"]
FULL_BAND_SCRIPTS = [name + "_full_band" for name in SCRIPTS]
ALL_SCRIPTS = SCRIPTS + FULL_BAND_SCRIPTS


def load_script(name):
    spec = spec_from_file_location(name, ROOT / "research" / (name + ".py"))
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=ALL_SCRIPTS)
def script(request):
    return load_script(request.param)


@pytest.fixture(params=SCRIPTS)
def two_bin_script(request):
    return load_script(request.param)


@pytest.fixture(params=FULL_BAND_SCRIPTS)
def full_band_script(request):
    return load_script(request.param)


def synthetic_dataset(script, n=5):
    """Two unequal target amplitudes amid larger, excluded nearby FFT bins."""
    frequencies = np.fft.rfftfreq(1280, 1 / 256)
    channels = mne.channels.make_standard_montage("biosemi64").ch_names
    values = np.empty((n, 2, 64, len(frequencies)))
    near = (frequencies >= 25 - 1e-9) & (frequencies <= 27 + 1e-9)
    at = {hz: np.flatnonzero(np.isclose(frequencies, hz, rtol=0, atol=1e-9))[0]
          for hz in (25.4, 26.0, 26.2, 26.4)}
    for pi in range(n):
        base = 1 + pi * .2
        values[pi, 0] = base
        values[pi, 1] = base + .8
        values[pi, 0, :, near] = 100 + pi
        values[pi, 1, :, near] = 200 + pi
        values[pi, 0, :, at[25.4]] = base - .6 + .02 * pi
        values[pi, 0, :, at[26.4]] = base
        values[pi, 1, :, at[25.4]] = base + .1 + .01 * pi
        values[pi, 1, :, at[26.4]] = base + .5 - .01 * pi
        # Both intervening peaks must be excluded from the two-bin response.
        # The larger 26 Hz bin must remain eligible for historical peak matching.
        values[pi, 0, :, at[26.0]] = 1000 + 3 * pi
        values[pi, 1, :, at[26.0]] = 1001 + 2 * pi
        values[pi, :, :, at[26.2]] = 500 + pi
    return {"participant_ids": np.asarray([f"Synthetic{pi}" for pi in range(n)]),
            "trigger_codes": np.asarray(script.CONFIG["codes"]),
            "channel_names": np.asarray(channels), "frequencies_hz": frequencies,
            "coherent_amplitude_uv": values.copy(), "phase_insensitive_amplitude_uv": values.copy()}


def test_pooled_background_subtraction_retains_negative_values_and_pairing(two_bin_script, tmp_path, monkeypatch):
    script = two_bin_script
    dataset = synthetic_dataset(script)
    # Raster integrity/layout are checked on real-data exports; this checks calculations.
    monkeypatch.setattr(script.plt.Figure, "savefig", lambda *args, **kwargs: None)
    result = script.analyze_and_export(dataset, script.CONFIG, tmp_path)
    assert result["N"] == 5
    np.testing.assert_allclose(result["signal_bins_hz"], [25.4, 26.4], rtol=0, atol=1e-9)
    assert len(result["background_bins_hz"]) == 16
    assert not set(result["signal_bins_hz"]) & set(result["background_bins_hz"])
    np.testing.assert_allclose(result["historical_matched_frequencies_hz"], np.full(5, 26.0), rtol=0, atol=1e-9)
    values = pd.read_csv(tmp_path / "participant_pooled_values.csv")
    assert (values.background_corrected_amplitude_uv < 0).all()
    primary = script.CONFIG["primary_rois"][0]
    rows = values[(values.method == "phase_insensitive") & (values.roi == primary)]
    cue0 = rows[rows.trigger_code == script.CONFIG["codes"][0]].sort_values("participant_id")
    cue1 = rows[rows.trigger_code == script.CONFIG["codes"][1]].sort_values("participant_id")
    bases = 1 + .2 * np.arange(5)
    np.testing.assert_allclose(cue0.pooled_raw_amplitude_uv, bases - .3 + .01 * np.arange(5), atol=2e-15)
    np.testing.assert_allclose(cue1.pooled_raw_amplitude_uv, bases + .3, atol=2e-15)
    np.testing.assert_allclose(cue0.background_mean_amplitude_uv, bases, atol=2e-15)
    np.testing.assert_allclose(cue1.background_mean_amplitude_uv, bases + .8, atol=2e-15)
    np.testing.assert_allclose(cue0.background_corrected_amplitude_uv, -.3 + .01 * np.arange(5), atol=2e-15)
    np.testing.assert_allclose(cue1.background_corrected_amplitude_uv, -.5, atol=2e-15)
    stats = pd.read_csv(tmp_path / "paired_statistics_uncorrected.csv")
    stats = stats[(stats.method == "phase_insensitive") & (stats.comparison == primary)]
    assert stats.N.eq(5).all() and stats.df.eq(4).all()
    corrected = stats[stats.metric == "background_corrected_amplitude_uv"].iloc[0]
    raw = stats[stats.metric == "pooled_raw_amplitude_uv"].iloc[0]
    assert corrected.mean_change_uv == pytest.approx(.22)
    assert raw.mean_change_uv == pytest.approx(-.58)


def test_full_band_averages_all_eleven_bins_and_excludes_outside_bins(full_band_script, tmp_path, monkeypatch):
    script = full_band_script
    dataset = synthetic_dataset(script)
    frequency = dataset["frequencies_hz"]
    signal_indices = [np.flatnonzero(np.isclose(frequency, hz, rtol=0, atol=1e-9))[0]
                      for hz in np.linspace(25, 27, 11)]
    background_indices = [np.flatnonzero(np.isclose(frequency, hz, rtol=0, atol=1e-9))[0]
                          for hz in [*np.linspace(23, 24.4, 8), *np.linspace(27.6, 29, 8)]]
    outside = np.ones(len(frequency), dtype=bool)
    outside[signal_indices + background_indices] = False
    values = dataset["phase_insensitive_amplitude_uv"]
    for pi in range(5):
        base = 1 + .2 * pi
        # Large values include the four guard bins and must enter neither mean.
        values[pi, 0, :, outside] = 5000 + pi
        values[pi, 1, :, outside] = 10000 + pi
        for j, index in enumerate(signal_indices):
            values[pi, 0, :, index] = base - .3 + .01 * pi + .02 * (j - 5)
            values[pi, 1, :, index] = base + .3 + .03 * (j - 5)
        for j, index in enumerate(background_indices):
            values[pi, 0, :, index] = base + .005 * (j - 7.5)
            values[pi, 1, :, index] = base + .8 + .007 * (j - 7.5)
    dataset["coherent_amplitude_uv"] = values.copy()
    # Identities, rather than lexical row positions, define each paired value.
    permutation = [2, 0, 4, 1, 3]
    for key in ("participant_ids", "coherent_amplitude_uv", "phase_insensitive_amplitude_uv"):
        dataset[key] = dataset[key][permutation]
    monkeypatch.setattr(script.plt.Figure, "savefig", lambda *args, **kwargs: None)
    result = script.analyze_and_export(dataset, script.CONFIG, tmp_path)
    np.testing.assert_allclose(result["signal_bins_hz"], np.linspace(25, 27, 11), rtol=0, atol=1e-9)
    np.testing.assert_allclose(result["background_bins_hz"], frequency[background_indices], rtol=0, atol=1e-9)
    assert not set(result["signal_bins_hz"]) & set(result["background_bins_hz"])
    rows = pd.read_csv(tmp_path / "participant_pooled_values.csv")
    statistics = pd.read_csv(tmp_path / "paired_statistics_uncorrected.csv")
    bases = 1 + .2 * np.arange(5)
    changes = .2 + .01 * np.arange(5)
    for method in ("coherent", "phase_insensitive"):
        for roi in script.CONFIG["primary_rois"]:
            selected = rows[(rows.method == method) & (rows.roi == roi)]
            cue0 = selected[selected.trigger_code == script.CONFIG["codes"][0]].sort_values("participant_id")
            cue1 = selected[selected.trigger_code == script.CONFIG["codes"][1]].sort_values("participant_id")
            np.testing.assert_allclose(cue0.pooled_raw_amplitude_uv, bases - .3 + .01 * np.arange(5), atol=2e-15)
            np.testing.assert_allclose(cue1.pooled_raw_amplitude_uv, bases + .3, atol=2e-15)
            np.testing.assert_allclose(cue0.background_mean_amplitude_uv, bases, atol=2e-15)
            np.testing.assert_allclose(cue1.background_mean_amplitude_uv, bases + .8, atol=2e-15)
            np.testing.assert_allclose(cue0.background_corrected_amplitude_uv, -.3 + .01 * np.arange(5), atol=2e-15)
            np.testing.assert_allclose(cue1.background_corrected_amplitude_uv, -.5, atol=2e-15)
            stats = statistics[(statistics.method == method) & (statistics.comparison == roi)]
            assert stats.N.eq(5).all() and stats.df.eq(4).all()
            corrected = stats[stats.metric == "background_corrected_amplitude_uv"].iloc[0]
            raw = stats[stats.metric == "pooled_raw_amplitude_uv"].iloc[0]
            assert corrected.mean_change_uv == pytest.approx(changes.mean())
            assert corrected.t_statistic == pytest.approx(changes.mean() / (changes.std(ddof=1) / np.sqrt(5)))
            assert raw.mean_change_uv == pytest.approx(-.58)
    assert (rows.background_corrected_amplitude_uv < 0).all()


@pytest.mark.parametrize("problem", ["duplicate_participant", "one_participant", "missing_code", "grid", "negative", "missing_channel"])
def test_invalid_cache_arrays_are_rejected(script, problem):
    data = synthetic_dataset(script)
    if problem == "duplicate_participant":
        data["participant_ids"][1] = data["participant_ids"][0]
    elif problem == "one_participant":
        data["participant_ids"] = data["participant_ids"][:1]
        for key in ("coherent_amplitude_uv", "phase_insensitive_amplitude_uv"):
            data[key] = data[key][:1]
    elif problem == "missing_code":
        data["trigger_codes"][0] = 99
    elif problem == "grid":
        data["frequencies_hz"][127] += .01
    elif problem == "negative":
        data["coherent_amplitude_uv"][0, 0, 0, 0] = -1
    else:
        data["channel_names"][0] = "NotAnElectrode"
    with pytest.raises(ValueError):
        script.validate_dataset(data)


@pytest.mark.parametrize("problem", ["method", "parameters", "counts"])
def test_cache_processing_provenance_must_match(script, tmp_path, problem):
    data = synthetic_dataset(script)
    metadata = {"processing_method": script.RAW_PROCESSING_METHOD,
                "parameters": json.loads(json.dumps(script.RAW_PARAMETERS)),
                "trial_counts": {pid: {str(c): 30 for c in script.CONFIG["codes"]} for pid in data["participant_ids"]}}
    if problem == "method":
        metadata["processing_method"] = "old_method"
    elif problem == "parameters":
        metadata["parameters"]["crop_start_seconds"] = 0
    else:
        metadata["trial_counts"][str(data["participant_ids"][0])][str(script.CONFIG["codes"][0])] = 29
    data["capture_metadata_json"] = np.asarray(json.dumps(metadata))
    cache = tmp_path / "spectra.npz"
    np.savez_compressed(cache, **data)
    with pytest.raises(ValueError):
        script._load_cache(cache)


def test_new_runs_preserve_prior_outputs(script, tmp_path):
    first = script._new_run_folder(tmp_path)
    sentinel = first / "earlier.txt"
    sentinel.write_text("keep", encoding="utf-8")
    second = script._new_run_folder(tmp_path)
    assert first != second and second.is_dir()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_pycharm_no_argument_entry_selects_folders(script, tmp_path, monkeypatch):
    source = tmp_path / "bdf"
    source.mkdir()
    destination = tmp_path / "results"
    choices = iter([source, destination])
    monkeypatch.setattr(script, "_choose_directory", lambda title: next(choices))
    monkeypatch.setattr(script, "_capture_bdfs", lambda *args: (synthetic_dataset(script), {}))
    monkeypatch.setattr(script, "analyze_and_export", lambda *args: None)
    output = script.main([])
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and manifest["participant_count"] == 5


def test_cancelled_run_is_not_left_running(script, tmp_path, monkeypatch):
    def cancel(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(script, "_load_cache", cancel)
    with pytest.raises(KeyboardInterrupt):
        script.main(["--cache", str(tmp_path / "unused.npz"), "--output", str(tmp_path / "out")])
    manifest = next((tmp_path / "out").glob("*/run_manifest.json"))
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "cancelled"


def test_all_four_standalone_files_embed_identical_recording_method():
    sections = []
    for name in ALL_SCRIPTS:
        source = (ROOT / "research" / (name + ".py")).read_text(encoding="utf-8")
        assert "from sssep_batch" not in source and "import sssep_batch" not in source
        sections.append(source.split("# BEGIN EMBEDDED RECORDING METHOD\n", 1)[1].split("# END EMBEDDED RECORDING METHOD", 1)[0])
        assert source.index('os.environ[_thread_variable] = "1"') < source.index("import mne")
    assert all(section == sections[0] for section in sections[1:])
