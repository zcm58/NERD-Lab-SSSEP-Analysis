"""One PySide6 launcher for participant tasks and recording analysis.

Participant presentation runs on Qt's GUI thread. BDF processing and saved
plot work stay off the GUI thread.
"""

from __future__ import annotations

import json
import sys
from math import isfinite
from pathlib import Path

import mne

from sssep_batch.batch import BatchValidationError, run_batch
from sssep_batch.config import (
    EVENT_DURATION_SEC,
    EXPECTED_REPETITIONS_PER_TRIGGER,
    INPUT_FOLDER,
    OUTPUT_ROOT,
    PLOT_CHANNEL,
    STIMULATION_FREQUENCY_HZ,
)
from sssep_batch.experiment import (
    CueTriggerCodes,
    QtTaskRunner,
    TaskCondition,
    TaskSettings,
    analysis_protocol_for_task,
)
from sssep_batch.experiment.models import (
    CUE_PROMPTS,
    DEFAULT_BREAK_DURATION_SEC,
    DEFAULT_BREAK_PROMPT,
    CueTarget,
)
from sssep_batch.models import AnalysisProtocol


REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = REPO_ROOT / ".sssep_gui_settings.json"
BIOSEMI64_CHANNELS = tuple(mne.channels.make_standard_montage("biosemi64").ch_names)


def load_saved_folders(settings_path: str | Path = SETTINGS_PATH) -> dict[str, str]:
    """Load saved folder defaults from `.sssep_gui_settings.json` if present."""
    path = Path(settings_path)
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Saved GUI settings are not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Saved GUI settings must contain a JSON object: {path}")

    saved: dict[str, str] = {}
    for key in ("input_folder", "output_root"):
        value = payload.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValueError(f"Saved GUI setting {key!r} must be a string: {path}")
        saved[key] = value
    return saved


