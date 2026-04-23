"""Per-file SSSEP processing pipeline."""

import traceback
from pathlib import Path

from sssep_batch.analysis.metrics import add_baseline_comparison, extract_target_metrics
from sssep_batch.analysis.plotting import plot_spectrum, spectrum_to_dataframe
from sssep_batch.analysis.spectra import (
    compute_sssep_fft_from_averaged_epochs,
    compute_welch_psd_average,
)
from sssep_batch.config import (
    ACTIVE_EVENT_CODES,
    BASELINE_EVENT_CODE,
    DOWNSAMPLE_RATE,
    EVENT_DURATION_SEC,
    EXPECTED_REPETITIONS_PER_TRIGGER,
    FMAX,
    FMIN,
    HIGHCUT,
    INCLUDE_POST_STIMULUS,
    LOWCUT,
    MAX_INDIVIDUAL_PLOTS,
    PRE_EVENT_SEC,
    POST_EVENT_SEC_IF_INCLUDED,
    SAVE_CSV_SUMMARIES,
    SAVE_PLOTS,
    TRIGGER_HZ_MAP,
    TRIGGER_LABELS,
)
from sssep_batch.events.epochs import extract_epochs_for_code
from sssep_batch.events.status import find_status_events, parse_trigger_label
from sssep_batch.logging_utils import ensure_folder, make_file_log_func
from sssep_batch.outputs import write_error_report, write_processing_report, write_summary_csv
from sssep_batch.preprocess.bad_channels import detect_and_interpolate_bad_channels_by_kurtosis
from sssep_batch.preprocess.channels import (
    apply_biosemi_montage,
    apply_exg_reference_and_drop,
    get_scalp_channels,
    keep_scalp_and_status_channels,
    require_channels,
    set_known_channel_types,
    validate_analysis_channels,
)
from sssep_batch.preprocess.filtering import (
    apply_basic_fir_filter,
    apply_notch_filter,
    downsample_if_needed,
    get_fir_edge_margin_samples,
    replace_nonfinite_values,
    validate_filter_settings,
)

import mne


