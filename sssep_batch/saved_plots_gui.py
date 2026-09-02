"""PySide6 panel for plotting previously saved SSSEP FFT amplitudes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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
from sssep_batch.roi_selection_gui import RoiSelectionDialog


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
    """Create one post-processing plot from an already-loaded FFT table."""

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
        """Create the requested ROI spectrum or scalp map off the UI thread."""

        try:
            common = {
                "dataset": self.dataset,
                "event_type": str(self.request["event_type"]),
                "trigger_code": int(self.request["trigger_code"]),
                "participant_id": self.request.get("participant_id"),
            }
            if self.request["kind"] == "roi":
                self.result = create_saved_roi_outputs(
                    **common,
                    channels=tuple(self.request["channels"]),
                    roi_name=str(self.request["roi_name"]),
                    stimulation_hz=float(self.request["stimulation_hz"]),
                )
            elif self.request["kind"] == "scalp":
                self.result = create_saved_scalp_outputs(
                    **common,
                    frequency_hz=float(self.request["frequency_hz"]),
                )
            else:
                raise ValueError(f"Unknown saved plot kind: {self.request['kind']!r}")
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

        self.results_edit = QLineEdit(initial_folder)
        self.results_browse_button = QPushButton("Browse...")
        self.results_load_button = QPushButton("Reload Results")
        self.level_combo = QComboBox()
        self.level_combo.addItem("Group average", "group")
        self.level_combo.addItem("Individual participant", "participant")
        self.participant_combo = QComboBox()
        self.event_combo = QComboBox()
        self.selected_channels: tuple[str, ...] = ()
        self.roi_name = ""
        self.roi_summary_label = QLabel("Load saved results to choose electrodes.")
        self.roi_summary_label.setWordWrap(True)
        self.roi_summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.choose_roi_button = QPushButton("Choose Electrodes / Define ROI...")
        self.frequency_spin = QDoubleSpinBox()
        self.frequency_spin.setDecimals(4)
        self.frequency_spin.setSingleStep(0.1)
        self.frequency_spin.setSuffix(" Hz")
        self.frequency_spin.setRange(0.0, 10000.0)
        if STIMULATION_FREQUENCY_HZ is not None:
            self.frequency_spin.setValue(STIMULATION_FREQUENCY_HZ)
        self.create_roi_button = QPushButton("Create Electrode / ROI FFT Plot")
        self.create_scalp_button = QPushButton("Create Scalp Map")
        self.view_button = QPushButton("View New Plot")
        self.status_label = QLabel(
            "Choose a processed results folder to load its FFT data automatically."
        )

        self._build_layout()
        self._connect_signals()
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
        body.addWidget(selection_card)

        roi_card = SectionCard(
            "FFT electrode selection",
            "Choose one electrode or define a region to average on the scalp diagram.",
        )
        roi_card.body.addWidget(self.roi_summary_label)
        roi_card.body.addWidget(self.choose_roi_button)
        roi_card.body.addStretch(1)
        self.create_roi_button.setProperty("uiRole", "primary")

        scalp_card = SectionCard(
            "Stimulation frequency",
            "Set the FFT marker and scalp-map frequency.",
        )
        scalp_form = make_form()
        scalp_form.addRow("TENS Unit Stimulation Frequency (Hz)", self.frequency_spin)
        scalp_card.body.addLayout(scalp_form)
        scalp_card.body.addWidget(
            hint_label(
                "Starts at the frequency saved for this trigger code when available. "
                "Scalp maps use the nearest saved bin and all available electrodes."
            )
        )
        scalp_card.body.addStretch(1)

        plot_row = QHBoxLayout()
        plot_row.setSpacing(14)
        plot_row.addWidget(roi_card, 3)
        plot_row.addWidget(scalp_card, 2)
        body.addLayout(plot_row)
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
        self.choose_roi_button.clicked.connect(self._choose_roi)
        self.create_roi_button.clicked.connect(lambda: self._start_plot("roi"))
        self.create_scalp_button.clicked.connect(lambda: self._start_plot("scalp"))
        self.view_button.clicked.connect(self._view_plot)

    def set_results_folder(self, folder: str) -> None:
        """Point the panel at a newly completed or user-selected run folder."""

        self.results_edit.setText(str(folder))

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
        self.selected_channels = ()
        self.roi_name = ""
        self._update_roi_summary()

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
        default_channel = (
            PLOT_CHANNEL if PLOT_CHANNEL in dataset.channel_names else dataset.channel_names[0]
        )
        self.selected_channels = (default_channel,)
        self.roi_name = default_channel
        self._update_roi_summary()
        lower_hz, upper_hz = saved_scalp_frequency_bounds(dataset)
        self.frequency_spin.setRange(lower_hz, upper_hz)
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
        for event in self.dataset.events:
            key = (event.event_type, event.trigger_code)
            if key in available:
                self.event_combo.addItem(event.display_name, key)
        previous_index = self.event_combo.findData(previous)
        if previous_index >= 0:
            self.event_combo.setCurrentIndex(previous_index)
        self.event_combo.blockSignals(False)
        self._event_changed()

    def _event_changed(self) -> None:
        """Use the selected event's saved TENS frequency when available."""

        if self.dataset is None:
            return
        selected = self.event_combo.currentData()
        if not isinstance(selected, tuple) or len(selected) != 2:
            return
        event_type, trigger_code = selected
        event = next(
            (
                item
                for item in self.dataset.events
                if item.event_type == event_type
                and item.trigger_code == int(trigger_code)
            ),
            None,
        )
        if event is not None and event.target_hz is not None:
            self.frequency_spin.setValue(event.target_hz)
        elif STIMULATION_FREQUENCY_HZ is not None:
            self.frequency_spin.setValue(STIMULATION_FREQUENCY_HZ)

    def _choose_roi(self) -> None:
        """Edit a separate selection draft; Cancel preserves the active ROI."""

        if self.dataset is None or self.is_busy():
            return
        dialog = RoiSelectionDialog(
            available_channels=self.dataset.channel_names,
            selected_channels=self.selected_channels,
            roi_name=self.roi_name,
            parent=self,
        )
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.selected_channels = dialog.selected_channels
                self.roi_name = dialog.roi_name
                self._update_roi_summary()
        finally:
            dialog.deleteLater()

    def _update_roi_summary(self) -> None:
        """Keep the plot page compact while showing exactly what will be averaged."""

        if not self.selected_channels:
            self.roi_summary_label.setText("Load saved results to choose electrodes.")
            return
        self.roi_summary_label.setText(
            f"{self.roi_name}\n{len(self.selected_channels)} electrode(s): "
            + ", ".join(self.selected_channels)
        )

    def _start_plot(self, kind: str) -> None:
        """Validate the saved-data selection and launch one plot worker."""

        if self.is_busy():
            return
        if self.dataset is None:
            self._warn(
                "Saved Results Need Attention",
                "Load a processed SSSEP results folder before plotting.",
            )
            return
        selected_event = self.event_combo.currentData()
        if not isinstance(selected_event, tuple) or len(selected_event) != 2:
            self._warn("Saved Results Need Attention", "Choose a trigger code before plotting.")
            return

        participant_id = None
        if self.level_combo.currentData() == "participant":
            participant_id = self.participant_combo.currentData()
            if not participant_id:
                self._warn("Saved Results Need Attention", "Choose a participant before plotting.")
                return
        request: dict[str, object] = {
            "kind": kind,
            "event_type": selected_event[0],
            "trigger_code": selected_event[1],
            "participant_id": participant_id,
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
                stimulation_hz=self.frequency_spin.value(),
            )
            working_message = "Creating the saved electrode / ROI FFT plot..."
        elif kind == "scalp":
            request["frequency_hz"] = self.frequency_spin.value()
            working_message = "Creating the saved FFT scalp map..."
        else:
            raise ValueError(f"Unknown saved plot kind: {kind!r}")

        self.plot_output_folder = ""
        self._set_working(True)
        self.status_label.setText(working_message)
        self.plot_worker = SavedPlotWorker(self.dataset, request, self)
        self.plot_worker.finished.connect(self._plot_worker_finished)
        self.plot_worker.finished.connect(self.plot_worker.deleteLater)
        self.plot_worker.start()

    def _plot_finished(self, result: dict[str, object]) -> None:
        """Show the generated plot location."""

        self.plot_output_folder = str(result["output_folder"])
        if result.get("kind") == "scalp":
            requested = float(result["requested_frequency_hz"])
            actual = float(result["actual_frequency_hz"])
            count_min = int(result["participant_count_min"])
            count_max = int(result["participant_count_max"])
            count_text = (
                f"N={count_min}"
                if count_min == count_max
                else f"electrode N={count_min}–{count_max}"
            )
            omitted = list(result.get("omitted_channels", []) or [])
            omitted_text = (
                f" Electrodes without montage coordinates were omitted: "
                f"{', '.join(omitted)}."
                if omitted
                else ""
            )
            self.status_label.setText(
                f"Scalp map created at the nearest FFT bin: requested "
                f"{requested:g} Hz, plotted {actual:g} Hz ({count_text}). "
                "PNG saved in saved_fft_plots."
                f"{omitted_text}"
            )
        else:
            participant_count = int(result["participant_count"])
            channels = ", ".join(result["used_channels"])
            self.status_label.setText(
                f"FFT plot created from {participant_count} participant(s) using "
                f"{channels}. PNG saved in saved_fft_plots."
            )

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
        try:
            if error is None and worker.result is not None:
                self._plot_finished(worker.result)
            elif error is None:
                error = RuntimeError("The saved FFT plot worker returned no result.")
        except Exception as exc:
            error = exc
        finally:
            self.plot_worker = None
            self._set_working(False)
        if error is not None:
            self._plot_failed(error)

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
            self.choose_roi_button,
            self.frequency_spin,
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
