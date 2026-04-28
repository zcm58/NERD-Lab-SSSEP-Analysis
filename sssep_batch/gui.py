"""PySide6 launcher used by beginner users to run the batch processor.

The intended workflow is: run `sssep_bdf_batch_processor.py` in PyCharm, choose
an input folder and output folder, click `Process Data`, and open the output
folder when processing finishes. This module keeps the GUI small and delegates
real work to `sssep_batch.batch`.

Long processing runs happen in a `QThread` so the window can keep updating
status text instead of freezing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sssep_batch.batch import BatchValidationError, run_batch, run_preflight_checks
from sssep_batch.config import INPUT_FOLDER, OUTPUT_ROOT


REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = REPO_ROOT / ".sssep_gui_settings.json"


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
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMessageBox,
            QPushButton,
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
        "QDesktopServices": QDesktopServices,
        "QFileDialog": QFileDialog,
        "QFormLayout": QFormLayout,
        "QHBoxLayout": QHBoxLayout,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QMessageBox": QMessageBox,
        "QPushButton": QPushButton,
        "QThread": QThread,
        "QUrl": QUrl,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
        "Signal": Signal,
    }


def launch_gui() -> int:
    """Open the launcher window and return the Qt application exit code."""
    qt = _require_pyside6()

    QApplication = qt["QApplication"]
    QCheckBox = qt["QCheckBox"]
    QDesktopServices = qt["QDesktopServices"]
    QFileDialog = qt["QFileDialog"]
    QFormLayout = qt["QFormLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QLineEdit = qt["QLineEdit"]
    QMessageBox = qt["QMessageBox"]
    QPushButton = qt["QPushButton"]
    QThread = qt["QThread"]
    QUrl = qt["QUrl"]
    QVBoxLayout = qt["QVBoxLayout"]
    QWidget = qt["QWidget"]
    Signal = qt["Signal"]

    class BatchWorker(QThread):
        """Run `run_batch()` off the UI thread and emit Qt progress signals."""

        progress_changed = Signal(str, int, int)
        batch_finished = Signal(object)
        batch_failed = Signal(str)

        def __init__(self, input_folder: str, output_root: str) -> None:
            """Remember the selected folders for the background run."""
            super().__init__()
            self.input_folder = input_folder
            self.output_root = output_root

        def run(self) -> None:
            """Execute the batch and translate success/failure into signals."""
            try:
                result = run_batch(
                    self.input_folder,
                    self.output_root,
                    progress_callback=self._handle_progress,
                )
            except Exception as exc:
                self.batch_failed.emit(str(exc))
            else:
                self.batch_finished.emit(result)

        def _handle_progress(self, event: dict[str, object]) -> None:
            """Convert a structured progress event into simple GUI signal values."""
            message = str(event.get("message", "Processing..."))
            completed = int(event.get("completed", 0) or 0)
            total = int(event.get("total", 0) or 0)
            self.progress_changed.emit(message, completed, total)

    class LauncherWindow(QWidget):
        """Main launcher widget with folder fields, buttons, and status text."""

        def __init__(self) -> None:
            """Create widgets, load saved folders, and wire up button actions."""
            super().__init__()
            self.worker: BatchWorker | None = None
            self.output_folder = ""

            self.setWindowTitle("SSSEP Batch Processor")
            self.input_edit = QLineEdit()
            self.output_edit = QLineEdit()
            self.input_browse_button = QPushButton("Browse...")
            self.output_browse_button = QPushButton("Browse...")
            self.save_checkbox = QCheckBox("Save folders for next time")
            self.save_checkbox.setChecked(True)
            self.process_button = QPushButton("Process Data")
            self.view_output_button = QPushButton("View Output")
            self.view_output_button.setEnabled(False)
            self.status_label = QLabel("Choose folders, then click Process Data.")

            self._load_initial_folders()
            self._build_layout()
            self._connect_signals()

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
            self.output_folder = output_default

        def _build_layout(self) -> None:
            """Assemble the small form-style launcher layout."""
            input_row = QHBoxLayout()
            input_row.addWidget(self.input_edit)
            input_row.addWidget(self.input_browse_button)

            output_row = QHBoxLayout()
            output_row.addWidget(self.output_edit)
            output_row.addWidget(self.output_browse_button)

            form = QFormLayout()
            form.addRow("Input folder", input_row)
            form.addRow("Output folder", output_row)

            button_row = QHBoxLayout()
            button_row.addWidget(self.process_button)
            button_row.addWidget(self.view_output_button)

            layout = QVBoxLayout()
            layout.addLayout(form)
            layout.addWidget(self.save_checkbox)
            layout.addLayout(button_row)
            layout.addWidget(self.status_label)
            self.setLayout(layout)

        def _connect_signals(self) -> None:
            """Connect button clicks to the methods that handle them."""
            self.input_browse_button.clicked.connect(self._browse_input)
            self.output_browse_button.clicked.connect(self._browse_output)
            self.process_button.clicked.connect(self._start_processing)
            self.view_output_button.clicked.connect(self._view_output)

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
                self.output_folder = folder

        def _start_processing(self) -> None:
            """Run preflight checks, save defaults if requested, and start work."""
            input_folder = self.input_edit.text().strip()
            output_root = self.output_edit.text().strip()

            try:
                preflight = run_preflight_checks(input_folder, output_root)
            except BatchValidationError as exc:
                message = str(exc)
                self.status_label.setText(message.splitlines()[0])
                QMessageBox.warning(self, "Setup Needs Attention", message)
                return

            if self.save_checkbox.isChecked():
                try:
                    save_folder_defaults(input_folder, output_root)
                except OSError as exc:
                    QMessageBox.warning(
                        self,
                        "Could Not Save Folders",
                        f"Processing will continue, but folder defaults were not saved.\n\n{exc}",
                    )

            self.output_folder = output_root
            self._set_running(True)
            self.status_label.setText(
                f"Setup checks passed. Starting {preflight['bdf_file_count']} file(s)..."
            )
            self.worker = BatchWorker(input_folder, output_root)
            self.worker.progress_changed.connect(self._update_progress)
            self.worker.batch_finished.connect(self._processing_finished)
            self.worker.batch_failed.connect(self._processing_failed)
            self.worker.start()

        def _set_running(self, running: bool) -> None:
            """Enable or disable controls while the background worker runs."""
            self.input_edit.setEnabled(not running)
            self.output_edit.setEnabled(not running)
            self.input_browse_button.setEnabled(not running)
            self.output_browse_button.setEnabled(not running)
            self.save_checkbox.setEnabled(not running)
            self.process_button.setEnabled(not running)
            self.view_output_button.setEnabled(False if running else bool(self.output_folder))

        def _update_progress(self, message: str, completed: int, total: int) -> None:
            """Show the latest worker progress message in the status label."""
            if total > 0:
                self.status_label.setText(f"{message} ({completed}/{total})")
            else:
                self.status_label.setText(message)

        def _processing_finished(self, result: dict[str, object]) -> None:
            """Show final batch status and re-enable output viewing."""
            self._set_running(False)
            self.view_output_button.setEnabled(True)
            failed = int(result.get("failed", 0) or 0)
            total = int(result.get("total_files", 0) or 0)
            summary_csv = result.get("summary_csv", "")
            if failed:
                self.status_label.setText(
                    f"Processing finished with {failed} failed file(s) out of {total}. "
                    f"Open the batch summary and check the error_file column: {summary_csv}"
                )
            else:
                self.status_label.setText(
                    f"Processing complete: {total} file(s) processed. "
                    f"Batch summary: {summary_csv}"
                )
            self.worker = None

        def _processing_failed(self, message: str) -> None:
            """Show a top-level failure message if the whole batch could not run."""
            self._set_running(False)
            self.view_output_button.setEnabled(False)
            self.status_label.setText(message.splitlines()[0])
            QMessageBox.critical(
                self,
                "Processing Failed",
                f"{message}\n\n"
                "What to try next: check that the selected folders still exist, "
                "then review any ERROR.txt file in the output folder.",
            )
            self.worker = None

        def _view_output(self) -> None:
            """Open the selected output folder in the Windows file browser."""
            output_path = Path(self.output_folder)
            if not output_path.exists():
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
    window.resize(700, 180)
    window.show()

    if owns_app:
        return int(app.exec())
    return 0