def process_one_bdf(
    bdf_file: str | Path,
    output_root: str | Path,
) -> dict[str, object]:
    """Process one BioSemi BDF file from loading through output saving."""

    bdf_path = Path(bdf_file)
    file_stem = bdf_path.stem
    output_folder = Path(output_root) / file_stem
    plots_dir = output_folder / "plots"
    ensure_folder(output_folder)
    ensure_folder(plots_dir)

    report_lines: list[str] = []
    log_func = make_file_log_func(report_lines)
    stage = "starting"

    try:
        log_func("=" * 78)
        log_func(f"Processing: {bdf_path.name}")
        log_func("=" * 78)

        stage = "loading_bdf"
        raw = mne.io.read_raw_bdf(str(bdf_path), preload=True, verbose=False)
        original_sfreq = float(raw.info["sfreq"])
        log_func(
            f"Loaded {bdf_path.name}: {len(raw.ch_names)} channels, "
            f"sfreq={original_sfreq:.3f} Hz, duration={raw.times[-1]:.2f} sec."
        )

        stage = "validating_channels"
        scalp_channels = get_scalp_channels(raw)
        require_channels(raw, ("EXG1", "EXG2"), "fixed EXG1/EXG2 reference")
        require_channels(raw, ["Status"], "BioSemi Status triggers")
        set_known_channel_types(raw, scalp_channels, log_func)

        stage = "referencing_and_channel_selection"
        apply_exg_reference_and_drop(raw, bdf_path.name, log_func)
        keep_scalp_and_status_channels(raw, scalp_channels, bdf_path.name, log_func)
        apply_biosemi_montage(raw, log_func)

        stage = "status_event_detection"
        _all_events, intended_events, found_codes = find_status_events(
            raw=raw,
            filename_for_log=bdf_path.name,
            output_folder=output_folder,
            log_func=log_func,
        )

        stage = "downsampling"
        intended_events = downsample_if_needed(
            raw=raw,
            filename_for_log=bdf_path.name,
            downsample_rate=DOWNSAMPLE_RATE,
            log_func=log_func,
            events=intended_events,
            debug_enabled=False,
        )
        final_sfreq_after_downsample = float(raw.info["sfreq"])
        if DOWNSAMPLE_RATE and original_sfreq > DOWNSAMPLE_RATE:
            if final_sfreq_after_downsample > DOWNSAMPLE_RATE + 1e-6:
                raise RuntimeError(
                    f"Downsampling was required, but final sampling rate is "
                    f"{final_sfreq_after_downsample:.3f} Hz."
                )

        stage = "filter_validation"
        validate_filter_settings(float(raw.info["sfreq"]))
        log_func(
            f"Filter validation passed: LOWCUT={LOWCUT} Hz, HIGHCUT={HIGHCUT} Hz, "
            f"targets={sorted(set(TRIGGER_HZ_MAP.values()))}."
        )

        stage = "finite_value_cleanup"
        replace_nonfinite_values(raw, log_func)

        stage = "basic_fir_filtering"
        apply_basic_fir_filter(
            raw=raw,
            filename_for_log=bdf_path.name,
            hp=LOWCUT,
            lp=HIGHCUT,
            log_func=log_func,
            debug_enabled=False,
        )
        apply_notch_filter(raw, bdf_path.name, log_func)
        filter_edge_margin_samples = get_fir_edge_margin_samples(
            sfreq=float(raw.info["sfreq"]),
            l_freq=LOWCUT,
            h_freq=HIGHCUT,
        )
        filter_edge_margin_sec = filter_edge_margin_samples / float(raw.info["sfreq"])
        log_func(
            "Epoch edge exclusion uses a conservative FIR margin of "
            f"{filter_edge_margin_samples} samples ({filter_edge_margin_sec:.3f} s) "
            "at both the start and end of the filtered recording. "
            "Reason: a fixed-length linear-phase FIR needs surrounding samples "
            "on both sides of each time point. Near the file boundaries, the "
            "filter must rely on padding and incomplete context, so windows in "
            "that region can contain edge transients even when they are still "
            "numerically inside the file."
        )

        stage = "kurtosis_bad_channel_detection"
        bad_metrics = detect_and_interpolate_bad_channels_by_kurtosis(
            raw=raw,
            filename_for_log=bdf_path.name,
            output_folder=output_folder,
            log_func=log_func,
            debug_enabled=False,
        )
        n_bad_by_kurtosis = int(bad_metrics["bad_by_kurtosis"].sum()) if not bad_metrics.empty else 0

        stage = "analysis_channel_validation"
        analysis_channels = validate_analysis_channels(raw)
        log_func(f"Using analysis channels ({len(analysis_channels)}): {analysis_channels}")

        post_sec = POST_EVENT_SEC_IF_INCLUDED if INCLUDE_POST_STIMULUS else 0.0
        analysis_window_sec = PRE_EVENT_SEC + EVENT_DURATION_SEC + post_sec
        log_func(
            f"Analysis window: pre={PRE_EVENT_SEC:.3f}s, "
            f"event={EVENT_DURATION_SEC:.3f}s, post={post_sec:.3f}s, "
            f"total={analysis_window_sec:.3f}s."
        )

        stage = "baseline_epoch_extraction"
        baseline_epochs = extract_epochs_for_code(
            raw=raw,
            events=intended_events,
            code=BASELINE_EVENT_CODE,
            picks=analysis_channels,
            window_sec=analysis_window_sec,
            edge_margin_samples=filter_edge_margin_samples,
        )
        log_func(
            f"Baseline trigger {BASELINE_EVENT_CODE}: "
            f"usable_epochs={baseline_epochs.epochs.shape[0]}, "
            f"skipped_epochs={baseline_epochs.skipped_epochs}, "
            f"out_of_bounds_epochs={baseline_epochs.out_of_bounds_epochs}, "
            f"edge_excluded_epochs={baseline_epochs.edge_excluded_epochs}."
        )

        baseline_fft = None
        baseline_welch = None
        if baseline_epochs.epochs.shape[0] > 0:
            baseline_fft = compute_sssep_fft_from_averaged_epochs(
                baseline_epochs.epochs,
                sfreq=float(raw.info["sfreq"]),
                fmin=FMIN,
                fmax=FMAX,
            )
            baseline_welch = compute_welch_psd_average(
                baseline_epochs.epochs,
                sfreq=float(raw.info["sfreq"]),
                fmin=FMIN,
                fmax=FMAX,
            )
        else:
            log_func(
                f"WARNING: No complete trigger-{BASELINE_EVENT_CODE} baseline epochs. "
                "Baseline ratio columns will be NaN."
            )

        stage = "active_sssep_analysis"
        summary_rows: list[dict[str, object]] = []
        plotted_trigger_count = 0
        plot_cap_notice_logged = False

        for code in ACTIVE_EVENT_CODES:
            label = TRIGGER_LABELS[code]
            condition, finger = parse_trigger_label(label)
            target_hz = TRIGGER_HZ_MAP[code]
            code_dir = plots_dir / f"trigger_{code:03d}_{label.replace(' ', '_')}"
            ensure_folder(code_dir)

            epoch_set = extract_epochs_for_code(
                raw=raw,
                events=intended_events,
                code=code,
                picks=analysis_channels,
                window_sec=analysis_window_sec,
                edge_margin_samples=filter_edge_margin_samples,
            )

            n_epochs = int(epoch_set.epochs.shape[0])
            epoch_count_ok = n_epochs == EXPECTED_REPETITIONS_PER_TRIGGER
            if epoch_set.edge_excluded_epochs > 0:
                log_func(
                    f"WARNING: Trigger {code} ({label}) excluded "
                    f"{epoch_set.edge_excluded_epochs} epoch(s) because the "
                    "analysis window overlapped the FIR edge-transient margin."
                )
            if not epoch_count_ok:
                log_func(
                    f"WARNING: Trigger {code} ({label}) expected "
                    f"{EXPECTED_REPETITIONS_PER_TRIGGER} usable epochs but found {n_epochs}."
                )
            else:
                log_func(f"Trigger {code} ({label}) has expected {n_epochs} usable epochs.")

            base_row: dict[str, object] = {
                "file_name": bdf_path.name,
                "trigger_code": code,
                "trigger_label": label,
                "condition": condition,
                "finger": finger,
                "expected_frequency_hz": target_hz,
                "expected_repetitions": EXPECTED_REPETITIONS_PER_TRIGGER,
                "usable_epochs": n_epochs,
                "skipped_epochs": epoch_set.skipped_epochs,
                "out_of_bounds_epochs": epoch_set.out_of_bounds_epochs,
                "edge_excluded_epochs": epoch_set.edge_excluded_epochs,
                "epoch_count_ok": epoch_count_ok,
                "analysis_window_sec": analysis_window_sec,
                "include_post_stimulus": INCLUDE_POST_STIMULUS,
                "sampling_rate_hz": float(raw.info["sfreq"]),
                "analysis_channels": ";".join(analysis_channels),
                "baseline_trigger_code": BASELINE_EVENT_CODE,
                "baseline_usable_epochs": int(baseline_epochs.epochs.shape[0]),
                "baseline_skipped_epochs": baseline_epochs.skipped_epochs,
                "baseline_out_of_bounds_epochs": baseline_epochs.out_of_bounds_epochs,
                "baseline_edge_excluded_epochs": baseline_epochs.edge_excluded_epochs,
                "fir_edge_margin_samples": filter_edge_margin_samples,
                "fir_edge_margin_sec": filter_edge_margin_sec,
            }

            if n_epochs == 0:
                no_epoch_row = dict(base_row)
                no_epoch_row["status"] = "no_complete_epochs"
                summary_rows.append(no_epoch_row)
                continue

            sssep_fft = compute_sssep_fft_from_averaged_epochs(
                epoch_set.epochs,
                sfreq=float(raw.info["sfreq"]),
                fmin=FMIN,
                fmax=FMAX,
            )
            welch_psd = compute_welch_psd_average(
                epoch_set.epochs,
                sfreq=float(raw.info["sfreq"]),
                fmin=FMIN,
                fmax=FMAX,
            )

            sssep_metrics = extract_target_metrics(sssep_fft, target_hz)
            welch_metrics = extract_target_metrics(welch_psd, target_hz)

            baseline_fft_metrics = (
                extract_target_metrics(baseline_fft, target_hz)
                if baseline_fft is not None
                else None
            )
            baseline_welch_metrics = (
                extract_target_metrics(baseline_welch, target_hz)
                if baseline_welch is not None
                else None
            )

            row = dict(base_row)
            row["status"] = "success"
            for key, value in sssep_metrics.items():
                row[f"sssep_fft_{key}"] = value
            for key, value in welch_metrics.items():
                row[f"welch_{key}"] = value

            add_baseline_comparison(row, "sssep_fft", baseline_fft_metrics)
            add_baseline_comparison(row, "welch", baseline_welch_metrics)
            summary_rows.append(row)

            if SAVE_CSV_SUMMARIES:
                spectrum_to_dataframe(sssep_fft, baseline_fft).to_csv(
                    code_dir / f"{file_stem}_trigger_{code:03d}_sssep_fft.csv",
                    index=False,
                )
                spectrum_to_dataframe(welch_psd, baseline_welch).to_csv(
                    code_dir / f"{file_stem}_trigger_{code:03d}_welch_psd.csv",
                    index=False,
                )

            should_plot = SAVE_PLOTS and plotted_trigger_count < MAX_INDIVIDUAL_PLOTS
            if SAVE_PLOTS and not should_plot and not plot_cap_notice_logged:
                log_func(
                    "Skipping plots for remaining successful triggers because "
                    f"MAX_INDIVIDUAL_PLOTS={MAX_INDIVIDUAL_PLOTS}."
                )
                plot_cap_notice_logged = True

            if should_plot:
                plot_spectrum(
                    active=sssep_fft,
                    baseline=baseline_fft,
                    title=(
                        f"{file_stem} - Trigger {code} {label} - "
                        "Primary SSSEP FFT"
                    ),
                    outpath=code_dir / f"{file_stem}_trigger_{code:03d}_sssep_fft.png",
                    target_hz=target_hz,
                )
                plot_spectrum(
                    active=welch_psd,
                    baseline=baseline_welch,
                    title=(
                        f"{file_stem} - Trigger {code} {label} - "
                        "Supplemental Welch PSD"
                    ),
                    outpath=code_dir / f"{file_stem}_trigger_{code:03d}_welch_psd.png",
                    target_hz=target_hz,
                )
                plotted_trigger_count += 1

        stage = "saving_outputs"
        summary_path = write_summary_csv(output_folder, file_stem, summary_rows)

        report_path = output_folder / f"{file_stem}_processing_report.txt"
        log_func(f"Done with: {bdf_path.name}")
        log_func(f"Summary CSV saved to: {summary_path}")
        log_func(f"Processing report saved to: {report_path}")
        write_processing_report(
            report_path=report_path,
            bdf_path=bdf_path,
            original_sfreq=original_sfreq,
            final_sfreq=float(raw.info["sfreq"]),
            n_bad_by_kurtosis=n_bad_by_kurtosis,
            found_codes=found_codes,
            analysis_window_sec=analysis_window_sec,
            filter_edge_margin_samples=filter_edge_margin_samples,
            filter_edge_margin_sec=filter_edge_margin_sec,
            analysis_channels=analysis_channels,
            report_lines=report_lines,
        )

        return {
            "file_name": bdf_path.name,
            "status": "success",
            "output_folder": str(output_folder),
            "summary_csv": str(summary_path),
            "original_sfreq_hz": original_sfreq,
            "final_sfreq_hz": float(raw.info["sfreq"]),
            "bad_channels_by_kurtosis": n_bad_by_kurtosis,
        }

    except Exception as exc:
        error_path = output_folder / "ERROR.txt"
        error_text = traceback.format_exc()
        write_error_report(
            error_path=error_path,
            bdf_path=bdf_path,
            stage=stage,
            exc=exc,
            error_text=error_text,
            report_lines=report_lines,
        )

        return {
            "file_name": bdf_path.name,
            "status": "failed",
            "failed_stage": stage,
            "output_folder": str(output_folder),
            "error": str(exc),
            "error_file": str(error_path),
        }
