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

        def fake_batch(input_folder, output_root, progress_callback=None,
                       plot_channel=None, analysis_protocol=None):
            assert threading.current_thread() is not threading.main_thread()
            assert plot_channel == "C4"
            assert analysis_protocol.active_event_codes == (11, 12)
            assert analysis_protocol.event_duration_sec == 7.5
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
                          if w.windowTitle() == "SSSEP Task and Analysis")
            assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
                "Run Participant Task", "Analyze Recordings", "Plot Saved FFT"
            ]
            window.input_edit.setText(str(input_folder))
            window.output_edit.setText(str(output_root))
            window.plot_channel_combo.setCurrentText("C4")
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
                assert not window.tabs.isTabEnabled(2)
                release.set()
                QTimer.singleShot(10, wait_for_finished)

            @checked
            def wait_for_finished():
                if window.worker is not None:
                    QTimer.singleShot(10, wait_for_finished)
                    return
                assert window.process_button.isEnabled()
                assert window.tabs.isTabEnabled(2)
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


@pytest.mark.parametrize(
    ("app_mode", "shutdown_method"),
    [("owned", "quit"), ("owned", "exit"), ("existing", "quit")],
)
def test_application_shutdown_stops_presentation_thread(
    tmp_path, app_mode, shutdown_method
):
    """Qt-level quit paths must stop the idle persistent presentation thread."""
    script = tmp_path / "application_shutdown_probe.py"
    script.write_text(
        textwrap.dedent(
            r'''
            import gc
            import sys
            import traceback

            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            import sssep_batch.gui as gui

            def checked(callback):
                def wrapped():
                    try:
                        callback()
                    except BaseException:
                        errors.append(traceback.format_exc())
                        QApplication.instance().exit(1)
                return wrapped

            @checked
            def request_shutdown():
                app = QApplication.instance()
                window = app._sssep_launcher_window
                assert window.isVisible()
                assert window.task_thread.isRunning()
                if shutdown_method == "quit":
                    app.quit()
                else:
                    app.exit(0)

            class AppFactory:
                @staticmethod
                def instance():
                    return QApplication.instance()

                def __new__(cls, argv):
                    app = QApplication(argv)
                    QTimer.singleShot(0, request_shutdown)
                    QTimer.singleShot(10000, lambda: app.exit(2))
                    return app

            if __name__ == "__main__":
                app_mode, shutdown_method = sys.argv[1:3]
                errors = []
                gui.load_saved_folders = lambda: {}

                if app_mode == "existing":
                    app = QApplication(sys.argv)
                    assert gui.launch_gui() == 0
                    gc.collect()
                    assert app._sssep_launcher_window.isVisible()
                    QTimer.singleShot(0, request_shutdown)
                    QTimer.singleShot(10000, lambda: app.exit(2))
                    exit_code = app.exec()
                else:
                    qt = gui._require_pyside6()
                    qt.update(QApplication=AppFactory)
                    gui._require_pyside6 = lambda: qt
                    exit_code = gui.launch_gui()
                    app = QApplication.instance()

                assert exit_code == 0, (exit_code, errors)
                assert not errors, errors
                window = app._sssep_launcher_window
                assert not window.task_thread.isRunning()
                print("APPLICATION_SHUTDOWN_OK")
            '''
        ),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root))
    completed = subprocess.run(
        [sys.executable, str(script), app_mode, shutdown_method],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "APPLICATION_SHUTDOWN_OK" in completed.stdout


def test_application_exit_cooperatively_stops_active_participant_task(tmp_path):
    """A direct Qt exit must abort and join an active presentation worker."""
    script = tmp_path / "active_task_shutdown_probe.py"
    script.write_text(
        textwrap.dedent(
            r'''
            from pathlib import Path
            from types import SimpleNamespace
            import sys
            import threading
            import time

            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            import sssep_batch.gui as gui

            started = threading.Event()

            def fake_task(settings, *, progress_callback=None, abort_requested=None):
                assert threading.current_thread() is not threading.main_thread()
                assert abort_requested is not None
                started.set()
                deadline = time.monotonic() + 10
                while not abort_requested() and time.monotonic() < deadline:
                    time.sleep(0.001)
                assert abort_requested(), "shutdown request never reached active task"
                return SimpleNamespace(
                    aborted=True,
                    abort_reason="Application shutdown requested during a cue epoch.",
                    completed_epochs=0,
                    log_path=None,
                )

            def request_shutdown_when_started():
                if not started.is_set():
                    QTimer.singleShot(10, request_shutdown_when_started)
                    return
                window = QApplication.instance()._sssep_launcher_window
                assert window.task_running
                QApplication.instance().exit(0)

            class AppFactory:
                @staticmethod
                def instance():
                    return QApplication.instance()

                def __new__(cls, argv):
                    app = QApplication(argv)
                    QTimer.singleShot(0, start_task)
                    QTimer.singleShot(10000, lambda: app.exit(2))
                    return app

            def start_task():
                window = QApplication.instance()._sssep_launcher_window
                window.task_log_edit.setText(str(log_folder))
                window._start_task()
                QTimer.singleShot(0, request_shutdown_when_started)

            if __name__ == "__main__":
                log_folder = Path(sys.argv[1])
                gui.load_saved_folders = lambda: {}
                gui.run_participant_task = fake_task
                qt = gui._require_pyside6()
                qt.update(QApplication=AppFactory)
                gui._require_pyside6 = lambda: qt

                exit_code = gui.launch_gui()
                app = QApplication.instance()
                window = app._sssep_launcher_window
                assert exit_code == 0
                assert not window.task_thread.isRunning()
                print("ACTIVE_TASK_SHUTDOWN_OK")
            '''
        ),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root))

    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "logs")],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ACTIVE_TASK_SHUTDOWN_OK" in completed.stdout


