"""FPVS-equivalent preprocessing and amplitude FFT on SSSEP trials.

SSSEP onset codes and trial durations remain experiment-specific. Preprocessing
and each electrode's amplitude FFT follow the pinned FPVS reference.
"""

import traceback
from pathlib import Path

from sssep_batch.analysis.metrics import add_baseline_comparison, extract_target_metrics
from sssep_batch.analysis.plotting import plot_spectrum
from sssep_batch.analysis.protocol import default_analysis_protocol
from sssep_batch.analysis.spectra import compute_sssep_fft_from_averaged_epochs
from sssep_batch.config import (
    DOWNSAMPLE_RATE, FPVS_REFERENCE_COMMIT, HIGHCUT, INCLUDE_POST_STIMULUS, LOWCUT,
    POST_EVENT_SEC_IF_INCLUDED, PRE_EVENT_SEC, PLOT_CHANNEL, PROCESSING_METHOD,
    SAVE_PLOTS,
)
from sssep_batch.events.epochs import extract_epochs_for_code
from sssep_batch.events.status import find_status_events, parse_trigger_label
from sssep_batch.loading import load_bdf
from sssep_batch.logging_utils import ensure_folder, make_file_log_func
from sssep_batch.models import AnalysisProtocol, ParticipantSpectrum
from sssep_batch.outputs import write_error_report, write_processing_report, write_summary_csv
from sssep_batch.preprocess.bad_channels import detect_and_interpolate_bad_channels_by_kurtosis
from sssep_batch.preprocess.channels import (
    apply_biosemi_montage, apply_exg_reference_and_drop,
    apply_final_average_reference, get_fft_channels, get_scalp_channels,
    keep_scalp_and_status_channels, set_known_channel_types,
    validate_analysis_channels,
)
from sssep_batch.preprocess.filtering import (
    apply_basic_fir_filter, downsample_if_needed, validate_filter_settings,
)


