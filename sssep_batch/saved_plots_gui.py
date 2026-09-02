"""PySide6 panel for plotting previously saved SSSEP FFT amplitudes."""

from __future__ import annotations

from math import isfinite
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sssep_batch.analysis.saved_fft import (
    PARTICIPANT_FFT_FILENAME,
    SavedFftDataset,
    load_saved_fft_dataset,
    saved_scalp_frequency_bounds,
)
from sssep_batch.analysis.saved_outputs import (
    create_saved_roi_outputs,
    create_saved_scalp_outputs,
)
from sssep_batch.config import PLOT_CHANNEL, STIMULATION_FREQUENCY_HZ
from sssep_batch.gui_style import SectionCard, build_page, hint_label, make_form


def _saved_results_source(selected_path: str) -> Path:
    """Resolve a run or the newest immediate run below an analysis output root."""

    selected = Path(selected_path).expanduser()
    if not selected.is_dir():
        return selected
    direct = selected / PARTICIPANT_FFT_FILENAME
    if direct.is_file():
        return direct
    candidates = [
        child / PARTICIPANT_FFT_FILENAME
        for child in selected.iterdir()
        if child.is_dir() and (child / PARTICIPANT_FFT_FILENAME).is_file()
    ]
    if not candidates:
        raise ValueError(
            f"No {PARTICIPANT_FFT_FILENAME} was found in this folder or its "
            f"immediate run folders:\n{selected}"
        )
    return max(
        candidates,
        key=lambda path: (path.stat().st_mtime_ns, path.parent.name.casefold(), path.parent.name),
    )


