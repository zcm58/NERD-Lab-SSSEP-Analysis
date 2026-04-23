from pathlib import Path

import numpy as np
import pandas as pd

from sssep_batch.models import EpochSet, Spectrum
from sssep_batch.pipeline import process_one_bdf


class _RawStub:
    def __init__(self) -> None:
        self.info = {"sfreq": 256.0}
        self.ch_names = ["Cz", "Pz", "Status"]
        self.times = np.linspace(0.0, 9.0, 10)


class _CsvStub:
    def __init__(self, counter: list[Path]) -> None:
        self.counter = counter

    def to_csv(self, path: Path, index: bool = False) -> None:
        self.counter.append(path)


def test_process_one_bdf_enforces_max_individual_plots(monkeypatch, tmp_path):
    import sssep_batch.pipeline as pipeline

    raw = _RawStub()
    report_capture: dict[str, object] = {}
    plot_calls: list[Path] = []
    csv_calls: list[Path] = []
    summary_rows_capture: list[dict[str, object]] = []

    monkeypatch.setattr(pipeline.mne.io, "read_raw_bdf", lambda *args, **kwargs: raw)
    monkeypatch.setattr(pipeline, "ACTIVE_EVENT_CODES", [1, 2, 3, 4])
    monkeypatch.setattr(pipeline, "TRIGGER_LABELS", {1: "Think Thumb", 2: "Think Index", 3: "Think Middle", 4: "Think Ring"})
    monkeypatch.setattr(pipeline, "TRIGGER_HZ_MAP", {1: 10.0, 2: 17.0, 3: 23.0, 4: 34.0})
    monkeypatch.setattr(pipeline, "MAX_INDIVIDUAL_PLOTS", 2)
    monkeypatch.setattr(pipeline, "EXPECTED_REPETITIONS_PER_TRIGGER", 5)
    monkeypatch.setattr(pipeline, "SAVE_PLOTS", True)
    monkeypatch.setattr(pipeline, "SAVE_CSV_SUMMARIES", True)
    monkeypatch.setattr(pipeline, "get_scalp_channels", lambda raw_obj: ["Cz", "Pz"])
    monkeypatch.setattr(pipeline, "require_channels", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "set_known_channel_types", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "apply_exg_reference_and_drop", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "keep_scalp_and_status_channels", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "apply_biosemi_montage", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "find_status_events",
        lambda **kwargs: (
            np.array([[10, 0, 1]], dtype=int),
            np.array([[10, 0, 1]], dtype=int),
            [1, 2, 3, 4],
        ),
    )
    monkeypatch.setattr(pipeline, "downsample_if_needed", lambda **kwargs: kwargs["events"])
    monkeypatch.setattr(pipeline, "validate_filter_settings", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "replace_nonfinite_values", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "apply_basic_fir_filter", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "apply_notch_filter", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "get_fir_edge_margin_samples", lambda **kwargs: 0)
    monkeypatch.setattr(pipeline, "detect_and_interpolate_bad_channels_by_kurtosis", lambda **kwargs: pd.DataFrame({"bad_by_kurtosis": [False, False]}))
    monkeypatch.setattr(pipeline, "validate_analysis_channels", lambda raw_obj: ["Cz", "Pz"])

    def fake_extract_epochs_for_code(*, code: int, picks: list[str], window_sec: float, **kwargs):
        epochs = np.ones((5, len(picks), 8), dtype=float)
        return EpochSet(
            code=code,
            label=f"Trigger {code}",
            epochs=epochs,
            skipped_epochs=0,
            out_of_bounds_epochs=0,
            edge_excluded_epochs=0,
        )

    monkeypatch.setattr(pipeline, "extract_epochs_for_code", fake_extract_epochs_for_code)
    monkeypatch.setattr(
        pipeline,
        "compute_sssep_fft_from_averaged_epochs",
        lambda *args, **kwargs: Spectrum(
            freqs=np.array([10.0, 17.0]),
            power=np.array([1.0, 0.5]),
            method="fft",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "compute_welch_psd_average",
        lambda *args, **kwargs: Spectrum(
            freqs=np.array([10.0, 17.0]),
            power=np.array([1.0, 0.5]),
            method="welch",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_target_metrics",
        lambda spectrum, target_hz: {
            "nearest_power": 1.0,
            "target_band_sum_power": 2.0,
        },
    )
    monkeypatch.setattr(pipeline, "add_baseline_comparison", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "spectrum_to_dataframe", lambda *args, **kwargs: _CsvStub(csv_calls))
    monkeypatch.setattr(pipeline, "plot_spectrum", lambda **kwargs: plot_calls.append(kwargs["outpath"]))
    monkeypatch.setattr(
        pipeline,
        "write_summary_csv",
        lambda output_folder, file_stem, summary_rows: (
            summary_rows_capture.extend(summary_rows) or (Path(output_folder) / f"{file_stem}_summary.csv")
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "write_processing_report",
        lambda **kwargs: report_capture.update(kwargs),
    )

    result = process_one_bdf(tmp_path / "synthetic.bdf", tmp_path)

    assert result["status"] == "success"
    assert len(summary_rows_capture) == 4
    assert len(csv_calls) == 8
    assert len(plot_calls) == 4
    assert any("MAX_INDIVIDUAL_PLOTS=2" in line for line in report_capture["report_lines"])
