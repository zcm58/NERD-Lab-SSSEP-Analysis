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


@pytest.fixture(params=SCRIPTS)
def script(request):
    spec = spec_from_file_location(request.param, ROOT / "research" / (request.param + ".py"))
    module = module_from_spec(spec)
    sys.modules[request.param] = module
    spec.loader.exec_module(module)
    return module


def synthetic_dataset(script, n=5):
    """A cue's broadband increase hides its opposite narrow-band change."""
    frequencies = np.fft.rfftfreq(1280, 1 / 256)
    channels = mne.channels.make_standard_montage("biosemi64").ch_names
    values = np.empty((n, 2, 64, len(frequencies)))
    signal = (frequencies >= 25 - 1e-9) & (frequencies <= 27 + 1e-9)
    for pi in range(n):
        base = 1 + pi * .2
        values[pi, 0] = base
        values[pi, 1] = base + .8
        values[pi, 0, :, signal] = base - .3 + .01 * pi
        values[pi, 1, :, signal] = base + .8 - .5
    return {"participant_ids": np.asarray([f"Synthetic{pi}" for pi in range(n)]),
            "trigger_codes": np.asarray(script.CONFIG["codes"]),
            "channel_names": np.asarray(channels), "frequencies_hz": frequencies,
            "coherent_amplitude_uv": values.copy(), "phase_insensitive_amplitude_uv": values.copy()}


def test_pooled_background_subtraction_retains_negative_values_and_pairing(script, tmp_path, monkeypatch):
    dataset = synthetic_dataset(script)
    # Raster integrity/layout are checked on real-data exports; this checks calculations.
    monkeypatch.setattr(script.plt.Figure, "savefig", lambda *args, **kwargs: None)
    result = script.analyze_and_export(dataset, script.CONFIG, tmp_path)
    assert result["N"] == 5
    assert len(result["signal_bins_hz"]) == 11
    assert len(result["background_bins_hz"]) == 16
    assert not set(result["signal_bins_hz"]) & set(result["background_bins_hz"])
    values = pd.read_csv(tmp_path / "participant_pooled_values.csv")
    assert (values.background_corrected_amplitude_uv < 0).all()
    primary = script.CONFIG["primary_rois"][0]
    rows = values[(values.method == "phase_insensitive") & (values.roi == primary)]
    cue0 = rows[rows.trigger_code == script.CONFIG["codes"][0]].sort_values("participant_id")
    cue1 = rows[rows.trigger_code == script.CONFIG["codes"][1]].sort_values("participant_id")
    np.testing.assert_allclose(cue0.background_corrected_amplitude_uv, -.3 + .01 * np.arange(5), atol=2e-15)
    np.testing.assert_allclose(cue1.background_corrected_amplitude_uv, -.5, atol=2e-15)
    stats = pd.read_csv(tmp_path / "paired_statistics_uncorrected.csv")
    stats = stats[(stats.method == "phase_insensitive") & (stats.comparison == primary)]
    assert stats.N.eq(5).all() and stats.df.eq(4).all()
    corrected = stats[stats.metric == "background_corrected_amplitude_uv"].iloc[0]
    raw = stats[stats.metric == "pooled_raw_amplitude_uv"].iloc[0]
    assert corrected.mean_change_uv == pytest.approx(.22)
    assert raw.mean_change_uv == pytest.approx(-.58)


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


def test_both_standalone_files_embed_identical_recording_method():
    sections = []
    for name in SCRIPTS:
        source = (ROOT / "research" / (name + ".py")).read_text(encoding="utf-8")
        assert "from sssep_batch" not in source and "import sssep_batch" not in source
        sections.append(source.split("# BEGIN EMBEDDED RECORDING METHOD\n", 1)[1].split("# END EMBEDDED RECORDING METHOD", 1)[0])
        assert source.index('os.environ[_thread_variable] = "1"') < source.index("import mne")
    assert sections[0] == sections[1]
