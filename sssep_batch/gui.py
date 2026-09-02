"""One PySide6 launcher for participant tasks and recording analysis.

Participant presentation runs on Qt's GUI thread. BDF processing and saved
plot work stay off the GUI thread.
"""

from __future__ import annotations

import sys
from dataclasses import replace
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
    TaskSettings,
    analysis_protocol_for_task,
)
from sssep_batch.models import AnalysisProtocol
from sssep_batch.launcher_settings import (
    SETTINGS_PATH,
    LauncherSettings,
    load_launcher_settings,
    load_saved_folders,
    save_folder_defaults,
    save_launcher_settings,
)


BIOSEMI64_CHANNELS = tuple(mne.channels.make_standard_montage("biosemi64").ch_names)


def _require_pyside6():
    """Import PySide6 lazily and provide a clear install message if missing."""
    try:
        from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
        from PySide6.QtGui import QAction, QActionGroup, QDesktopServices
        from PySide6.QtWidgets import (
            QApplication,
            QDialog,
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMenuBar,
            QMessageBox,
            QPushButton,
            QStackedWidget,
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
        "QAction": QAction,
        "QActionGroup": QActionGroup,
        "QDesktopServices": QDesktopServices,
        "QDialog": QDialog,
        "QFileDialog": QFileDialog,
        "QHBoxLayout": QHBoxLayout,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QMenuBar": QMenuBar,
        "QMessageBox": QMessageBox,
        "QPushButton": QPushButton,
        "Qt": Qt,
        "QStackedWidget": QStackedWidget,
        "QThread": QThread,
        "QTimer": QTimer,
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
    from sssep_batch.task_settings_gui import TaskSettingsDialog

    QApplication = qt["QApplication"]
    QAction = qt["QAction"]
    QActionGroup = qt["QActionGroup"]
    QDesktopServices = qt["QDesktopServices"]
    QDialog = qt["QDialog"]
    QFileDialog = qt["QFileDialog"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QLineEdit = qt["QLineEdit"]
    QMenuBar = qt["QMenuBar"]
    QMessageBox = qt["QMessageBox"]
    QPushButton = qt["QPushButton"]
    Qt = qt["Qt"]
    QStackedWidget = qt["QStackedWidget"]
    QThread = qt["QThread"]
    QTimer = qt["QTimer"]
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

            self.setWindowTitle("NERD Lab SSSEP Task")
            self.pages = QStackedWidget()
            self.task_page = QWidget()
            self.analysis_page = QWidget()

            self.session_settings = TaskSettings(
                epoch_duration_sec=EVENT_DURATION_SEC,
                epochs_per_condition=EXPECTED_REPETITIONS_PER_TRIGGER * 2,
                trigger_codes=CueTriggerCodes(11, 12, 21, 22),
            )
            self.settings_action = QAction("Settings...", self)
            self.start_task_button = QPushButton("Start SSSEP Task")
            self.task_status_label = QLabel("")
            self.task_status_label.hide()

            self.input_edit = QLineEdit()
            self.output_edit = QLineEdit()
            self.input_browse_button = QPushButton("Browse...")
            self.output_browse_button = QPushButton("Browse...")
            if PLOT_CHANNEL not in BIOSEMI64_CHANNELS:
                raise ValueError(
                    f"Configured PLOT_CHANNEL {PLOT_CHANNEL!r} is not a BioSemi64 "
                    "electrode. Correct sssep_batch/config.py before opening the "
                    "analysis launcher."
                )
            self.plot_channel = PLOT_CHANNEL
            self.stimulation_hz = STIMULATION_FREQUENCY_HZ
            self.remember_folders = True
            self.analysis_settings_label = hint_label("")
            self.process_button = QPushButton("Process Data")
            self.view_output_button = QPushButton("View Output")
            self.view_output_button.setEnabled(False)
            self.status_label = QLabel("Choose folders, then click Process Data.")
            self.saved_plots_page = SavedPlotsPanel(parent=self)

            self._load_settings()
            self._build_layout()
            apply_launcher_style(self)
            self._connect_signals()

        def _load_settings(self) -> None:
            """Restore saved preferences without changing fixed study settings."""
            defaults = LauncherSettings(
                task=replace(
                    self.session_settings,
                    output_folder=Path(OUTPUT_ROOT) if OUTPUT_ROOT else None,
                ),
                plot_channel=self.plot_channel,
                stimulation_hz=self.stimulation_hz,
                input_folder=INPUT_FOLDER,
                output_root=OUTPUT_ROOT,
            )
            self._settings_need_review = False
            try:
                saved = load_launcher_settings(
                    defaults, channels=BIOSEMI64_CHANNELS, settings_path=SETTINGS_PATH
                )
            except (OSError, TypeError, ValueError) as exc:
                saved = defaults
                self._settings_need_review = True
                message = (
                    f"Saved settings could not be loaded:\n{exc}\n\n"
                    "Review File > Settings and click Save before running a task "
                    "or processing recordings. The existing settings file has not changed."
                )
                QTimer.singleShot(0, lambda: QMessageBox.warning(
                    self, "Saved Settings Need Attention", message
                ))
            self.session_settings = saved.task
            self.plot_channel = saved.plot_channel
            self.stimulation_hz = saved.stimulation_hz
            self.remember_folders = saved.remember_folders
            self.input_edit.setText(saved.input_folder if saved.remember_folders else INPUT_FOLDER)
            self.output_edit.setText(saved.output_root if saved.remember_folders else OUTPUT_ROOT)
            self.saved_plots_page.set_results_folder(self.output_edit.text())

        def _build_layout(self) -> None:
            """Keep the task home minimal; select other workflows from View."""
            task_layout = QVBoxLayout(self.task_page)
            task_layout.setContentsMargins(24, 32, 24, 24)
            task_layout.setSpacing(18)
            task_layout.addStretch(1)
            self.start_task_button.setProperty("uiRole", "primary")
            self.start_task_button.setMinimumSize(260, 60)
            task_layout.addWidget(
                self.start_task_button, alignment=Qt.AlignmentFlag.AlignHCenter
            )
            settings_hint = hint_label("Change settings in File > Settings.")
            settings_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            task_layout.addWidget(settings_hint)
            task_layout.addStretch(1)

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

            fft_card = SectionCard(
                "FFT output", "Full electrode data are saved for later plotting."
            )
            fft_card.body.addWidget(self.analysis_settings_label)
            fft_card.body.addWidget(hint_label("Change analysis settings in File > Settings."))

            analysis_body, analysis_footer = build_page(self.analysis_page)
            analysis_body.addWidget(hint_label(
                "Match the epoch duration and epochs per condition in File > "
                "Settings to your recordings. Epochs for the same trigger code "
                "are averaged before FFT."
            ))
            analysis_body.addWidget(files_card)
            analysis_body.addWidget(fft_card)
            self.status_label.setWordWrap(True)
            self.process_button.setProperty("uiRole", "primary")
            analysis_footer.addWidget(self.status_label, 1)
            analysis_footer.addWidget(self.view_output_button)
            analysis_footer.addWidget(self.process_button)

            for page in (self.task_page, self.analysis_page, self.saved_plots_page):
                self.pages.addWidget(page)
            layout = QVBoxLayout()
            layout.setContentsMargins(24, 18, 24, 18)
            layout.setSpacing(12)
            menu_bar = QMenuBar(self)
            menu_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.file_menu = menu_bar.addMenu("File")
            # Retain the wrapper so Qt's menu action survives Python collection.
            self.file_menu_action = self.file_menu.menuAction()
            self.file_menu.addAction(self.settings_action)
            self.view_menu = menu_bar.addMenu("View")
            self.view_menu_action = self.view_menu.menuAction()
            self.view_action_group = QActionGroup(self)
            self.view_actions = []
            for index, name in enumerate(("SSSEP Task", "Process Data", "Generate FFT Plots")):
                action = QAction(name, self)
                action.setCheckable(True)
                action.triggered.connect(lambda _checked=False, i=index: self._show_view(i))
                self.view_action_group.addAction(action)
                self.view_menu.addAction(action)
                self.view_actions.append(action)
            layout.setMenuBar(menu_bar)
            self.title_label = QLabel("NERD Lab SSSEP Task")
            self.title_label.setProperty("uiRole", "title")
            layout.addWidget(self.title_label)
            layout.addWidget(self.pages)
            self.setLayout(layout)
            self._refresh_settings_summary()
            self._show_view(0)

        def _show_view(self, index: int) -> None:
            """Change workflow only when its action is available."""
            if not self.view_actions[index].isEnabled():
                return
            self.pages.setCurrentIndex(index)
            self.view_actions[index].setChecked(True)
            self.title_label.setText(
                ("NERD Lab SSSEP Task", "Process Data", "Generate FFT Plots")[index]
            )
            if index == 2:
                self.saved_plots_page.ensure_results_loaded()

        def _connect_signals(self) -> None:
            """Connect button clicks to the methods that handle them."""
            self.settings_action.triggered.connect(self._open_settings)
            self.start_task_button.clicked.connect(self._start_task)
            self.input_browse_button.clicked.connect(self._browse_input)
            self.output_browse_button.clicked.connect(self._browse_output)
            self.process_button.clicked.connect(self._start_processing)
            self.view_output_button.clicked.connect(self._view_output)
            self.saved_plots_page.busy_changed.connect(
                self._saved_plot_busy_changed
            )

        def _open_settings(self) -> None:
            """Apply a validated draft only after the operator chooses Save."""
            if self.worker is not None or self.task_running or self.saved_plots_page.is_busy():
                return
            dialog = TaskSettingsDialog(
                self.session_settings,
                channels=BIOSEMI64_CHANNELS,
                plot_channel=self.plot_channel,
                stimulation_hz=self.stimulation_hz,
                remember_folders=self.remember_folders,
                parent=self,
                on_save=self._save_settings_draft,
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.session_settings = dialog.settings
                self.plot_channel = dialog.plot_channel
                self.stimulation_hz = dialog.stimulation_hz
                self.remember_folders = dialog.remember_folders
                self._settings_need_review = False
                self._refresh_settings_summary()
            dialog.deleteLater()

        def _save_settings_draft(self, task, plot_channel, stimulation_hz, remember_folders) -> None:
            """Persist the validated draft before the Settings dialog accepts it."""
            save_launcher_settings(
                LauncherSettings(
                    task=task, plot_channel=plot_channel, stimulation_hz=stimulation_hz,
                    remember_folders=remember_folders,
                    input_folder=self.input_edit.text().strip() if remember_folders else "",
                    output_root=self.output_edit.text().strip() if remember_folders else "",
                ),
                settings_path=SETTINGS_PATH,
            )

        def _refresh_settings_summary(self) -> None:
            settings = self.session_settings
            frequency = "Not set" if self.stimulation_hz is None else f"{self.stimulation_hz:g} Hz"
            self.analysis_settings_label.setText(
                f"Both conditions  |  {settings.epoch_duration_sec:g}-second epochs  |  "
                f"{settings.epochs_per_condition} epochs per condition\n"
                f"Electrode: {self.plot_channel}  |  TENS stimulation frequency: {frequency}"
            )

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
            if self.worker is not None or self.task_running or self.saved_plots_page.is_busy():
                return
            input_folder = self.input_edit.text().strip()
            output_root = self.output_edit.text().strip()
            plot_channel = self.plot_channel
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
            """Require a log destination before starting the accepted session."""
            self._require_reviewed_settings()
            if self.session_settings.output_folder is None:
                raise ValueError("Choose a task log folder in File > Settings before starting.")
            return self.session_settings

        def _analysis_protocol(self) -> AnalysisProtocol:
            """Use the accepted session settings for both recorded conditions."""
            self._require_reviewed_settings()
            return analysis_protocol_for_task(
                epoch_duration_sec=self.session_settings.epoch_duration_sec,
                epochs_per_condition=self.session_settings.epochs_per_condition,
                trigger_codes=self.session_settings.trigger_codes,
                target_hz=self.stimulation_hz,
            )

        def _require_reviewed_settings(self) -> None:
            if self._settings_need_review:
                raise ValueError("Review File > Settings and click Save before continuing.")

        def _start_task(self) -> None:
            """Validate task fields and start the Qt presentation session."""
            if self.task_running or self.worker is not None or self.saved_plots_page.is_busy():
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
            if self.saved_plots_page.is_busy():
                event.ignore()
                self.saved_plots_page.show_busy_close_message()
                return
            if self.task_running:
                event.ignore()
                self.task_status_label.setText(
                    "The participant task is still running. Press Escape in the task "
                    "screen before closing this window."
                )
                return
            if self.remember_folders and not self._settings_need_review:
                self._save_recording_folders()
            super().closeEvent(event)

        def _shutdown_application(self) -> None:
            """Finish active background work before Qt destroys its threads."""
            if self.task_runner is not None:
                self.task_runner.request_stop()
            if self.worker is not None and self.worker.isRunning():
                self.worker.wait()
            self.saved_plots_page.wait_for_workers()

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
            self._set_navigation_busy(running)
            self.process_button.setEnabled(not running)
            self.view_output_button.setEnabled(False if running else bool(self.output_folder))

        def _set_task_running(self, running: bool) -> None:
            """Enable or disable task fields during a presentation."""
            self._set_navigation_busy(running)
            self.start_task_button.setEnabled(not running)

        def _saved_plot_busy_changed(self, working: bool) -> None:
            """Keep other workflows idle during saved-result work."""
            self._set_navigation_busy(working)

        def _set_navigation_busy(self, working: bool) -> None:
            self.settings_action.setEnabled(not working)
            for action in self.view_actions:
                action.setEnabled(not working)

        def _update_task_progress(self, completed: int, total: int) -> None:
            """Show cue progress emitted by the presentation runner."""
            if completed == 0:
                self.task_status_label.setText(
                    f"Task started. Waiting to present {total} epochs."
                )
            else:
                self.task_status_label.setText(
                    f"Presented epoch {completed} of {total}."
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
            self.saved_plots_page.set_results_folder(self.output_folder)
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
                    f"{participant_plot_failures} participant trigger code plot(s) failed; "
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
                    f"{len(group_plot_errors)} group trigger code plot(s) failed"
                    + (
                        f"; see {group_plot_error_file}"
                        if group_plot_error_file
                        else ""
                    )
                )
            elif skipped_group_cues:
                issues.append("some trigger code plots were skipped because data were unavailable")
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
                    f"{group_plot_count} group trigger code plot(s). Click View Output."
                )
            if self.remember_folders:
                self._save_recording_folders()

        def _save_recording_folders(self) -> None:
            try:
                save_folder_defaults(
                    self.input_edit.text().strip(), self.output_edit.text().strip(),
                    settings_path=SETTINGS_PATH,
                )
            except (OSError, ValueError) as exc:
                QMessageBox.warning(
                    self, "Could Not Save Folders",
                    f"Recording folders could not be saved. Other settings were kept.\n\n{exc}",
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