class SavedFftLoadWorker(QThread):
    """Load and validate a saved FFT table without blocking the launcher."""

    def __init__(self, selected_path: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.selected_path = selected_path
        self.dataset: SavedFftDataset | None = None
        self.error: Exception | None = None

    def run(self) -> None:
        """Read the selected saved results and report one terminal signal."""

        source = Path(self.selected_path)
        try:
            source = _saved_results_source(self.selected_path)
            self.dataset = load_saved_fft_dataset(source)
        except Exception as exc:
            self.error = ValueError(f"Could not load saved FFT data from:\n{source}\n\n{exc}")


class SavedPlotWorker(QThread):
    """Create selected-condition plots sequentially from one loaded FFT table."""

    progress = Signal(str)

    def __init__(
        self,
        dataset: SavedFftDataset,
        request: dict[str, object],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.dataset = dataset
        self.request = request
        self.result: dict[str, object] | None = None
        self.error: Exception | None = None

    def run(self) -> None:
        """Keep successful plots and report failures without stopping the batch."""

        try:
            events = tuple(self.request["events"])
            outputs, failures = [], []
            available = {name.casefold(): name for name in self.dataset.channel_names}
            requested = tuple(self.request.get("channels", ()))
            channels = tuple(dict.fromkeys(
                name if name in self.dataset.channel_names else available[name.casefold()]
                for name in requested if name.casefold() in available
            ))
            missing = [name for name in requested if name.casefold() not in available]
            for index, (event_type, trigger_code) in enumerate(events, 1):
                event = next(item for item in self.dataset.events if (
                    item.event_type, item.trigger_code
                ) == (event_type, trigger_code))
                self.progress.emit(f"Creating plot {index}/{len(events)}: {event.display_name}...")
                try:
                    frequency = self.request.get("stimulation_hz")
                    if frequency is None:
                        frequency = event.target_hz
                    if frequency is not None:
                        lower, upper = saved_scalp_frequency_bounds(self.dataset)
                        if not isfinite(frequency) or not lower <= frequency <= upper:
                            raise ValueError(
                                f"TENS Unit Stimulation Frequency must be between {lower:g} "
                                f"and {upper:g} Hz for these results. Change it in File > Settings."
                            )
                    common = dict(
                        dataset=self.dataset, event_type=event_type, trigger_code=trigger_code,
                        participant_id=self.request.get("participant_id"),
                    )
                    if self.request["kind"] == "roi":
                        if not channels:
                            raise ValueError("No selected ROI electrodes are in these results. Review Regions of Interest in File > Settings.")
                        output = create_saved_roi_outputs(
                            **common, channels=channels, roi_name=str(self.request["roi_name"]),
                            stimulation_hz=frequency,
                        )
                    elif self.request["kind"] == "scalp":
                        if frequency is None:
                            raise ValueError("Set TENS Unit Stimulation Frequency in File > Settings before creating a scalp map.")
                        output = create_saved_scalp_outputs(**common, frequency_hz=frequency)
                    else:
                        raise ValueError(f"Unknown saved plot kind: {self.request['kind']!r}")
                    outputs.append(dict(
                        output, event_type=event_type, trigger_code=trigger_code,
                        trigger_label=event.trigger_label,
                    ))
                except Exception as exc:
                    failures.append(f"{event.display_name}: {str(exc) or type(exc).__name__}")
            self.result = dict(
                kind=self.request["kind"], outputs=outputs, failures=failures,
                requested_count=len(events), missing_channels=missing,
            )
        except Exception as exc:
            self.error = exc


class SavedPlotsPanel(QWidget):
    """Load a completed run and create new FFT displays without reprocessing."""

    busy_changed = Signal(bool)

    def __init__(self, initial_folder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.load_worker: SavedFftLoadWorker | None = None
        self.plot_worker: SavedPlotWorker | None = None
        self.dataset: SavedFftDataset | None = None
        self.plot_output_folder = ""
        self._updating_results_path = False
        self.settings_need_review = False

        self.results_edit = QLineEdit(initial_folder)
        self.results_browse_button = QPushButton("Browse...")
        self.results_load_button = QPushButton("Reload Results")
        self.level_combo = QComboBox()
        self.level_combo.addItem("Group average", "group")
        self.level_combo.addItem("Individual participant", "participant")
        self.participant_combo = QComboBox()
        self.event_combo = QComboBox()
        self.selected_channels: tuple[str, ...] = (PLOT_CHANNEL,)
        self.roi_name = PLOT_CHANNEL
        self.stimulation_hz = STIMULATION_FREQUENCY_HZ
        self.plot_settings_label = hint_label("")
        self.plot_settings_label.setTextFormat(Qt.TextFormat.PlainText)
        self.create_roi_button = QPushButton("Create FFT Plot")
        self.create_scalp_button = QPushButton("Create Scalp Map")
        self.view_button = QPushButton("View New Plot")
        self.status_label = QLabel(
            "Choose a processed results folder to load its FFT data automatically."
        )

        self._build_layout()
        self._connect_signals()
        self._update_plot_settings_summary()
        self._set_working(False)

    def _build_layout(self) -> None:
        """Group saved-result choices and plotting actions into section cards."""

        body, footer = build_page(self)
        source_card = SectionCard(
            "Saved results",
            "Load an earlier run to make new plots without processing BDF files again.",
        )

        results_row = QHBoxLayout()
        results_row.addWidget(self.results_edit)
        results_row.addWidget(self.results_browse_button)
        results_row.addWidget(self.results_load_button)
        source_form = make_form()
        source_form.addRow("Processed results folder", results_row)
        source_card.body.addLayout(source_form)
        body.addWidget(source_card)

        selection_card = SectionCard("Data selection")
        selection_row = QHBoxLayout()
        selection_row.setSpacing(12)
        for label, control, stretch in (
            ("Plot level", self.level_combo, 2),
            ("Participant", self.participant_combo, 1),
            ("Trigger code / event", self.event_combo, 2),
        ):
            field = QVBoxLayout()
            field.setSpacing(6)
            field.addWidget(QLabel(label))
            field.addWidget(control)
            selection_row.addLayout(field, stretch)
        selection_card.body.addLayout(selection_row)
        selection_card.body.addWidget(self.plot_settings_label)
        selection_card.body.addWidget(hint_label(
            "Change Regions of Interest and stimulation frequency in File > Settings. "
            "All conditions creates a separate PNG for each available attention trigger code."
        ))
        body.addWidget(selection_card)
        self.create_roi_button.setProperty("uiRole", "primary")
        body.addStretch(1)

        self.status_label.setWordWrap(True)
        self.status_label.setProperty("uiRole", "muted")
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.create_roi_button)
        footer.addWidget(self.create_scalp_button)
        footer.addWidget(self.view_button)

    def _connect_signals(self) -> None:
        """Connect panel actions."""

        self.results_browse_button.clicked.connect(self._browse_results)
        self.results_load_button.clicked.connect(self._load_results)
        self.results_edit.textChanged.connect(self._source_path_changed)
        self.results_edit.editingFinished.connect(self.ensure_results_loaded)
        self.level_combo.currentIndexChanged.connect(self._level_changed)
        self.participant_combo.currentIndexChanged.connect(self._participant_changed)
        self.event_combo.currentIndexChanged.connect(self._event_changed)
        self.create_roi_button.clicked.connect(lambda: self._start_plot("roi"))
        self.create_scalp_button.clicked.connect(lambda: self._start_plot("scalp"))
        self.view_button.clicked.connect(self._view_plot)

    def set_results_folder(self, folder: str) -> None:
        """Point the panel at a newly completed or user-selected run folder."""

        self.results_edit.setText(str(folder))

    def set_plot_settings(
        self, *, roi_name: str, channels: tuple[str, ...], stimulation_hz: float | None,
    ) -> None:
        """Receive the committed File > Settings selection, independent of data loads."""
        self.roi_name = roi_name
        self.selected_channels = tuple(channels)
        self.stimulation_hz = stimulation_hz
        self._update_plot_settings_summary()

    def ensure_results_loaded(self) -> None:
        """Load on view activation or completed path entry, reusing valid loaded data."""

        if self.dataset is None:
            self._load_results()

    def _source_path_changed(self, _text: str = "") -> None:
        """Discard loaded data when the visible source path changes."""

        if self._updating_results_path or self.is_busy():
            return
        if self.dataset is None and not self.plot_output_folder:
            return
        self._clear_loaded_results()
        self._refresh_controls(False)
        self.status_label.setText(
            "Results folder changed. Finish entering the path to load its FFT data."
        )

    def _clear_loaded_results(self) -> None:
        self.dataset = None
        self.plot_output_folder = ""
        self.participant_combo.clear()
        self.event_combo.clear()

    def is_busy(self) -> bool:
        """Return whether saved FFT loading or plotting is still active."""

        return self.load_worker is not None or self.plot_worker is not None

    def wait_for_workers(self) -> None:
        """Wait for active saved-result workers during application shutdown."""

        if self.load_worker is not None and self.load_worker.isRunning():
            self.load_worker.wait()
        if self.plot_worker is not None and self.plot_worker.isRunning():
            self.plot_worker.wait()

    def show_busy_close_message(self) -> None:
        """Explain why the launcher cannot close yet."""

        self.status_label.setText(
            "Saved FFT loading or plotting is still running. Keep this window "
            "open until it finishes."
        )

    def _browse_results(self) -> None:
        """Choose an SSSEP run folder containing saved participant FFT data."""

        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Processed SSSEP Results Folder",
            self.results_edit.text().strip(),
        )
        if folder:
            self.results_edit.setText(folder)
            self.ensure_results_loaded()

    def _load_results(self) -> None:
        """Load one consolidated participant FFT table off the UI thread."""

        if self.is_busy():
            return
        selected_path = self.results_edit.text().strip()
        if not selected_path:
            self.status_label.setText(
                "Choose a processed results folder to load its FFT data automatically."
            )
            return

        self._clear_loaded_results()
        self.load_worker = SavedFftLoadWorker(selected_path, self)
        self.load_worker.finished.connect(self._load_finished)
        self.load_worker.finished.connect(self.load_worker.deleteLater)
        self._set_working(True)
        self.status_label.setText("Finding and checking the saved FFT data...")
        self.load_worker.start()

    def _results_loaded(self, dataset: SavedFftDataset) -> None:
        """Populate selectors after strict CSV validation."""

        self.dataset = dataset
        self._updating_results_path = True
        try:
            self.results_edit.setText(str(dataset.source_csv.parent))
        finally:
            self._updating_results_path = False
        self.participant_combo.clear()
        for participant_id in dataset.participant_ids:
            self.participant_combo.addItem(participant_id, participant_id)
        self._populate_events()
        self._event_changed()
        self.status_label.setText(
            f"Loaded {len(dataset.participant_ids)} participant(s), "
            f"{len(dataset.events)} event(s), and {len(dataset.channel_names)} "
            f"electrode(s) from {dataset.source_csv.parent}. Choose what to plot."
        )

    def _results_failed(self, exc: Exception) -> None:
        """Show a saved-data loading or validation failure."""

        message = str(exc) or type(exc).__name__
        self.status_label.setText(message.splitlines()[0])
        QMessageBox.warning(self, "Could Not Load Saved FFT Data", message)

    def _load_finished(self) -> None:
        """Handle one load result before releasing its worker and controls."""

        worker = self.load_worker
        if worker is None:
            return
        error = worker.error
        try:
            if error is None and worker.dataset is not None:
                self._results_loaded(worker.dataset)
            elif error is None:
                error = RuntimeError("The saved FFT loader returned no result.")
        except Exception as exc:
            self._clear_loaded_results()
            error = exc
        finally:
            self.load_worker = None
            self._set_working(False)
        if error is not None:
            # A modal dialog runs a nested event loop: release the finished
            # worker first so its queued deletion cannot leave a stale handle.
            self._results_failed(error)

    def _level_changed(self) -> None:
        """Enable participant selection only for participant-level plots."""

        self.participant_combo.setEnabled(
            self.dataset is not None
            and self.level_combo.currentData() == "participant"
            and not self.is_busy()
        )
        self._populate_events()

    def _participant_changed(self) -> None:
        """Limit individual plots to events saved for that participant."""

        if self.level_combo.currentData() == "participant":
            self._populate_events()

    def _populate_events(self) -> None:
        """Show group events or only the selected participant's events."""

        if self.dataset is None:
            return
        selected_participant = None
        if self.level_combo.currentData() == "participant":
            selected_participant = self.participant_combo.currentData()
        available = {
            (record.event_type, record.trigger_code)
            for record in self.dataset.records
            if selected_participant is None
            or record.participant_id == selected_participant
        }
        previous = self.event_combo.currentData()
        self.event_combo.blockSignals(True)
        self.event_combo.clear()
        if any(event_type == "cue" for event_type, _code in available):
            self.event_combo.addItem("All conditions", "all")
        for event in self.dataset.events:
            key = (event.event_type, event.trigger_code)
            if key in available:
                self.event_combo.addItem(event.display_name, key)
        previous_index = next((
            index for index in range(self.event_combo.count())
            if self.event_combo.itemData(index) == previous
        ), -1)
        if previous_index >= 0:
            self.event_combo.setCurrentIndex(previous_index)
        elif self.event_combo.count() > 1 and self.event_combo.itemData(0) == "all":
            self.event_combo.setCurrentIndex(1)
        self.event_combo.blockSignals(False)
        self._event_changed()

    def _event_changed(self) -> None:
        """Make each action's single-condition or all-condition scope explicit."""
        all_conditions = self.event_combo.currentData() == "all"
        self.create_roi_button.setText("Create All FFT Plots" if all_conditions else "Create FFT Plot")
        self.create_scalp_button.setText("Create All Scalp Maps" if all_conditions else "Create Scalp Map")

    def _update_plot_settings_summary(self) -> None:
        frequency = "Saved per-condition frequency" if self.stimulation_hz is None else f"{self.stimulation_hz:g} Hz"
        self.plot_settings_label.setText(
            f"Regions of Interest: {self.roi_name} ({', '.join(self.selected_channels)})\n"
            f"TENS Unit Stimulation Frequency: {frequency}"
        )

    def _start_plot(self, kind: str) -> None:
        """Validate the saved-data selection and launch one plot worker."""

        if self.is_busy():
            return
        if self.settings_need_review:
            self._warn(
                "Settings Need Attention",
                "Review File > Settings and click Save before creating plots.",
            )
            return
        if self.dataset is None:
            self._warn(
                "Saved Results Need Attention",
                "Load a processed SSSEP results folder before plotting.",
            )
            return
        selected_event = self.event_combo.currentData()
        if selected_event != "all" and (
            not isinstance(selected_event, tuple) or len(selected_event) != 2
        ):
            self._warn("Saved Results Need Attention", "Choose a trigger code before plotting.")
            return

        participant_id = None
        if self.level_combo.currentData() == "participant":
            participant_id = self.participant_combo.currentData()
            if not participant_id:
                self._warn("Saved Results Need Attention", "Choose a participant before plotting.")
                return
        events = (
            tuple(self.event_combo.itemData(index) for index in range(self.event_combo.count())
                  if isinstance(self.event_combo.itemData(index), tuple)
                  and self.event_combo.itemData(index)[0] == "cue")
            if selected_event == "all" else (selected_event,)
        )
        if not events:
            self._warn("Saved Results Need Attention", "No attention conditions are available for this selection.")
            return
        request: dict[str, object] = {
            "kind": kind,
            "events": events,
            "participant_id": participant_id,
            "stimulation_hz": self.stimulation_hz,
        }
        if kind == "roi":
            channels = self.selected_channels
            if not channels:
                self._warn("ROI Needs Attention", "Select at least one electrode for the FFT plot.")
                return
            roi_name = self.roi_name.strip()
            if not roi_name:
                self._warn(
                    "ROI Needs Attention",
                    "Enter a short electrode or ROI name before plotting.",
                )
                return
            request.update(
                channels=channels, roi_name=roi_name,
            )
            working_message = "Creating the saved electrode / ROI FFT plot..."
        elif kind == "scalp":
            working_message = "Creating the saved FFT scalp map..."
        else:
            raise ValueError(f"Unknown saved plot kind: {kind!r}")

        self.plot_output_folder = ""
        self._set_working(True)
        self.status_label.setText(working_message)
        self.plot_worker = SavedPlotWorker(self.dataset, request, self)
        self.plot_worker.progress.connect(self.status_label.setText)
        self.plot_worker.finished.connect(self._plot_worker_finished)
        self.plot_worker.finished.connect(self.plot_worker.deleteLater)
        self.plot_worker.start()

    def _plot_finished(self, result: dict[str, object]) -> str | None:
        """Report every result; return failures to show after releasing the worker."""
        outputs = result["outputs"]
        failures = result["failures"]
        self.plot_output_folder = str(outputs[0]["output_folder"]) if outputs else ""
        kind = "scalp map(s)" if result["kind"] == "scalp" else "FFT plot(s)"
        summary = f"Created {len(outputs)} of {result['requested_count']} {kind}."
        if outputs:
            summary += " PNGs saved in saved_fft_plots."
        if failures:
            summary += f" {len(failures)} failed."
        details = []
        for output in outputs:
            label = f"Trigger code {output['trigger_code']}" if output["event_type"] == "cue" else "Baseline"
            if result["kind"] == "scalp":
                details.append(
                    f"{label}: requested {output['requested_frequency_hz']:g} Hz, "
                    f"plotted {output['actual_frequency_hz']:g} Hz; "
                    f"electrode N={output['participant_count_min']}–{output['participant_count_max']}."
                )
                if output.get("omitted_channels"):
                    details.append(f"{label}: omitted electrodes without coordinates: {', '.join(output['omitted_channels'])}.")
            else:
                details.append(f"{label}: N={output['participant_count']}, using {', '.join(output['used_channels'])}.")
        if result.get("missing_channels"):
            details.append("ROI electrodes not in these results: " + ", ".join(result["missing_channels"]))
        self.status_label.setText("\n".join([summary, *details]))
        return "\n\n".join([summary, *failures]) if failures else None

    def _plot_failed(self, exc: Exception) -> None:
        """Show a post-processing plot failure without hiding its cause."""

        message = str(exc) or type(exc).__name__
        self.status_label.setText(message.splitlines()[0])
        QMessageBox.critical(self, "Saved FFT Plot Failed", message)

    def _plot_worker_finished(self) -> None:
        """Handle one plot result before releasing its worker and controls."""

        worker = self.plot_worker
        if worker is None:
            return
        error = worker.error
        warning = None
        try:
            if error is None and worker.result is not None:
                warning = self._plot_finished(worker.result)
            elif error is None:
                error = RuntimeError("The saved FFT plot worker returned no result.")
        except Exception as exc:
            error = exc
        finally:
            self.plot_worker = None
            self._set_working(False)
        if error is not None:
            self._plot_failed(error)
        elif warning:
            QMessageBox.warning(self, "Some Plots Could Not Be Created", warning)

    def _set_working(self, working: bool) -> None:
        """Enable saved-result controls only when data are loaded and idle."""

        self._refresh_controls(working)
        self.busy_changed.emit(working)

    def _refresh_controls(self, working: bool) -> None:
        """Refresh controls without reporting a worker-state transition."""

        loaded = self.dataset is not None
        self.results_edit.setEnabled(not working)
        self.results_browse_button.setEnabled(not working)
        self.results_load_button.setEnabled(not working)
        for widget in (
            self.level_combo,
            self.event_combo,
            self.create_roi_button,
            self.create_scalp_button,
        ):
            widget.setEnabled(loaded and not working)
        self.participant_combo.setEnabled(
            loaded
            and not working
            and self.level_combo.currentData() == "participant"
        )
        self.view_button.setEnabled(not working and bool(self.plot_output_folder))

    def _view_plot(self) -> None:
        """Open the fresh folder containing the latest post-processing plot."""

        output_path = Path(self.plot_output_folder)
        if not output_path.is_dir():
            self._warn(
                "Saved Plot Folder Not Found",
                f"The saved plot folder does not exist:\n\n{output_path}",
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_path))):
            self._warn(
                "Could Not Open Saved Plot",
                f"Could not open the saved plot folder:\n\n{output_path}",
            )

    def _warn(self, title: str, message: str) -> None:
        """Show a warning and mirror its first line in the panel status."""

        self.status_label.setText(message.splitlines()[0])
        QMessageBox.warning(self, title, message)
