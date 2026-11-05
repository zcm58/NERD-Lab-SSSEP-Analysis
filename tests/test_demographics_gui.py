"""Demographics export wiring in an isolated Qt process."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_file_menu_demographics_export_uses_task_logs_and_restores_controls(tmp_path):
    script = tmp_path / "demographics_probe.py"
    script.write_text(textwrap.dedent(r'''
        import csv
        from dataclasses import replace
        from pathlib import Path
        import sys
        import threading
        import time

        from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
        import sssep_batch.gui as gui

        workspace = Path(sys.argv[1])
        task_logs = workspace / "task logs"
        task_logs.mkdir()
        other_logs = workspace / "other logs"
        other_logs.mkdir()
        log = task_logs / "sssep_task_events_sample.csv"
        row = {
            "participant_number": "007", "participant_age": "22",
            "participant_sex": "Female", "participant_handedness": "Right handed",
            "participant_colorblind": "False", "run_id": "sample-run",
            "started_at_utc": "2026-10-01T16:00:00+00:00",
            "run_aborted": "False", "test_mode": "False",
        }
        with log.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=row)
            writer.writeheader()
            writer.writerows([row, row])
        original = log.read_bytes()

        def preferences(defaults, **_kwargs):
            return replace(defaults, task=replace(defaults.task, output_folder=task_logs),
                           remember_folders=False, output_root="")

        gui.load_launcher_settings = preferences
        save_selection = None
        folder_selection = ""
        save_dialog_sources = []
        folder_dialog_calls = []

        class ProbeFileDialog(QFileDialog):
            @staticmethod
            def getExistingDirectory(parent, title, directory):
                folder_dialog_calls.append((title, directory))
                return folder_selection

            def exec(self):
                save_dialog_sources.append(Path(self.directory().absolutePath()))
                assert self.acceptMode() == QFileDialog.AcceptMode.AcceptSave
                assert self.defaultSuffix() == "csv"
                assert Path(self.selectedFiles()[0]).name == "participant_demographics.csv"
                if save_selection is None:
                    return QDialog.DialogCode.Rejected
                self.selectFile(str(save_selection))
                return QDialog.DialogCode.Accepted

        qt = gui._require_pyside6()
        qt["QFileDialog"] = ProbeFileDialog
        gui._require_pyside6 = lambda: qt
        messages = []
        QMessageBox.information = lambda _parent, title, text: messages.append(("info", title, text))
        QMessageBox.warning = lambda _parent, title, text: messages.append(("warning", title, text))

        export = gui.export_demographics
        release = threading.Event()
        calls = []

        def observed_export(source, destination):
            assert threading.current_thread() is not threading.main_thread()
            calls.append((source, destination))
            assert release.wait(8), "GUI probe did not release the export"
            return export(source, destination)

        gui.export_demographics = observed_export
        app = QApplication([])
        assert gui.launch_gui() == 0
        window = app._sssep_launcher_window
        action = window.demographics_action
        assert action in window.file_menu.actions()
        assert action.text().rstrip(".…") == "Export Participant Demographics"

        action.trigger()
        assert save_dialog_sources == [task_logs]
        assert not folder_dialog_calls and not calls
        assert window.demographics_worker is None and action.isEnabled()

        save_selection = workspace / "selected demographics"
        output = save_selection.with_suffix(".csv")
        action.trigger()
        try:
            assert window.demographics_worker is not None
            assert not action.isEnabled() and not window.pages.isEnabled()
            assert not window.close(), "Window closed during an active export"
        finally:
            release.set()
            if window.demographics_worker is not None:
                assert window.demographics_worker.wait(8000)
        deadline = time.monotonic() + 8
        while window.demographics_worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert window.demographics_worker is None
        assert action.isEnabled() and window.pages.isEnabled()
        assert window.settings_action.isEnabled()
        assert all(action.isEnabled() for action in window.view_actions)
        assert calls == [(task_logs, output)]
        assert len(messages) == 1 and messages[0][0] == "info"
        assert "Exported 1 task run" in messages[0][2] and str(output) in messages[0][2]
        with output.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert rows[0]["participant_number"] == "007"
        assert rows[0]["source_file"] == log.name
        assert log.read_bytes() == original

        window.session_settings = replace(window.session_settings, output_folder=None)
        action.trigger()
        assert len(folder_dialog_calls) == 1
        assert save_dialog_sources == [task_logs, task_logs]
        folder_selection = str(other_logs)
        save_selection = None
        action.trigger()
        assert len(folder_dialog_calls) == 2
        assert save_dialog_sources == [task_logs, task_logs, other_logs]
        assert window.session_settings.output_folder is None
        assert calls == [(task_logs, output)]
        assert window.demographics_worker is None and action.isEnabled()
        assert window.close()
        print("DEMOGRAPHICS_GUI_OK")
    '''), encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        cwd=repo_root,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "DEMOGRAPHICS_GUI_OK" in completed.stdout