def test_application_exit_waits_for_active_batch_worker(tmp_path):
    """A direct Qt exit must join an analysis thread before returning."""
    script = tmp_path / "active_batch_shutdown_probe.py"
    script.write_text(
        textwrap.dedent(
            r'''
            from pathlib import Path
            import sys
            import threading
            import time

            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            import sssep_batch.gui as gui

            started = threading.Event()

            def fake_batch(input_folder, output_root, progress_callback=None,
                           plot_channel=None, analysis_protocol=None):
                assert threading.current_thread() is not threading.main_thread()
                started.set()
                time.sleep(0.25)
                return {
                    "output_folder": str(output_root),
                    "summary_csv": str(Path(output_root) / "batch_processing_summary.csv"),
                    "total_files": 1,
                    "failed": 0,
                }

            def request_shutdown_when_started():
                if not started.is_set():
                    QTimer.singleShot(10, request_shutdown_when_started)
                    return
                window = QApplication.instance()._sssep_launcher_window
                assert window.worker is not None and window.worker.isRunning()
                QApplication.instance().exit(0)

            def start_batch():
                window = QApplication.instance()._sssep_launcher_window
                window.input_edit.setText(str(input_folder))
                window.output_edit.setText(str(output_folder))
                window._start_processing()
                QTimer.singleShot(0, request_shutdown_when_started)

            class AppFactory:
                @staticmethod
                def instance():
                    return QApplication.instance()

                def __new__(cls, argv):
                    app = QApplication(argv)
                    QTimer.singleShot(0, start_batch)
                    QTimer.singleShot(10000, lambda: app.exit(2))
                    return app

            if __name__ == "__main__":
                input_folder, output_folder = map(Path, sys.argv[1:3])
                gui.load_saved_folders = lambda: {}
                gui.run_batch = fake_batch
                qt = gui._require_pyside6()
                qt.update(QApplication=AppFactory)
                gui._require_pyside6 = lambda: qt

                exit_code = gui.launch_gui()
                app = QApplication.instance()
                window = app._sssep_launcher_window
                assert exit_code == 0
                assert window.worker is not None and not window.worker.isRunning()
                assert not window.task_thread.isRunning()
                print("ACTIVE_BATCH_SHUTDOWN_OK")
            '''
        ),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root))
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(tmp_path / "input"),
            str(tmp_path / "output"),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ACTIVE_BATCH_SHUTDOWN_OK" in completed.stdout


def test_invalid_configured_plot_channel_fails_clearly(tmp_path):
    """An invalid default must not silently select the first montage channel."""
    script = tmp_path / "invalid_plot_channel_probe.py"
    script.write_text(
        textwrap.dedent(
            r'''
            import sssep_batch.gui as gui

            gui.PLOT_CHANNEL = "NotAChannel"
            gui.load_saved_folders = lambda: {}

            try:
                gui.launch_gui()
            except ValueError as exc:
                message = str(exc)
                assert "Configured PLOT_CHANNEL 'NotAChannel'" in message
                assert "not a BioSemi64 electrode" in message
            else:
                raise AssertionError("Invalid PLOT_CHANNEL unexpectedly opened the launcher")

            print("INVALID_PLOT_CHANNEL_REJECTED")
            '''
        ),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root))
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "INVALID_PLOT_CHANNEL_REJECTED" in completed.stdout
