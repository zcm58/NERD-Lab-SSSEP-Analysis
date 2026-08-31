"""Optional exact comparisons against the pinned, unmodified FPVS source.

Set FPVS_REFERENCE_ROOT to the Toolbox checkout. Actual BDFs, the Toolbox's
loader/preprocessor, and FFT expressions extracted from its AST are exercised.
Its visual-oddball crop is intentionally replaced by this experiment's SSSEP
windows. No FPVS GUI, QC workflow, or participant data is needed.
"""

import ast
import hashlib
import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import mne
import numpy as np
import pandas as pd
import pytest

from sssep_batch import config, pipeline
from sssep_batch.preprocess import bad_channels
from test_bdf_end_to_end import write_synthetic_bdf


REFERENCE_HASHES = {
    "Main_App/processing/preprocess.py": "5200fbb68675fb3c2f8299f97a634382da4031331a4c636f6a12d74e453a6526",
    "Main_App/Shared/load_utils.py": "11f2d04a9b3d90e35442102fa00f29b94c2a349ecdaa4354978b088f2b07a284",
    "Main_App/Shared/post_process.py": "2535ae764b8c85afdf2dca64a3ac2a3e292d513e3225560f8fdf05476a95c714",
    "Main_App/Performance/process_runner.py": "f926e5b81036393c964e68c67daad2f431903ce1737927b27d94551ffa668aa5",
}


@pytest.fixture
def fpvs_source(monkeypatch, tmp_path):
    location = os.environ.get("FPVS_REFERENCE_ROOT")
    if not location:
        pytest.skip("Set FPVS_REFERENCE_ROOT to compare against actual FPVS source.")
    src = Path(location) / "src"
    for relative, expected_hash in REFERENCE_HASHES.items():
        source = (src / relative).read_text(encoding="utf-8")
        assert hashlib.sha256(source.encode()).hexdigest() == expected_hash, (
            f"Reference source changed: {relative}; review before updating the parity contract."
        )
    monkeypatch.syspath_prepend(str(src))
    loader = importlib.import_module("Main_App.Shared.load_utils")
    preprocess = importlib.import_module("Main_App.processing.preprocess")
    # Isolate reference memmaps in this test; never write to the reference repo.
    memmap_dir = tmp_path / "reference_memmap"
    memmap_dir.mkdir()
    monkeypatch.setattr(loader, "_memmap_dir_for_pid", lambda: memmap_dir)
    return SimpleNamespace(src=src, loader=loader, preprocess=preprocess)


