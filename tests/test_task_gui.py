"""Exercise participant-task GUI settings and main-thread runner lifecycle."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_task_tab_runs_each_task_on_qt_main_thread(tmp_path):
    """Two task launches should create main-thread runners and restore controls."""
    script = tmp_path / "task_gui_probe.py"
    script.write_text(
        textwrap.dedent(
            r'''
            from pathlib import Path
            from types import SimpleNamespace
            import sys
            import threading
            import traceback

            from PySide6.QtCore import QObject, QTimer, Signal
            from PySide6.QtWidgets import QApplication, QLabel
            import sssep_batch.gui as gui

            class FakeTaskRunner(QObject):
                progress_changed = Signal(int, int)
                task_finished = Signal(object)
                task_failed = Signal(object)
                task_done = Signal()

                def __init__(self, *, parent=None):
                    super().__init__(parent)
                    self.settings = None
                    self.stop_requested = False
                    self.finished = False
                    runners.append(self)

                def start(self, settings):
                    assert threading.current_thread() is threading.main_thread()
                    assert self.parent() is window_ref[0]
                    self.settings = settings
                    settings_seen.append(settings)
                    start_thread_ids.append(threading.get_ident())
                    self.progress_changed.emit(0, settings.total_epochs)

                def complete(self):
                    assert threading.current_thread() is threading.main_thread()
                    assert not self.finished
                    self.finished = True
                    completion_thread_ids.append(threading.get_ident())
                    self.progress_changed.emit(
                        self.settings.total_epochs,
                        self.settings.total_epochs,
                    )
                    self.task_finished.emit(
                        SimpleNamespace(
                            aborted=False,
                            abort_reason=None,
                            completed_epochs=self.settings.total_epochs,
                            log_path=self.settings.output_folder
                            / f"task_{len(settings_seen)}.csv",
                        )
                    )
                    self.task_done.emit()

                def request_stop(self):
                    self.stop_requested = True

            def checked(callback):
                def wrapped(*args):
                    try:
                        callback(*args)
                    except BaseException:
                        errors.append(traceback.format_exc())
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

            def prompt_controls(window):
                return (
                    window.break_duration_spin,
                    window.left_hand_prompt_edit,
                    window.right_hand_prompt_edit,
                    window.right_ankle_prompt_edit,
                    window.break_prompt_edit,
                )

            @checked
            def start_probe():
                window = next(w for w in QApplication.topLevelWidgets()
                              if w.windowTitle() == "SSSEP Task and Analysis")
                window_ref.append(window)
                assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
                    "Run Participant Task", "Analyze Recordings", "Plot Saved FFT"
                ]
                assert "TENS Unit Stimulation Frequency (Hz)" in {
                    label.text() for label in window.findChildren(QLabel)
                }
                assert window.plot_channel_combo.count() == 64
                assert window.plot_channel_combo.currentText() == gui.PLOT_CHANNEL
                assert not hasattr(window, "serial_port_edit")
                assert window.total_epochs_spin.singleStep() == 2
                assert window.total_epochs_spin.value() % 2 == 0
                assert window.break_duration_spin.value() == 10.0
                assert window.left_hand_prompt_edit.text() == "Think of your left hand"
                assert window.right_hand_prompt_edit.text() == "Think of your right hand"
                assert window.right_ankle_prompt_edit.text() == "Think of your right ankle"
                assert window.break_prompt_edit.text() == "Now let's take a short break."
                assert "fresh random order" in window.total_epochs_spin.toolTip()
                for widget in (*prompt_controls(window), window.start_task_button):
                    assert widget.isVisible()
                    assert window.task_tab.rect().contains(widget.geometry())
                assert not window.test_mode_checkbox.isChecked()
                assert window.task_runner is None
                assert_trigger_codes_locked(window)

                window.condition_combo.setCurrentIndex(1)
                window.epoch_duration_spin.setValue(2.5)
                window.break_duration_spin.setValue(4.5)
                window.total_epochs_spin.setValue(4)
                window.task_log_edit.setText(str(log_folder))
                window.stimulation_frequency_edit.setText("12.5")
                window.left_hand_prompt_edit.setText("  Focus on your left hand.  ")
                window.right_hand_prompt_edit.setText("Focus on your right hand.")
                window.right_ankle_prompt_edit.setText("Focus on your right ankle.")
                window.break_prompt_edit.setText(" ")
                window._start_task()
                assert not runners
                assert not window.task_running
                assert messages[-1][0] == "Task Settings Need Attention"
                messages.clear()
                window.break_prompt_edit.setText("Rest for a moment.")
                analysis_protocol = window._analysis_protocol()
                assert analysis_protocol.active_event_codes == (21, 22)
                assert analysis_protocol.event_duration_sec == 2.5
                assert analysis_protocol.expected_repetitions_per_trigger == 2
                assert [
                    trigger.target_hz for trigger in analysis_protocol.active_triggers
                ] == [12.5, 12.5]
                window._start_task()
                QTimer.singleShot(0, check_first_run)

            @checked
            def check_first_run():
                window = window_ref[0]
                assert window.task_running
                assert window.task_runner is runners[0]
                assert start_thread_ids == [main_thread_id]
                assert not window.start_task_button.isEnabled()
                assert not window.tabs.isTabEnabled(1)
                assert not window.tabs.isTabEnabled(2)
                assert all(not widget.isEnabled() for widget in prompt_controls(window))
                assert_trigger_codes_locked(window)
                assert not window.close(), "Active participant task accepted close"
                settings = settings_seen[0]
                assert settings.condition is gui.TaskCondition.RIGHT_HAND_AND_ANKLE
                assert settings.epoch_duration_sec == 2.5
                assert settings.break_duration_sec == 4.5
                assert settings.left_hand_prompt == "Focus on your left hand."
                assert settings.right_hand_prompt == "Focus on your right hand."
                assert settings.right_ankle_prompt == "Focus on your right ankle."
                assert settings.break_prompt == "Rest for a moment."
                assert settings.total_epochs == 4
                assert settings.test_mode is False
                assert settings.serial_port == "COM3"
                assert settings.output_folder == log_folder
                assert settings.trigger_codes == gui.CueTriggerCodes(11, 12, 21, 22)
                runners[0].complete()
                QTimer.singleShot(0, start_second_run)

            @checked
            def start_second_run():
                window = window_ref[0]
                assert not window.task_running
                assert window.task_runner is None
                assert window.start_task_button.isEnabled()
                assert window.tabs.isTabEnabled(1)
                assert window.tabs.isTabEnabled(2)
                assert all(widget.isEnabled() for widget in prompt_controls(window))
                assert_trigger_codes_locked(window)
                assert "Task complete: 4 epoch(s)." in window.task_status_label.text()
                window._start_task()
                QTimer.singleShot(0, check_second_run)

            @checked
            def check_second_run():
                window = window_ref[0]
                assert len(runners) == 2
                assert runners[1] is not runners[0]
                assert window.task_runner is runners[1]
                assert start_thread_ids == [main_thread_id, main_thread_id]
                runners[1].complete()
                QTimer.singleShot(0, test_mode_confirmation)

            @checked
            def test_mode_confirmation():
                window = window_ref[0]
                assert window.task_runner is None
                window.test_mode_checkbox.setChecked(True)
                previous_status = window.task_status_label.text()

                question_answers.append(MessageBox.No)
                window._start_task()
                assert window.task_runner is None
                assert not window.task_running
                assert window.task_status_label.text() == previous_status
                assert window.test_mode_checkbox.isEnabled()

                question_answers.append(MessageBox.Yes)
                window._start_task()
                QTimer.singleShot(0, check_test_mode_run)

            @checked
            def check_test_mode_run():
                window = window_ref[0]
                assert len(runners) == 3
                assert window.task_runner is runners[2]
                assert settings_seen[2].test_mode is True
                assert not window.test_mode_checkbox.isEnabled()
                assert questions == [
                    (
                        "Confirm Test Mode",
                        "Are you sure you want to run the experiment in test mode?",
                    ),
                    (
                        "Confirm Test Mode",
                        "Are you sure you want to run the experiment in test mode?",
                    ),
                ]
                runners[2].complete()
                QTimer.singleShot(0, finish_probe)

            @checked
            def finish_probe():
                window = window_ref[0]
                assert len(settings_seen) == 3
                assert completion_thread_ids == [main_thread_id] * 3
                assert window.task_runner is None
                assert not any(runner.stop_requested for runner in runners)
                assert not messages
                assert window.close(), "Completed task runner prevented close"
                observed.add("closed")

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
                Yes = 1
                No = 2

                @staticmethod
                def warning(parent, title, message):
                    messages.append((title, message))
                critical = warning

                @staticmethod
                def question(parent, title, message, buttons, default):
                    questions.append((title, message))
                    assert buttons == MessageBox.Yes | MessageBox.No
                    assert default == MessageBox.No
                    return question_answers.pop(0)

            if __name__ == "__main__":
                log_folder = Path(sys.argv[1])
                main_thread_id = threading.get_ident()
                runners, settings_seen = [], []
                start_thread_ids, completion_thread_ids = [], []
                messages, questions, question_answers = [], [], []
                errors, window_ref = [], []
                observed = set()
                gui.QtTaskRunner = FakeTaskRunner
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
