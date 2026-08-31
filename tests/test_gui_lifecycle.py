"""Exercise real Qt/thread shutdown in a separate process, without EEG data."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("outcome", ["success", "validation_error"])
def test_launcher_retains_worker_and_opens_actual_run_folder(tmp_path, outcome):
    """Closing during a batch is blocked; finished workers can be closed safely."""
    script = tmp_path / "launcher_probe.py"
    script.write_text(textwrap.dedent(r'''
        from concurrent.futures import ProcessPoolExecutor
        from pathlib import Path
        import sys
        import threading
        import traceback

        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        import sssep_batch.gui as gui

        def fake_batch(input_folder, output_root, progress_callback=None):
            assert threading.current_thread() is not threading.main_thread()
            with ProcessPoolExecutor(max_workers=1) as executor:
                future = executor.submit(sum, [1, 2, 3])
                started.set()
                assert release.wait(10), "GUI did not release the synthetic worker"
                assert future.result(timeout=10) == 6
            if outcome == "validation_error":
                raise gui.BatchValidationError("No .bdf files were found.")
            return {
                "output_folder": str(run_folder),
                "summary_csv": str(run_folder / "batch_processing_summary.csv"),
                "total_files": 1,
                "failed": 0,
            }

        def checked(callback):
            def wrapped(*args):
                try:
                    callback(*args)
                except BaseException:
                    errors.append(traceback.format_exc())
                    release.set()
                    QApplication.instance().exit(1)
            return wrapped

        @checked
        def start_probe():
            window = next(w for w in QApplication.topLevelWidgets()
                          if w.windowTitle() == "SSSEP Batch Processor")
            window.input_edit.setText(str(input_folder))
            window.output_edit.setText(str(output_root))
            window._start_processing()

            @checked
            def check_result_signal(result):
                assert window.worker is not None, "Thread released before finished"
                assert not window.process_button.isEnabled()
                observed.add("result")

            @checked
            def wait_for_worker():
                if not started.is_set():
                    QTimer.singleShot(10, wait_for_worker)
                    return
                assert window.worker.isRunning()
                assert not window.close(), "Active worker window accepted close"
                assert window.isVisible()
                assert not window.process_button.isEnabled()
                release.set()
                QTimer.singleShot(10, wait_for_finished)

            @checked
            def wait_for_finished():
                if window.worker is not None:
                    QTimer.singleShot(10, wait_for_finished)
                    return
                assert window.process_button.isEnabled()
                assert window.output_edit.text() == str(output_root)
                if outcome == "success":
                    assert window.output_folder == str(run_folder)
                    assert window.view_output_button.isEnabled()
                    assert saved == [(str(input_folder), str(output_root))]
                    window._view_output()
                    assert opened == [str(run_folder)]
                    assert not messages
                else:
                    assert not window.output_folder
                    assert not window.view_output_button.isEnabled()
                    assert saved == []
                    assert messages == [("Setup Needs Attention", "No .bdf files were found.")]
                assert window.close(), "Stopped worker prevented window close"
                observed.add("closed")

            window.worker.batch_finished.connect(check_result_signal)
            window.worker.batch_failed.connect(check_result_signal)
            QTimer.singleShot(0, wait_for_worker)

        class AppFactory:
            @staticmethod
            def instance():
                return QApplication.instance()

            def __new__(cls, argv):
                app = QApplication(argv)
                QTimer.singleShot(0, start_probe)
                QTimer.singleShot(15000, lambda: app.exit(2))
                return app

        class MessageBox:
            @staticmethod
            def warning(parent, title, message):
                messages.append((title, message))
            critical = warning

        class DesktopServices:
            @staticmethod
            def openUrl(url):
                opened.append(str(Path(url.toLocalFile())))
                return True

        if __name__ == "__main__":
            input_folder, output_root = map(Path, sys.argv[1:3])
            outcome = sys.argv[3]
            run_folder = output_root / "run_test"
            run_folder.mkdir(parents=True)
            started, release = threading.Event(), threading.Event()
            saved, opened, messages, errors = [], [], [], []
            observed = set()
            gui.run_batch = fake_batch
            gui.load_saved_folders = lambda: {}
            gui.save_folder_defaults = lambda *args: saved.append(args)
            qt = gui._require_pyside6()
            qt.update(QApplication=AppFactory, QMessageBox=MessageBox,
                      QDesktopServices=DesktopServices)
            gui._require_pyside6 = lambda: qt
            exit_code = gui.launch_gui()
            assert exit_code == 0, (exit_code, errors)
            assert observed == {"result", "closed"}, (observed, errors)
            print("LIFECYCLE_OK")
    '''), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root))
    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "input"),
         str(tmp_path / "output"), outcome],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "LIFECYCLE_OK" in completed.stdout