def process_one_bdf(
    bdf_file: str | Path,
    output_root: str | Path,
    plot_channel: str = PLOT_CHANNEL,
    analysis_protocol: AnalysisProtocol | None = None,
) -> dict[str, object]:
    """Process one recording into a fresh per-file directory within a batch run."""
    bdf_path = Path(bdf_file)
    file_stem = bdf_path.stem
    output_folder = Path(output_root) / file_stem
    # Direct callers must not mix previous results into a rerun either.
    output_folder.mkdir(parents=True, exist_ok=False)
    plots_dir = output_folder / "plots"
    report_lines: list[str] = []
    log_func = make_file_log_func(report_lines)
    stage = "loading_bdf"

    try:
        stage = "validating_analysis_protocol"
        protocol = analysis_protocol or default_analysis_protocol()
        if not isinstance(protocol, AnalysisProtocol):
            raise RuntimeError("analysis_protocol must be an AnalysisProtocol value.")

        stage = "validating_plot_channel"
        if not isinstance(plot_channel, str) or not plot_channel.strip():
            raise RuntimeError(
                "The FFT plot electrode must be a channel label such as 'Cz', 'C3', or 'C4'."
            )
        plot_channel = plot_channel.strip()

        stage = "loading_bdf"
        log_func(f"Processing: {bdf_path.name}")
        log_func(f"Method: {PROCESSING_METHOD}; FPVS reference: {FPVS_REFERENCE_COMMIT}")
        raw = load_bdf(bdf_path)
        original_sfreq = float(raw.info["sfreq"])
        log_func(f"Loaded {len(raw.ch_names)} channels at {original_sfreq:g} Hz.")

        stage = "validating_channels"
        scalp_channels = get_scalp_channels(raw)
        set_known_channel_types(raw, scalp_channels, log_func)
        apply_biosemi_montage(raw, log_func)

        stage = "referencing_and_channel_selection"
        apply_exg_reference_and_drop(raw, bdf_path.name, log_func)
        keep_scalp_and_status_channels(raw, scalp_channels, bdf_path.name, log_func)

        stage = "filter_validation"
        validate_filter_settings(float(raw.info["sfreq"]))
        stage = "basic_fir_filtering"
        filter_info = apply_basic_fir_filter(
            raw, bdf_path.name, hp=LOWCUT, lp=HIGHCUT, log_func=log_func,
        )
        stage = "downsampling"
        downsample_if_needed(
            raw, bdf_path.name, downsample_rate=DOWNSAMPLE_RATE,
            log_func=log_func, filter_info_to_preserve=filter_info,
        )

        stage = "kurtosis_bad_channel_detection"
        bad_metrics = detect_and_interpolate_bad_channels_by_kurtosis(
            raw, bdf_path.name, output_folder, log_func,
        )
        n_bad = int(bad_metrics["bad_by_kurtosis"].sum()) if not bad_metrics.empty else 0
        stage = "final_average_reference"
        apply_final_average_reference(raw, bdf_path.name, log_func)

        # Match FPVS's event detection on the final sampling grid.
        stage = "status_event_detection"
        _, intended_events, found_codes = find_status_events(
            raw, bdf_path.name, output_folder, log_func,
            active_event_codes=protocol.active_event_codes,
            baseline_event_code=protocol.baseline_event_code,
        )

        stage = "analysis_channel_validation"
        requested_analysis_channels = validate_analysis_channels(raw)
        fft_channels = get_fft_channels(raw)
        # FPVS's Epochs export excludes bads remaining after failed interpolation.
        analysis_channels = [ch for ch in requested_analysis_channels if ch in fft_channels]
        if not analysis_channels:
            raise RuntimeError("No good configured analysis channels remain for FFT summaries.")
        plot_channel_available = plot_channel in fft_channels
        channel_indices = [fft_channels.index(ch) for ch in analysis_channels]
        log_func(f"FFT electrodes ({len(fft_channels)}): {fft_channels}")
        log_func(f"Amplitude summary electrodes ({len(analysis_channels)}): {analysis_channels}")
        if SAVE_PLOTS and plot_channel_available:
            log_func(f"Amplitude plot electrode: {plot_channel}")
        elif SAVE_PLOTS:
            log_func(
                f"WARNING: Plot electrode {plot_channel!r} is unavailable or remains "
                "marked bad in this recording. FFT tables and summaries will be "
                "saved, but PNG plots will be skipped for this file."
            )

        post_sec = POST_EVENT_SEC_IF_INCLUDED if INCLUDE_POST_STIMULUS else 0.0
        window_sec = PRE_EVENT_SEC + protocol.event_duration_sec + post_sec
        stage = "baseline_epoch_extraction"
        baseline_epochs = extract_epochs_for_code(
            raw,
            intended_events,
            protocol.baseline_event_code,
            fft_channels,
            window_sec,
            label=protocol.baseline_label,
        )
        baseline_fft = (
            compute_sssep_fft_from_averaged_epochs(baseline_epochs.epochs, float(raw.info["sfreq"]))
            if len(baseline_epochs.epochs) else None
        )
        if baseline_fft is None:
            log_func("WARNING: No complete baseline epochs; baseline amplitudes/ratios are unavailable.")

        stage = "active_sssep_analysis"
        summary_rows = []
        participant_spectra: list[ParticipantSpectrum] = []
        if baseline_fft is not None:
            participant_spectra.append(
                ParticipantSpectrum(
                    participant_id=file_stem,
                    file_name=bdf_path.name,
                    event_type="baseline",
                    trigger_code=protocol.baseline_event_code,
                    trigger_label=protocol.baseline_label,
                    target_hz=None,
                    usable_epochs=len(baseline_epochs.epochs),
                    channel_names=tuple(fft_channels),
                    analysis_channels=tuple(analysis_channels),
                    spectrum=baseline_fft,
                    sampling_rate_hz=float(raw.info["sfreq"]),
                    analysis_window_sec=window_sec,
                )
            )
        plotted = 0
        plot_failures = 0
        for trigger in protocol.active_triggers:
            code = trigger.code
            label = trigger.label
            condition, finger = parse_trigger_label(label)
            target_hz = trigger.target_hz
            epoch_set = extract_epochs_for_code(
                raw,
                intended_events,
                code,
                fft_channels,
                window_sec,
                label=label,
            )
            n_epochs = len(epoch_set.epochs)
            count_ok = n_epochs == protocol.expected_repetitions_per_trigger
            if not count_ok:
                log_func(
                    f"WARNING: Trigger {code} ({label}) expected "
                    f"{protocol.expected_repetitions_per_trigger} epochs; found {n_epochs}."
                )
            row = {
                "file_name": bdf_path.name, "processing_method": PROCESSING_METHOD,
                "fpvs_reference_commit": FPVS_REFERENCE_COMMIT,
                "trigger_code": code, "trigger_label": label,
                "condition": condition, "finger": finger,
                "expected_frequency_hz": target_hz,
                "expected_repetitions": protocol.expected_repetitions_per_trigger,
                "usable_epochs": n_epochs, "skipped_epochs": epoch_set.skipped_epochs,
                "out_of_bounds_epochs": epoch_set.out_of_bounds_epochs,
                "edge_excluded_epochs": 0, "epoch_count_ok": count_ok,
                "analysis_window_sec": window_sec,
                "include_post_stimulus": INCLUDE_POST_STIMULUS,
                "sampling_rate_hz": float(raw.info["sfreq"]),
                "analysis_channels": ";".join(analysis_channels),
                "fft_channels": ";".join(fft_channels),
                "baseline_trigger_code": protocol.baseline_event_code,
                "baseline_usable_epochs": len(baseline_epochs.epochs),
                "baseline_skipped_epochs": baseline_epochs.skipped_epochs,
                "baseline_out_of_bounds_epochs": baseline_epochs.out_of_bounds_epochs,
                "baseline_edge_excluded_epochs": 0,
                "fir_edge_margin_samples": 0, "fir_edge_margin_sec": 0.0,
                "status": "success" if n_epochs else "no_complete_epochs",
            }
            spectrum = (
                compute_sssep_fft_from_averaged_epochs(epoch_set.epochs, float(raw.info["sfreq"]))
                if n_epochs else None
            )
            metrics = extract_target_metrics(spectrum, target_hz, channel_indices)
            row.update({f"sssep_fft_{key}": value for key, value in metrics.items()})
            baseline_metrics = (
                extract_target_metrics(baseline_fft, target_hz, channel_indices)
                if baseline_fft is not None else None
            )
            add_baseline_comparison(row, "sssep_fft", baseline_metrics)
            summary_rows.append(row)
            if spectrum is None:
                continue

            participant_spectra.append(
                ParticipantSpectrum(
                    participant_id=file_stem,
                    file_name=bdf_path.name,
                    event_type="cue",
                    trigger_code=code,
                    trigger_label=label,
                    target_hz=target_hz,
                    usable_epochs=n_epochs,
                    channel_names=tuple(fft_channels),
                    analysis_channels=tuple(analysis_channels),
                    spectrum=spectrum,
                    sampling_rate_hz=float(raw.info["sfreq"]),
                    analysis_window_sec=window_sec,
                )
            )
            if SAVE_PLOTS and plot_channel_available:
                try:
                    ensure_folder(plots_dir)
                    output_stem = f"{file_stem}_cue_{code:03d}_fft_amplitude"
                    plot_spectrum(
                        active=spectrum, baseline=baseline_fft,
                        title=f"{file_stem} - Cue {code} {label} - FFT amplitude",
                        outpath=plots_dir / f"{output_stem}.png", target_hz=target_hz,
                        channel_names=fft_channels, plot_channel=plot_channel,
                        active_label=f"Cue average ({n_epochs} epochs)",
                        baseline_label=(
                            f"Gap/Break average ({len(baseline_epochs.epochs)} epochs)"
                        ),
                    )
                except Exception as exc:
                    plot_failures += 1
                    message = str(exc) or type(exc).__name__
                    log_func(
                        f"WARNING: Participant plot skipped for trigger {code} "
                        f"({label}) after a plotting error: {message}"
                    )
                else:
                    plotted += 1

        log_func(
            f"Created {plotted} participant amplitude plot(s), one per usable cue; "
            f"{plot_failures} plot(s) failed."
        )
        stage = "saving_outputs"
        summary_path = write_summary_csv(output_folder, file_stem, summary_rows)
        report_path = output_folder / f"{file_stem}_processing_report.txt"
        log_func(f"Done with: {bdf_path.name}")
        log_func(f"Summary CSV saved to: {summary_path}")
        log_func(f"Processing report saved to: {report_path}")
        write_processing_report(
            report_path=report_path, bdf_path=bdf_path,
            original_sfreq=original_sfreq, final_sfreq=float(raw.info["sfreq"]),
            n_bad_by_kurtosis=n_bad, found_codes=found_codes,
            analysis_window_sec=window_sec, filter_edge_margin_samples=0,
            filter_edge_margin_sec=0.0, analysis_channels=analysis_channels,
            report_lines=report_lines, summary_rows=summary_rows,
            summary_csv_path=summary_path,
            active_event_codes=protocol.active_event_codes,
            baseline_event_code=protocol.baseline_event_code,
        )
        if not any(row["status"] == "success" for row in summary_rows):
            raise RuntimeError("No usable active-condition epochs. See the event summary for counts.")
        return {
            "file_name": bdf_path.name, "status": "success",
            "processing_method": PROCESSING_METHOD,
            "output_folder": str(output_folder), "summary_csv": str(summary_path),
            "original_sfreq_hz": original_sfreq,
            "final_sfreq_hz": float(raw.info["sfreq"]),
            "bad_channels_by_kurtosis": n_bad,
            "participant_plot_count": plotted,
            "participant_plot_failures": plot_failures,
            "_participant_spectra": tuple(participant_spectra),
        }
    except Exception as exc:
        error_path = output_folder / "ERROR.txt"
        write_error_report(
            error_path, bdf_path, stage, exc, traceback.format_exc(), report_lines,
        )
        return {
            "file_name": bdf_path.name, "status": "failed", "failed_stage": stage,
            "output_folder": str(output_folder), "error": str(exc),
            "error_file": str(error_path), "processing_method": PROCESSING_METHOD,
        }