def save_folder_defaults(
    input_folder: str,
    output_root: str,
    settings_path: str | Path = SETTINGS_PATH,
) -> None:
    """Save local GUI folder defaults without editing `config.py`."""
    path = Path(settings_path)
    payload = {
        "input_folder": input_folder,
        "output_root": output_root,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _require_pyside6():
    """Import PySide6 lazily and provide a clear install message if missing."""
    try:
        from PySide6.QtCore import QThread, QUrl, Signal
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QDoubleSpinBox,
            QFileDialog,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMessageBox,
            QPushButton,
            QSpinBox,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        raise RuntimeError(
            "PySide6 is required for the SSSEP launcher. Activate the project "
            "virtual environment and run: pip install -r requirements.txt"
        ) from exc

    return {
        "QApplication": QApplication,
        "QCheckBox": QCheckBox,
        "QComboBox": QComboBox,
        "QDesktopServices": QDesktopServices,
        "QDoubleSpinBox": QDoubleSpinBox,
        "QFileDialog": QFileDialog,
        "QGridLayout": QGridLayout,
        "QHBoxLayout": QHBoxLayout,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QMessageBox": QMessageBox,
        "QPushButton": QPushButton,
        "QSpinBox": QSpinBox,
        "QTabWidget": QTabWidget,
        "QThread": QThread,
        "QUrl": QUrl,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
        "Signal": Signal,
    }


def launch_gui() -> int:
    """Open the launcher window and return the Qt application exit code."""
    qt = _require_pyside6()
    from sssep_batch.gui_style import (
        SectionCard,
        apply_launcher_style,
        build_page,
        hint_label,
        make_form,
    )
    from sssep_batch.saved_plots_gui import SavedPlotsPanel

    QApplication = qt["QApplication"]
    QCheckBox = qt["QCheckBox"]
    QComboBox = qt["QComboBox"]
    QDesktopServices = qt["QDesktopServices"]
    QDoubleSpinBox = qt["QDoubleSpinBox"]
    QFileDialog = qt["QFileDialog"]
    QGridLayout = qt["QGridLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QLineEdit = qt["QLineEdit"]
    QMessageBox = qt["QMessageBox"]
    QPushButton = qt["QPushButton"]
    QSpinBox = qt["QSpinBox"]
    QTabWidget = qt["QTabWidget"]
    QThread = qt["QThread"]
    QUrl = qt["QUrl"]
    QVBoxLayout = qt["QVBoxLayout"]
    QWidget = qt["QWidget"]
    Signal = qt["Signal"]

    class BatchWorker(QThread):
        """Run `run_batch()` off the UI thread and emit Qt progress signals."""

        progress_changed = Signal(str, int, int)
        batch_finished = Signal(object)
        batch_failed = Signal(object)

        def __init__(
            self,
            input_folder: str,
            output_root: str,
            plot_channel: str,
            analysis_protocol: AnalysisProtocol,
            parent: QWidget,
        ) -> None:
            """Remember the selected batch settings for the background run."""
            super().__init__(parent)
            self.input_folder = input_folder
            self.output_root = output_root
            self.plot_channel = plot_channel
            self.analysis_protocol = analysis_protocol

        def run(self) -> None:
            """Execute the batch and translate success/failure into signals."""
            try:
                result = run_batch(
                    self.input_folder,
                    self.output_root,
                    progress_callback=self._handle_progress,
                    plot_channel=self.plot_channel,
                    analysis_protocol=self.analysis_protocol,
                )
            except Exception as exc:
                self.batch_failed.emit(exc)
            else:
                self.batch_finished.emit(result)

        def _handle_progress(self, event: dict[str, object]) -> None:
            """Convert a structured progress event into simple GUI signal values."""
            message = str(event.get("message", "Processing..."))
            completed = int(event.get("completed", 0) or 0)
            total = int(event.get("total", 0) or 0)
            self.progress_changed.emit(message, completed, total)

    class LauncherWindow(QWidget):
        """Single launcher for task presentation and BDF analysis."""

        def __init__(self) -> None:
            """Create widgets, load saved folders, and wire up button actions."""
            super().__init__()
            self.worker: BatchWorker | None = None
            self.task_runner: QtTaskRunner | None = None
            self.task_running = False
            self.output_folder = ""

            self.setWindowTitle("SSSEP Task and Analysis")
            self.tabs = QTabWidget()
            self.task_tab = QWidget()
            self.analysis_tab = QWidget()

            self.condition_combo = QComboBox()
            self.condition_combo.addItem(
                "Both hands (left hand / right hand)",
                TaskCondition.BOTH_HANDS.value,
            )
            self.condition_combo.addItem(
                "Right hand and right ankle",
                TaskCondition.RIGHT_HAND_AND_ANKLE.value,
            )
            self.epoch_duration_spin = QDoubleSpinBox()
            self.epoch_duration_spin.setRange(0.1, 3600.0)
            self.epoch_duration_spin.setDecimals(2)
            self.epoch_duration_spin.setSingleStep(0.5)
            self.epoch_duration_spin.setValue(EVENT_DURATION_SEC)
            self.epoch_duration_spin.setSuffix(" seconds")
            self.break_duration_spin = QDoubleSpinBox()
            self.break_duration_spin.setRange(0.1, 3600.0)
            self.break_duration_spin.setDecimals(2)
            self.break_duration_spin.setSingleStep(0.5)
            self.break_duration_spin.setValue(DEFAULT_BREAK_DURATION_SEC)
            self.break_duration_spin.setSuffix(" seconds")
            self.break_duration_spin.setToolTip(
                "A break appears between cue epochs, but not before or after the task."
            )
            self.total_epochs_spin = QSpinBox()
            self.total_epochs_spin.setRange(2, 10000)
            self.total_epochs_spin.setSingleStep(2)
            self.total_epochs_spin.setValue(EXPECTED_REPETITIONS_PER_TRIGGER * 2)
            self.total_epochs_spin.setToolTip(
                "Each cue appears equally often. A fresh random order is chosen "
                "for every task; the same cue may appear twice in a row."
            )
            self.left_hand_prompt_edit = QLineEdit(CUE_PROMPTS[CueTarget.LEFT_HAND])
            self.right_hand_prompt_edit = QLineEdit(CUE_PROMPTS[CueTarget.RIGHT_HAND])
            self.right_ankle_prompt_edit = QLineEdit(CUE_PROMPTS[CueTarget.RIGHT_ANKLE])
            self.break_prompt_edit = QLineEdit(DEFAULT_BREAK_PROMPT)
            self.test_mode_checkbox = QCheckBox(
                "Test mode (no BioSemi triggers)"
            )
            self.test_mode_checkbox.setToolTip(
                "Run the fullscreen task without opening COM3 or sending triggers."
            )

            self.both_hands_left_code_spin = self._new_fixed_trigger_spin(11)
            self.both_hands_right_code_spin = self._new_fixed_trigger_spin(12)
            self.hand_ankle_hand_code_spin = self._new_fixed_trigger_spin(21)
            self.hand_ankle_ankle_code_spin = self._new_fixed_trigger_spin(22)
            self.task_log_edit = QLineEdit()
            self.task_log_browse_button = QPushButton("Browse...")
            self.start_task_button = QPushButton("Start Task")
            self.task_status_label = QLabel(
                "Choose task settings, confirm BioSemi is ready, then click Start Task."
            )

            self.input_edit = QLineEdit()
            self.output_edit = QLineEdit()
            self.input_browse_button = QPushButton("Browse...")
            self.output_browse_button = QPushButton("Browse...")
            self.plot_channel_combo = QComboBox()
            self.plot_channel_combo.addItems(BIOSEMI64_CHANNELS)
            if PLOT_CHANNEL not in BIOSEMI64_CHANNELS:
                raise ValueError(
                    f"Configured PLOT_CHANNEL {PLOT_CHANNEL!r} is not a BioSemi64 "
                    "electrode. Correct sssep_batch/config.py before opening the "
                    "analysis launcher."
                )
            self.plot_channel_combo.setCurrentText(PLOT_CHANNEL)
            self.stimulation_frequency_edit = QLineEdit()
            self.stimulation_frequency_edit.setPlaceholderText("Optional")
            if STIMULATION_FREQUENCY_HZ is not None:
                self.stimulation_frequency_edit.setText(
                    f"{STIMULATION_FREQUENCY_HZ:g}"
                )
            self.save_checkbox = QCheckBox("Save folders for next time")
            self.save_checkbox.setChecked(True)
            self.process_button = QPushButton("Process Data")
            self.view_output_button = QPushButton("View Output")
            self.view_output_button.setEnabled(False)
            self.status_label = QLabel("Choose folders, then click Process Data.")
            self.saved_plots_tab = SavedPlotsPanel(parent=self)

            self._load_initial_folders()
            self._build_layout()
            apply_launcher_style(self)
            self._connect_signals()

        @staticmethod
        def _new_fixed_trigger_spin(code: int):
            """Show one study trigger code without allowing operator edits."""
            spin = QSpinBox()
            spin.setRange(code, code)
            spin.setValue(code)
            spin.setEnabled(False)
            spin.setToolTip("Fixed BioSemi trigger code for this study")
            return spin

        def _load_initial_folders(self) -> None:
            """Populate folder fields from saved settings or config defaults."""
            try:
                saved = load_saved_folders()
            except ValueError as exc:
                saved = {}
                self.status_label.setText(str(exc))

            input_default = saved.get("input_folder") or INPUT_FOLDER
            output_default = saved.get("output_root") or OUTPUT_ROOT
            self.input_edit.setText(input_default)
            self.output_edit.setText(output_default)
            self.task_log_edit.setText(output_default)
            self.saved_plots_tab.set_results_folder(output_default)

        def _build_layout(self) -> None:
            """Group the three workflows using the FPVS Studio visual hierarchy."""
            session_card = SectionCard(
                "Session settings", "Equal cue counts in a fresh random order."
            )
            session_form = make_form()
            session_form.addRow("Condition", self.condition_combo)
            session_form.addRow("Duration of each epoch", self.epoch_duration_spin)
            session_form.addRow("Break between epochs", self.break_duration_spin)
            session_form.addRow("Total epochs (even)", self.total_epochs_spin)
            session_card.body.addLayout(session_form)

            text_card = SectionCard(
                "Participant text", "The words shown on the fullscreen display."
            )
            text_form = make_form()
            text_form.addRow("Left hand text", self.left_hand_prompt_edit)
            text_form.addRow("Right hand text", self.right_hand_prompt_edit)
            text_form.addRow("Right ankle text", self.right_ankle_prompt_edit)
            text_form.addRow("Break text", self.break_prompt_edit)
            text_card.body.addLayout(text_form)

            trigger_card = SectionCard(
                "BioSemi trigger codes", "Fixed for this study; editing is disabled."
            )
            trigger_form = make_form()
            for label, spin in (
                ("Both hands: left hand", self.both_hands_left_code_spin),
                ("Both hands: right hand", self.both_hands_right_code_spin),
                ("Hand/ankle: right hand", self.hand_ankle_hand_code_spin),
                ("Hand/ankle: right ankle", self.hand_ankle_ankle_code_spin),
            ):
                trigger_form.addRow(label, spin)
            trigger_card.body.addLayout(trigger_form)

            run_card = SectionCard(
                "Task log and test mode", "TENS stimulation is controlled externally."
            )
            task_log_row = QHBoxLayout()
            task_log_row.addWidget(self.task_log_edit)
            task_log_row.addWidget(self.task_log_browse_button)
            run_card.body.addWidget(QLabel("Task log folder"))
            run_card.body.addLayout(task_log_row)
            run_card.body.addWidget(self.test_mode_checkbox)
            run_card.body.addWidget(hint_label(
                "Keep the CSV log with the participant's recording. Test mode "
                "runs the screens without sending BioSemi triggers."
            ))

            task_body, task_footer = build_page(self.task_tab)
            task_grid = QGridLayout()
            task_grid.setSpacing(12)
            task_grid.setColumnStretch(0, 1)
            task_grid.setColumnStretch(1, 1)
            task_grid.addWidget(session_card, 0, 0)
            task_grid.addWidget(text_card, 0, 1)
            task_grid.addWidget(trigger_card, 1, 0)
            task_grid.addWidget(run_card, 1, 1)
            task_body.addLayout(task_grid)
            self.task_status_label.setWordWrap(True)
            self.start_task_button.setProperty("uiRole", "primary")
            task_footer.addWidget(self.task_status_label, 1)
            task_footer.addWidget(self.start_task_button)

            input_row = QHBoxLayout()
            input_row.addWidget(self.input_edit)
            input_row.addWidget(self.input_browse_button)

            output_row = QHBoxLayout()
            output_row.addWidget(self.output_edit)
            output_row.addWidget(self.output_browse_button)

            files_card = SectionCard(
                "Recording folders", "Use one BDF file per participant."
            )
            files_form = make_form()
            files_form.addRow("Input folder", input_row)
            files_form.addRow("Output folder", output_row)
            files_card.body.addLayout(files_form)
            files_card.body.addWidget(self.save_checkbox)

            fft_card = SectionCard(
                "FFT output", "Full electrode data are saved for later plotting."
            )
            fft_form = make_form()
            fft_form.addRow("Electrode to plot", self.plot_channel_combo)
            fft_form.addRow(
                "TENS Unit Stimulation Frequency (Hz)",
                self.stimulation_frequency_edit,
            )
            fft_card.body.addLayout(fft_form)

            analysis_body, analysis_footer = build_page(self.analysis_tab)
            analysis_body.addWidget(hint_label(
                "Match the condition, epoch duration, and epoch count on Run "
                "Participant Task to your recordings. Same-cue epochs are "
                "averaged before FFT."
            ))
            analysis_body.addWidget(files_card)
            analysis_body.addWidget(fft_card)
            self.status_label.setWordWrap(True)
            self.process_button.setProperty("uiRole", "primary")
            analysis_footer.addWidget(self.status_label, 1)
            analysis_footer.addWidget(self.view_output_button)
            analysis_footer.addWidget(self.process_button)

            self.tabs.addTab(self.task_tab, "Run Participant Task")
            self.tabs.addTab(self.analysis_tab, "Analyze Recordings")
            self.tabs.addTab(self.saved_plots_tab, "Plot Saved FFT")
            layout = QVBoxLayout()
            layout.setContentsMargins(24, 18, 24, 18)
            layout.setSpacing(12)
            title = QLabel("SSSEP Task and Analysis")
            title.setProperty("uiRole", "title")
            layout.addWidget(title)
            layout.addWidget(hint_label("NERD Lab  |  Participant tasks and EEG analysis"))
            layout.addWidget(self.tabs)
            self.setLayout(layout)

        def _connect_signals(self) -> None:
            """Connect button clicks to the methods that handle them."""
            self.task_log_browse_button.clicked.connect(self._browse_task_log)
            self.start_task_button.clicked.connect(self._start_task)
            self.input_browse_button.clicked.connect(self._browse_input)
            self.output_browse_button.clicked.connect(self._browse_output)
            self.process_button.clicked.connect(self._start_processing)
            self.view_output_button.clicked.connect(self._view_output)
            self.saved_plots_tab.busy_changed.connect(
                self._saved_plot_busy_changed
            )

        def _browse_task_log(self) -> None:
            """Choose where the participant-task CSV log will be saved."""
            folder = QFileDialog.getExistingDirectory(
                self,
                "Choose Task Log Folder",
                self.task_log_edit.text().strip(),
            )
            if folder:
                self.task_log_edit.setText(folder)

        def _browse_input(self) -> None:
            """Open a folder picker for the input `.bdf` folder."""
            folder = QFileDialog.getExistingDirectory(
                self,
                "Choose Input Folder",
                self.input_edit.text().strip(),
            )
            if folder:
                self.input_edit.setText(folder)

        def _browse_output(self) -> None:
            """Open a folder picker for where analysis outputs should be saved."""
            folder = QFileDialog.getExistingDirectory(
                self,
                "Choose Output Folder",
                self.output_edit.text().strip(),
            )
            if folder:
                self.output_edit.setText(folder)

        def _start_processing(self) -> None:
            """Start setup checks and processing off the UI thread."""
            if self.worker is not None or self.task_running:
                return
            input_folder = self.input_edit.text().strip()
            output_root = self.output_edit.text().strip()
            plot_channel = self.plot_channel_combo.currentText().strip()
            try:
                analysis_protocol = self._analysis_protocol()
            except (TypeError, ValueError) as exc:
                message = str(exc) or type(exc).__name__
                self.status_label.setText(message)
                QMessageBox.warning(
                    self,
                    "Analysis Settings Need Attention",
                    message,
                )
                return
            self.output_folder = ""
            self._set_batch_running(True)
            self.status_label.setText("Checking folders, packages, and settings...")
            self.worker = BatchWorker(
                input_folder,
                output_root,
                plot_channel,
                analysis_protocol,
                self,
            )
            self.worker.progress_changed.connect(self._update_progress)
            self.worker.batch_finished.connect(self._processing_finished)
            self.worker.batch_failed.connect(self._processing_failed)
            self.worker.finished.connect(self._worker_finished)
            self.worker.finished.connect(self.worker.deleteLater)
            self.worker.start()

        def _task_settings(self) -> TaskSettings:
            """Build the validated participant settings currently shown."""
            log_folder = self.task_log_edit.text().strip()
            if not log_folder:
                raise ValueError("Choose a task log folder before starting the task.")
            return TaskSettings(
                condition=TaskCondition(self.condition_combo.currentData()),
                epoch_duration_sec=self.epoch_duration_spin.value(),
                total_epochs=self.total_epochs_spin.value(),
                trigger_codes=CueTriggerCodes(
                    self.both_hands_left_code_spin.value(),
                    self.both_hands_right_code_spin.value(),
                    self.hand_ankle_hand_code_spin.value(),
                    self.hand_ankle_ankle_code_spin.value(),
                ),
                output_folder=Path(log_folder),
                test_mode=self.test_mode_checkbox.isChecked(),
                break_duration_sec=self.break_duration_spin.value(),
                left_hand_prompt=self.left_hand_prompt_edit.text(),
                right_hand_prompt=self.right_hand_prompt_edit.text(),
                right_ankle_prompt=self.right_ankle_prompt_edit.text(),
                break_prompt=self.break_prompt_edit.text(),
            )

        def _analysis_protocol(self) -> AnalysisProtocol:
            """Use the visible task fields when cutting and labeling FFT epochs."""

            frequency_text = self.stimulation_frequency_edit.text().strip()
            target_hz: float | None = None
            if frequency_text:
                try:
                    target_hz = float(frequency_text)
                except ValueError as exc:
                    raise ValueError(
                        "Stimulation frequency must be a number, or left blank."
                    ) from exc
                if not isfinite(target_hz) or target_hz <= 0:
                    raise ValueError(
                        "Stimulation frequency must be a finite number above zero."
                    )

            return analysis_protocol_for_task(
                condition=TaskCondition(self.condition_combo.currentData()),
                epoch_duration_sec=self.epoch_duration_spin.value(),
                total_epochs=self.total_epochs_spin.value(),
                trigger_codes=CueTriggerCodes(
                    self.both_hands_left_code_spin.value(),
                    self.both_hands_right_code_spin.value(),
                    self.hand_ankle_hand_code_spin.value(),
                    self.hand_ankle_ankle_code_spin.value(),
                ),
                target_hz=target_hz,
            )

        def _start_task(self) -> None:
            """Validate task fields and start the Qt presentation session."""
            if self.task_running or self.worker is not None:
                return
            try:
                settings = self._task_settings()
            except (TypeError, ValueError) as exc:
                message = str(exc) or type(exc).__name__
                self.task_status_label.setText(message)
                QMessageBox.warning(self, "Task Settings Need Attention", message)
                return

            if settings.test_mode:
                response = QMessageBox.question(
                    self,
                    "Confirm Test Mode",
                    "Are you sure you want to run the experiment in test mode?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if response != QMessageBox.Yes:
                    return

            self.task_running = True
            self._set_task_running(True)
            if settings.test_mode:
                self.task_status_label.setText(
                    "Starting test mode without BioSemi triggers..."
                )
            else:
                self.task_status_label.setText(
                    f"Opening {settings.serial_port} before the participant screen..."
                )
            self.task_runner = QtTaskRunner(parent=self)
            self.task_runner.progress_changed.connect(self._update_task_progress)
            self.task_runner.task_finished.connect(self._task_finished)
            self.task_runner.task_failed.connect(self._task_failed)
            self.task_runner.task_done.connect(self._task_done)
            self.task_runner.start(settings)

        def closeEvent(self, event) -> None:
            """Block closing while participant or analysis work is active."""
            if self.worker is not None and self.worker.isRunning():
                event.ignore()
                self.status_label.setText(
                    "Processing is still running. Keep this window open until it finishes."
                )
                return
            if self.saved_plots_tab.is_busy():
                event.ignore()
                self.saved_plots_tab.show_busy_close_message()
                return
            if self.task_running:
                event.ignore()
                self.task_status_label.setText(
                    "The participant task is still running. Press Escape in the task "
                    "screen before closing this window."
                )
                return
            super().closeEvent(event)

        def _shutdown_application(self) -> None:
            """Finish active background work before Qt destroys its threads."""
            if self.task_runner is not None:
                self.task_runner.request_stop()
            if self.worker is not None and self.worker.isRunning():
                self.worker.wait()
            self.saved_plots_tab.wait_for_workers()

        def _worker_finished(self) -> None:
            """Release the stopped worker before accepting another run."""
            self.worker = None
            self._set_batch_running(False)

        def _set_batch_running(self, running: bool) -> None:
            """Enable or disable analysis controls during a batch."""
            self.input_edit.setEnabled(not running)
            self.output_edit.setEnabled(not running)
            self.input_browse_button.setEnabled(not running)
            self.output_browse_button.setEnabled(not running)
            self.plot_channel_combo.setEnabled(not running)
            self.stimulation_frequency_edit.setEnabled(not running)
            self.save_checkbox.setEnabled(not running)
            self.process_button.setEnabled(not running)
            self.view_output_button.setEnabled(False if running else bool(self.output_folder))
            self.tabs.setTabEnabled(0, not running)
            self.tabs.setTabEnabled(2, not running)

        def _set_task_running(self, running: bool) -> None:
            """Enable or disable task fields during a presentation."""
            for widget in (
                self.condition_combo,
                self.epoch_duration_spin,
                self.break_duration_spin,
                self.total_epochs_spin,
                self.left_hand_prompt_edit,
                self.right_hand_prompt_edit,
                self.right_ankle_prompt_edit,
                self.break_prompt_edit,
                self.test_mode_checkbox,
                self.task_log_edit,
                self.task_log_browse_button,
                self.start_task_button,
            ):
                widget.setEnabled(not running)
            self.tabs.setTabEnabled(1, not running)
            self.tabs.setTabEnabled(2, not running)

        def _saved_plot_busy_changed(self, working: bool) -> None:
            """Keep the task and analysis tabs idle during saved-result work."""

            self.tabs.setTabEnabled(0, not working)
            self.tabs.setTabEnabled(1, not working)

        def _update_task_progress(self, completed: int, total: int) -> None:
            """Show cue progress emitted by the presentation runner."""
            if completed == 0:
                self.task_status_label.setText(
                    f"Task started. Waiting to present {total} cue epochs."
                )
            else:
                self.task_status_label.setText(
                    f"Presented cue epoch {completed} of {total}."
                )

        def _task_finished(self, result) -> None:
            """Show the completed or aborted task result."""
            log_text = f" Log: {result.log_path}" if result.log_path else ""
            if result.aborted:
                reason = result.abort_reason or "The task was stopped."
                self.task_status_label.setText(
                    f"Task stopped after {result.completed_epochs} completed epoch(s). "
                    f"{reason}{log_text}"
                )
                if "trigger output failed" in reason.casefold():
                    QMessageBox.critical(self, "BioSemi Trigger Failed", reason)
                return
            self.task_status_label.setText(
                f"Task complete: {result.completed_epochs} epoch(s).{log_text}"
            )

        def _task_failed(self, exc: Exception) -> None:
            """Make task setup, display, serial, and log failures visible."""
            message = str(exc) or type(exc).__name__
            self.task_status_label.setText(message.splitlines()[0])
            QMessageBox.critical(
                self,
                "Participant Task Failed",
                f"{message}\n\nNo task was continued after this failure.",
            )

        def _task_done(self) -> None:
            """Release the completed task session and re-enable its controls."""
            runner = self.task_runner
            self.task_runner = None
            if runner is not None:
                runner.deleteLater()
            self.task_running = False
            self._set_task_running(False)

        def _update_progress(self, message: str, completed: int, total: int) -> None:
            """Show the latest worker progress message in the status label."""
            if total > 0:
                self.status_label.setText(f"{message} ({completed}/{total})")
            else:
                self.status_label.setText(message)

        def _processing_finished(self, result: dict[str, object]) -> None:
            """Show batch results while retaining the thread until it finishes."""
            self.output_folder = str(result["output_folder"])
            self.saved_plots_tab.set_results_folder(self.output_folder)
            failed = int(result.get("failed", 0) or 0)
            total = int(result.get("total_files", 0) or 0)
            participant_plot_failures = int(
                result.get("participant_plot_failures", 0) or 0
            )
            group_status = str(result.get("group_output_status", ""))
            group_plot_count = int(result.get("group_plot_count", 0) or 0)
            group_error_file = str(result.get("group_output_error_file", ""))
            group_plot_error_file = str(result.get("group_plot_error_file", ""))
            group_plot_errors = list(result.get("group_plot_errors", []) or [])
            skipped_group_cues = list(
                result.get("group_plot_skipped_trigger_codes", []) or []
            )
            group_plot_warnings = list(result.get("group_plot_warnings", []) or [])
            issues: list[str] = []
            if failed:
                issues.append(
                    f"{failed} of {total} participant file(s) failed; check the "
                    "batch summary"
                )
            if participant_plot_failures:
                issues.append(
                    f"{participant_plot_failures} participant cue plot(s) failed; "
                    "FFT data were retained"
                )
            if group_status == "failed":
                issues.append(
                    "some group results could not be created"
                    + (f"; see {group_error_file}" if group_error_file else "")
                )
            elif group_status == "skipped_no_usable_spectra":
                issues.append("no usable FFT spectra were available for group results")
            elif group_plot_errors:
                issues.append(
                    f"{len(group_plot_errors)} group cue plot(s) failed"
                    + (
                        f"; see {group_plot_error_file}"
                        if group_plot_error_file
                        else ""
                    )
                )
            elif skipped_group_cues:
                issues.append("some cue plots were skipped because data were unavailable")
            elif group_plot_warnings:
                issues.append(
                    "some group plots omit the baseline because matched data "
                    "were unavailable"
                )
            elif group_status == "success_with_warnings":
                issues.append("group results include warnings; check the batch log")

            if issues:
                self.status_label.setText(
                    "Processing finished with issues: " + "; ".join(issues) + ". "
                    "Click View Output for details."
                )
            else:
                self.status_label.setText(
                    f"Processing complete: {total} participant file(s), "
                    f"{group_plot_count} group cue plot(s). Click View Output."
                )
            if self.save_checkbox.isChecked():
                try:
                    save_folder_defaults(
                        self.input_edit.text().strip(), self.output_edit.text().strip()
                    )
                except OSError as exc:
                    QMessageBox.warning(
                        self,
                        "Could Not Save Folders",
                        f"Processing finished, but folder defaults were not saved.\n\n{exc}",
                    )

        def _processing_failed(self, exc: Exception) -> None:
            """Show a top-level failure message if the whole batch could not run."""
            message = str(exc) or type(exc).__name__
            self.status_label.setText(message.splitlines()[0])
            if isinstance(exc, BatchValidationError):
                QMessageBox.warning(self, "Setup Needs Attention", message)
                return
            QMessageBox.critical(
                self,
                "Processing Failed",
                f"{message}\n\n"
                "What to try next: check that the selected folders still exist, "
                "then review any ERROR.txt file in the output folder.",
            )

        def _view_output(self) -> None:
            """Open the selected output folder in the Windows file browser."""
            output_path = Path(self.output_folder)
            if not output_path.is_dir():
                QMessageBox.warning(
                    self,
                    "Output Folder Not Found",
                    f"The output folder does not exist yet:\n\n{output_path}",
                )
                return
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_path)))
            if not opened:
                QMessageBox.warning(
                    self,
                    "Could Not Open Output",
                    f"Could not open the output folder:\n\n{output_path}",
                )

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)

    window = LauncherWindow()
    app.aboutToQuit.connect(window._shutdown_application)
    app._sssep_launcher_window = window
    window.resize(1080, 800)
    window.show()

    if owns_app:
        return int(app.exec())
    return 0