def reference_fft_from_source(source_path, epochs, sfreq):
    """Execute the actual reference assignments, without its experiment's crop."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    assignments = []
    for name in (
        "avg_data", "avg_data_uv", "num_fft_bins", "fft_frequencies",
        "fft_full_spectrum", "fft_amplitudes",
    ):
        matches = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
            and (name != "avg_data" or "np.mean(ep_data.astype(np.float64)" in ast.unparse(node.value))
        ]
        assert len(matches) == 1, f"Ambiguous reference FFT expression: {name}"
        assignments.append(matches[0])
    namespace = {"np": np, "ep_data": epochs, "sfreq": sfreq, "num_times": epochs.shape[-1]}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace["fft_frequencies"], namespace["fft_amplitudes"]


@pytest.mark.parametrize("sfreq,mode", [(256, "clean"), (512, "automatic_bad"), (2048, "manual_bad"), (512, "disabled")])
def test_bdf_pipeline_is_exactly_equal_to_fpvs(fpvs_source, tmp_path, monkeypatch, sfreq, mode):
    path = tmp_path / f"synthetic_{sfreq}_{mode}.bdf"
    write_synthetic_bdf(path, sfreq)
    log = []
    app = SimpleNamespace(log=lambda message, **_: log.append(message))
    reference_raw = fpvs_source.loader.load_eeg_file(
        app, str(path), ref_pair=config.REFERENCE_CHANNELS, first_n_channels=64,
    )
    assert reference_raw is not None, log
    sssep_raw = pipeline.load_bdf(path)

    def add_bad(raw):
        if mode == "automatic_bad":
            raw._data[0, int(30 * sfreq)] += 0.1
        elif mode in {"manual_bad", "disabled"}:
            raw.info["bads"] = ["Cz"]

    add_bad(reference_raw)
    add_bad(sssep_raw)
    threshold = 0 if mode == "disabled" else config.KURTOSIS_REJECT_Z
    monkeypatch.setattr(bad_channels, "KURTOSIS_REJECT_Z", threshold)
    params = {
        "high_pass": config.LOWCUT, "low_pass": config.HIGHCUT,
        "downsample_rate": config.DOWNSAMPLE_RATE, "reject_thresh": threshold,
        "ref_channel1": config.REFERENCE_CHANNELS[0],
        "ref_channel2": config.REFERENCE_CHANNELS[1],
        "max_idx_keep": 64, "stim_channel": config.STIM_CHANNEL,
    }
    reference_raw, reference_n_bad = fpvs_source.preprocess.perform_preprocessing(
        reference_raw, params, log.append, path.name,
    )
    assert reference_raw is not None, log
    if mode == "automatic_bad":
        assert reference_n_bad > 0  # Ensure this comparison really exercises interpolation.
    assert reference_raw.info["bads"] == (["Cz"] if mode == "disabled" else [])
    reference_events = mne.find_events(
        reference_raw, stim_channel=config.STIM_CHANNEL, shortest_event=1, verbose=False,
    )

    find_events = pipeline.find_status_events
    extract_epochs = pipeline.extract_epochs_for_code
    compute_fft = pipeline.compute_sssep_fft_from_averaged_epochs
    captured_spectra = []
    checked_preprocessing = []

    def compare_preprocessed(raw, *args, **kwargs):
        assert raw.ch_names == reference_raw.ch_names
        assert raw.get_channel_types() == reference_raw.get_channel_types()
        assert raw.info["sfreq"] == reference_raw.info["sfreq"]
        assert raw.info["bads"] == reference_raw.info["bads"]
        assert raw.info["highpass"] == reference_raw.info["highpass"]
        assert raw.info["lowpass"] == reference_raw.info["lowpass"]
        np.testing.assert_array_equal(raw.get_data(), reference_raw.get_data())
        events = find_events(raw, *args, **kwargs)
        np.testing.assert_array_equal(events[0], reference_events)
        checked_preprocessing.append(True)
        return events

    def compare_epochs(raw, events, code, picks, window_sec, **kwargs):
        actual = extract_epochs(raw, events, code, picks, window_sec, **kwargs)
        n_times = round(window_sec * reference_raw.info["sfreq"])
        starts = reference_events[reference_events[:, 2] == code, 0] - reference_raw.first_samp
        expected = [reference_raw.get_data(start=int(start), stop=int(start + n_times))
                    for start in starts if 0 <= start and start + n_times <= reference_raw.n_times]
        if expected:
            # The active FPVS runner constructs EpochsArray with baseline=None;
            # verify this step as well, including its projector state.
            reference_epochs = mne.EpochsArray(
                np.stack(expected), reference_raw.info.copy(), tmin=0.0,
                baseline=None, verbose=False,
            ).pick("eeg", exclude="bads").pick(picks)
            np.testing.assert_array_equal(actual.epochs, reference_epochs.get_data())
        else:
            assert len(actual.epochs) == 0
        return actual

    def compare_fft(epochs, final_sfreq):
        actual = compute_fft(epochs, final_sfreq)
        frequencies, amplitudes = reference_fft_from_source(
            fpvs_source.src / "Main_App/Shared/post_process.py", epochs, final_sfreq,
        )
        np.testing.assert_array_equal(actual.freqs, frequencies)
        np.testing.assert_array_equal(actual.amplitude_uv, amplitudes)
        captured_spectra.append(actual)
        return actual

    monkeypatch.setattr(pipeline, "load_bdf", lambda _: sssep_raw)
    monkeypatch.setattr(pipeline, "find_status_events", compare_preprocessed)
    monkeypatch.setattr(pipeline, "extract_epochs_for_code", compare_epochs)
    monkeypatch.setattr(pipeline, "compute_sssep_fft_from_averaged_epochs", compare_fft)
    monkeypatch.setattr(pipeline, "SAVE_PLOTS", False)
    try:
        result = pipeline.process_one_bdf(path, tmp_path / "results")
        if result["status"] != "success":
            pytest.fail(Path(result["error_file"]).read_text(encoding="utf-8"))
        assert checked_preprocessing == [True]
        assert result["bad_channels_by_kurtosis"] == reference_n_bad
        assert len(captured_spectra) == 5  # Baseline plus four present active conditions.
        summary = pd.read_csv(result["summary_csv"])
        fft_channels = summary.iloc[0]["fft_channels"].split(";")
        outputs = sorted(Path(result["output_folder"]).rglob("*_sssep_fft_amplitude.csv"))
        for csv_path, expected in zip(outputs, captured_spectra[1:], strict=True):
            frame = pd.read_csv(csv_path, float_precision="round_trip")
            np.testing.assert_array_equal(frame["frequency_hz"], expected.freqs)
            np.testing.assert_array_equal(
                frame[[f"active_{channel}_amplitude_uv" for channel in fft_channels]].to_numpy().T,
                expected.amplitude_uv,
            )
    finally:
        reference_raw.close()
        sssep_raw.close()
