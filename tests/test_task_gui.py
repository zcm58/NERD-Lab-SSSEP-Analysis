"""Exercise participant-task GUI settings and persistent worker lifecycle."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_task_tab_reuses_one_background_thread_and_builds_settings(tmp_path):
    """Two task launches should reuse a worker and keep Qt widgets on the UI thread."""
    script = tmp_path / "task_gui_probe.py"
    script.write_text(
        textwrap.dedent(
            r'''
            from pathlib import Path
            from types import SimpleNamespace
            import sys
            import threading
            import traceback

            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            import sssep_batch.gui as gui

            def fake_task(settings, progress_callback=None, abort_requested=None):
                assert abort_requested is not None
                assert not abort_requested()
                run_index = len(settings_seen)
                settings_seen.append(settings)
                worker_thread_ids.append(threading.get_ident())
                progress_callback(0, settings.total_epochs)
                started[run_index].set()
                assert release[run_index].wait(10), "GUI did not release task worker"
                progress_callback(settings.total_epochs, settings.total_epochs)
                return SimpleNamespace(
                    aborted=False,
                    abort_reason=None,
                    completed_epochs=settings.total_epochs,
                    log_path=settings.output_folder / f"task_{run_index + 1}.csv",
                )

            def checked(callback):
                def wrapped(*args):
                    try:
                        callback(*args)
                    except BaseException:
                        errors.append(traceback.format_exc())
                        for event in release:
                            event.set()
                        if window_ref:
                            window_ref[0].task_running = False
                            window_ref[0].task_thread.quit()
                            window_ref[0].task_thread.wait(2000)
                        QApplication.instance().exit(1)
                return wrapped

            def assert_trigger_codes_locked(window):
                trigger_spins = (
                    window.both_hands_left_code_spin,
                    window.both_hands_right_code_spin,
                    window.hand_ankle_hand_code_spin,
                    window.hand_ankle_ankle_code_spin,
                )
                assert [spin.value() for spin in trigger_spins] == [11, 12, 21, 22]
                assert all(spin.minimum() == spin.maximum() for spin in trigger_spins)
                assert all(not spin.isEnabled() for spin in trigger_spins)

            @checked
            def start_probe():
                window = next(w for w in QApplication.topLevelWidgets()
                              if w.windowTitle() == "SSSEP Task and Analysis")
                window_ref.append(window)
                assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
                    "Run Participant Task", "Analyze Recordings"
                ]
                assert window.plot_channel_combo.count() == 64
                assert window.plot_channel_combo.currentText() == gui.PLOT_CHANNEL
                assert not hasattr(window, "serial_port_edit")
                assert window.total_epochs_spin.singleStep() == 2
                assert window.total_epochs_spin.value() % 2 == 0
                assert_trigger_codes_locked(window)

                window.condition_combo.setCurrentIndex(1)
                window.epoch_duration_spin.setValue(2.5)
                window.total_epochs_spin.setValue(4)
                window.task_log_edit.setText(str(log_folder))
                window.stimulation_frequency_edit.setText("12.5")
                analysis_protocol = window._analysis_protocol()
                assert analysis_protocol.active_event_codes == (21, 22)
                assert analysis_protocol.event_duration_sec == 2.5
                assert analysis_protocol.expected_repetitions_per_trigger == 2
                assert [
                    trigger.target_hz for trigger in analysis_protocol.active_triggers
                ] == [12.5, 12.5]
                original_worker = window.task_worker
                window._start_task()

                @checked
                def wait_for_first_start():
                    if not started[0].is_set():
                        QTimer.singleShot(10, wait_for_first_start)
                        return
                    assert window.task_running
                    assert window.task_worker is original_worker
                    assert window.task_thread.isRunning()
                    assert not window.start_task_button.isEnabled()
                    assert not window.tabs.isTabEnabled(1)
                    assert_trigger_codes_locked(window)
                    assert not window.close(), "Active participant task accepted close"
                    settings = settings_seen[0]
                    assert settings.condition is gui.TaskCondition.RIGHT_HAND_AND_ANKLE
                    assert settings.epoch_duration_sec == 2.5
                    assert settings.total_epochs == 4
                    assert settings.serial_port == "COM3"
                    assert settings.output_folder == log_folder
                    assert settings.trigger_codes == gui.CueTriggerCodes(11, 12, 21, 22)
                    release[0].set()
                    QTimer.singleShot(10, wait_for_first_finish)

                @checked
                def wait_for_first_finish():
                    if window.task_running:
                        QTimer.singleShot(10, wait_for_first_finish)
                        return
                    assert window.start_task_button.isEnabled()
                    assert window.tabs.isTabEnabled(1)
                    assert_trigger_codes_locked(window)
                    assert "Task complete: 4 epoch(s)." in window.task_status_label.text()
                    assert window.task_worker is original_worker
                    window._start_task()
                    QTimer.singleShot(10, wait_for_second_start)

                @checked
                def wait_for_second_start():
                    if not started[1].is_set():
                        QTimer.singleShot(10, wait_for_second_start)
                        return
                    assert window.task_worker is original_worker
                    release[1].set()
                    QTimer.singleShot(10, wait_for_second_finish)

                @checked
                def wait_for_second_finish():
                    if window.task_running:
                        QTimer.singleShot(10, wait_for_second_finish)
                        return
                    assert len(settings_seen) == 2
                    assert worker_thread_ids[0] == worker_thread_ids[1]
                    assert not messages
                    assert window.close(), "Idle presentation worker prevented close"
                    assert not window.task_thread.isRunning()
                    observed.add("closed")

                QTimer.singleShot(0, wait_for_first_start)

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

            if __name__ == "__main__":
                log_folder = Path(sys.argv[1])
                started = [threading.Event(), threading.Event()]
                release = [threading.Event(), threading.Event()]
                settings_seen, worker_thread_ids = [], []
                messages, errors, window_ref = [], [], []
                observed = set()
                gui.run_participant_task = fake_task
                gui.load_saved_folders = lambda: {}
                qt = gui._require_pyside6()
                qt.update(QApplication=AppFactory, QMessageBox=MessageBox)
                gui._require_pyside6 = lambda: qt
                exit_code = gui.launch_gui()
                assert exit_code == 0, (exit_code, errors)
                assert observed == {"closed"}, (observed, errors)
                print("TASK_GUI_OK")
            '''
        ),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root))
    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "task_logs")],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "TASK_GUI_OK" in completed.stdout
