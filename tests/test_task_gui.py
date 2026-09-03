"""Exercise participant-task GUI settings and main-thread runner lifecycle."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_task_view_settings_persist_and_tasks_run_on_qt_main_thread(tmp_path):
    """Two task launches should create main-thread runners and restore controls."""
    script = tmp_path / "task_gui_probe.py"
    script.write_text(
        textwrap.dedent(
            r'''
            from pathlib import Path
            from dataclasses import replace
            from types import SimpleNamespace
            import os
            import sys
            import threading
            import traceback

            from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Signal
            from PySide6.QtGui import QFont, QFontDatabase
            from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QScrollArea, QSpinBox
            import sssep_batch.task_settings_gui as settings_gui
            import sssep_batch.roi_selection_gui as roi_gui
            from sssep_batch.roi_settings import load_custom_rois
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

            def assert_trigger_codes_locked(dialog):
                trigger_spins = dialog.trigger_spins
                assert [spin.value() for spin in trigger_spins] == [11, 12, 21, 22]
                assert all(spin.minimum() == spin.maximum() for spin in trigger_spins)
                assert all(not spin.isEnabled() for spin in trigger_spins)

            def edit_nested_roi(dialog, name, labels, *, save_custom=False, use=True, add=False):
                @checked
                def edit_selection():
                    selector = QApplication.activeModalWidget()
                    assert isinstance(selector, roi_gui.RoiSelectionDialog)
                    assert selector.parent() is dialog
                    assert len(selector.map_widget.electrode_buttons) == 64
                    assert all(button.isEnabled() for button in selector.map_widget.electrode_buttons.values())
                    selector.clear_button.click()
                    for label in labels:
                        selector.map_widget.electrode_buttons[label].click()
                    selector.name_edit.setText(name)
                    if save_custom:
                        selector.save_button.click()
                    if use:
                        selector.use_button.click()
                    else:
                        selector.reject()
                QTimer.singleShot(0, edit_selection)
                (dialog.add_roi_button if add else dialog.edit_roi_button).click()

            @checked
            def cancel_settings():
                dialog = QApplication.activeModalWidget()
                assert dialog.windowTitle() == "SSSEP Settings"
                assert not hasattr(dialog, "serial_port_edit")
                assert not hasattr(dialog, "condition_combo")
                assert dialog.epochs_per_condition_spin.value() == 10
                assert dialog.epoch_duration_spin.value() == 15.0
                assert dialog.break_duration_spin.value() == 10.0
                assert dialog.stimulation_frequency_edit.text() == "26"
                assert not dialog.test_mode_checkbox.isChecked()
                assert dialog.show_timer_checkbox.text() == "Show countdown timer"
                assert dialog.show_timer_checkbox.isChecked()
                assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
                    "Session", "Participant text", "Analysis", "Regions of Interest"
                ]
                assert_trigger_codes_locked(dialog)
                assert window_ref[0].saved_plots_page.dataset is None
                edit_nested_roi(dialog, "Reusable central", ("C3", "C4"), save_custom=True)
                assert dialog.plot_rois == {"Reusable central": ("C3", "C4")}
                assert "C3, C4" in dialog.roi_list.item(0).text()
                assert window_ref[0].plot_rois == {gui.PLOT_CHANNEL: (gui.PLOT_CHANNEL,)}
                assert window_ref[0].saved_plots_page.plot_rois == window_ref[0].plot_rois
                assert load_custom_rois(roi_gui.ROI_SETTINGS_PATH) == {
                    "Reusable central": ("C3", "C4"),
                }
                dialog.epoch_duration_spin.setValue(30.0)
                dialog.epochs_per_condition_spin.setValue(20)
                dialog.left_hand_prompt_edit.setText("Unsaved prompt")
                dialog.show_timer_checkbox.setChecked(False)
                dialog.reject()

            @checked
            def save_settings():
                dialog = QApplication.activeModalWidget()
                assert dialog.show_timer_checkbox.isChecked(), "Cancel changed the timer preference"
                assert "TENS Unit Stimulation Frequency (Hz)" in {
                    label.text() for label in dialog.findChildren(QLabel)
                }
                assert dialog.plot_channel_combo.count() == 64
                assert dialog.plot_channel_combo.currentText() == gui.PLOT_CHANNEL
                assert dialog.plot_rois == {gui.PLOT_CHANNEL: (gui.PLOT_CHANNEL,)}
                edit_nested_roi(dialog, "Discard nested", ("Fp1",), use=False)
                assert dialog.plot_rois == {gui.PLOT_CHANNEL: (gui.PLOT_CHANNEL,)}
                edit_nested_roi(dialog, "Central hands", ("C3", "Cz", "C4"))
                expected = tuple(label for label in gui.BIOSEMI64_CHANNELS if label in {"C3", "Cz", "C4"})
                assert dialog.plot_rois == {"Central hands": expected}
                edit_nested_roi(dialog, "Left electrode", ("C3",), add=True)
                assert list(dialog.plot_rois) == ["Central hands", "Left electrode"]
                assert dialog.plot_rois["Left electrode"] == ("C3",)
                edit_nested_roi(dialog, "Right electrode", ("C4",), add=True)
                assert dialog.roi_list.count() == 3
                edit_nested_roi(dialog, "central HANDS", ("C4",), add=True)
                assert messages[-1][0] == "ROI Name Already Used"
                assert dialog.roi_list.count() == 3
                assert dialog.plot_rois["Central hands"] == expected
                messages.clear()
                edit_nested_roi(dialog, "LEFT ELECTRODE", ("C4",))
                assert messages[-1][0] == "ROI Name Already Used"
                assert "Right electrode" in dialog.plot_rois
                messages.clear()
                dialog.remove_roi_button.click()
                assert list(dialog.plot_rois) == ["Central hands", "Left electrode"]
                edit_nested_roi(dialog, "Discard new ROI", ("Fp2",), add=True, use=False)
                assert dialog.roi_list.count() == 2
                assert dialog.epochs_per_condition_spin.singleStep() == 2
                assert dialog.left_hand_prompt_edit.text() == "Think of your left hand"
                assert dialog.right_hand_prompt_edit.text() == "Think of your right hand"
                assert dialog.right_ankle_prompt_edit.text() == "Think of your right ankle"
                assert dialog.break_prompt_edit.text() == "Now let's take a short break."
                for index in range(dialog.tabs.count()):
                    dialog.tabs.setCurrentIndex(index)
                    QApplication.processEvents()
                    scroll = dialog.tabs.currentWidget().findChild(QScrollArea, "pageScrollArea")
                    assert scroll.widget().width() == scroll.viewport().width()
                dialog.epoch_duration_spin.setValue(15.0)
                dialog.break_duration_spin.setValue(4.5)
                dialog.show_timer_checkbox.setChecked(False)
                dialog.epochs_per_condition_spin.setValue(4)
                dialog.task_log_edit.setText(str(log_folder))
                dialog.stimulation_frequency_edit.setText("12.5")
                dialog.plot_channel_combo.setCurrentText("C4")
                dialog.left_hand_prompt_edit.setText("  Focus on your left hand.  ")
                dialog.right_hand_prompt_edit.setText("Focus on your right hand.")
                dialog.right_ankle_prompt_edit.setText("Focus on your right ankle.")
                dialog.break_prompt_edit.setText(" ")
                dialog._save()
                assert dialog.isVisible()
                assert messages[-1][0] == "Settings Need Attention"
                assert window_ref[0].session_settings.epochs_per_condition == 10
                assert window_ref[0].plot_rois == {gui.PLOT_CHANNEL: (gui.PLOT_CHANNEL,)}
                messages.clear()
                dialog.break_prompt_edit.setText("Rest for a moment.")
                dialog.stimulation_frequency_edit.setText("nan")
                dialog._save()
                assert dialog.isVisible()
                assert "finite number" in messages[-1][1]
                messages.clear()
                dialog.stimulation_frequency_edit.setText("12.5")
                assert_trigger_codes_locked(dialog)
                save_to_disk = gui.save_launcher_settings
                def fail_save(*args, **kwargs):
                    raise OSError("Settings folder is read-only")
                gui.save_launcher_settings = fail_save
                dialog._save()
                assert dialog.isVisible()
                assert window_ref[0].session_settings.epochs_per_condition == 10
                assert not gui.SETTINGS_PATH.exists()
                assert window_ref[0].saved_plots_page.plot_rois == {gui.PLOT_CHANNEL: (gui.PLOT_CHANNEL,)}
                assert messages[-1][0] == "Could Not Save Settings"
                messages.clear()
                gui.save_launcher_settings = save_to_disk
                dialog._save()

            @checked
            def start_probe():
                window = next(w for w in QApplication.topLevelWidgets()
                              if w.windowTitle() == "NERD Lab SSSEP Task")
                window_ref.append(window)
                assert [action.text() for action in window.view_actions] == [
                    "SSSEP Task", "Process Data", "Generate FFT Plots"
                ]
                assert window.pages.count() == 3
                assert not hasattr(window, "tabs")
                assert not window.task_page.findChildren(QLineEdit)
                assert not window.task_page.findChildren(QSpinBox)
                assert window.start_task_button.text() == "Start SSSEP Task"
                assert window.session_settings.total_epochs == 20
                assert not hasattr(window, "condition_combo")
                assert window.settings_action.isEnabled()
                menu_bar = window.layout().menuBar()
                assert [action.text() for action in menu_bar.actions()] == ["File", "View"]
                assert window.settings_action in menu_bar.actions()[0].menu().actions()
                assert {label.text() for label in window.findChildren(QLabel) if label.isVisible()} == {
                    "Change settings in File > Settings.", "NERD Lab SSSEP Task"
                }
                for index, action in enumerate(window.view_actions):
                    action.trigger()
                    assert window.pages.currentIndex() == index
                    assert action.isChecked()
                window.view_actions[0].trigger()
                window.resize(820, 680)
                QApplication.processEvents()
                button = window.start_task_button
                position = button.mapTo(window.task_page, QPoint(0, 0))
                assert window.task_page.rect().contains(QRect(position, button.size()))
                original = window.session_settings
                window.session_settings = replace(original, output_folder=None)
                window._start_task()
                assert not runners
                assert "File > Settings" in messages[-1][1]
                messages.clear()
                window.session_settings = original
                QTimer.singleShot(0, cancel_settings)
                window.settings_action.trigger()
                assert window.session_settings is original
                assert not gui.SETTINGS_PATH.exists()
                assert window.plot_rois == {gui.PLOT_CHANNEL: (gui.PLOT_CHANNEL,)}
                assert load_custom_rois(roi_gui.ROI_SETTINGS_PATH) == {
                    "Reusable central": ("C3", "C4"),
                }, "Explicit library Save must survive outer Cancel"
                QTimer.singleShot(0, save_settings)
                window.settings_action.trigger()
                assert window.session_settings is not original
                assert window.session_settings.epochs_per_condition == 4
                assert window.session_settings.show_timer is False
                assert window.plot_channel == "C4"
                assert list(window.plot_rois) == ["Central hands", "Left electrode"]
                assert set(window.plot_rois["Central hands"]) == {"C3", "Cz", "C4"}
                assert window.plot_rois["Left electrode"] == ("C3",)
                assert window.saved_plots_page.plot_rois == window.plot_rois
                assert window.saved_plots_page.plot_rois is not window.plot_rois
                assert window.saved_plots_page.stimulation_hz == 12.5
                assert gui.SETTINGS_PATH.exists()
                assert window.session_settings.total_epochs == 8
                assert "C4" in window.analysis_settings_label.text()
                analysis_protocol = window._analysis_protocol()
                assert analysis_protocol.active_event_codes == (11, 12, 21, 22)
                assert analysis_protocol.event_duration_sec == 15.0
                assert analysis_protocol.expected_repetitions_per_trigger == 2
                assert [
                    trigger.target_hz for trigger in analysis_protocol.active_triggers
                ] == [12.5] * 4
                window._start_task()
                QTimer.singleShot(0, check_first_run)

            @checked
            def check_first_run():
                window = window_ref[0]
                assert window.task_running
                assert window.task_runner is runners[0]
                assert start_thread_ids == [main_thread_id]
                assert not window.start_task_button.isEnabled()
                assert not window.view_actions[1].isEnabled()
                assert not window.view_actions[2].isEnabled()
                assert not window.settings_action.isEnabled()
                assert not any(action.isEnabled() for action in window.view_actions)
                window._show_view(1)
                assert window.pages.currentIndex() == 0
                window._open_settings()
                assert QApplication.activeModalWidget() is None
                assert not window.close(), "Active participant task accepted close"
                settings = settings_seen[0]
                assert settings.epoch_duration_sec == 15.0
                assert settings.break_duration_sec == 4.5
                assert settings.left_hand_prompt == "Focus on your left hand."
                assert settings.right_hand_prompt == "Focus on your right hand."
                assert settings.right_ankle_prompt == "Focus on your right ankle."
                assert settings.break_prompt == "Rest for a moment."
                assert settings.epochs_per_condition == 4
                assert settings.total_epochs == 8
                assert settings.test_mode is False
                assert settings.show_timer is False
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
                assert window.view_actions[1].isEnabled()
                assert window.view_actions[2].isEnabled()
                assert window.settings_action.isEnabled()
                assert "Task complete: 8 epoch(s)." in window.task_status_label.text()
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
                @checked
                def enable_test_mode():
                    dialog = QApplication.activeModalWidget()
                    dialog.test_mode_checkbox.setChecked(True)
                    dialog._save()
                QTimer.singleShot(0, enable_test_mode)
                window.settings_action.trigger()
                assert window.session_settings.test_mode
                previous_status = window.task_status_label.text()

                question_answers.append(MessageBox.No)
                window._start_task()
                assert window.task_runner is None
                assert not window.task_running
                assert window.task_status_label.text() == previous_status
                assert window.settings_action.isEnabled()

                question_answers.append(MessageBox.Yes)
                window._start_task()
                QTimer.singleShot(0, check_test_mode_run)

            @checked
            def check_test_mode_run():
                window = window_ref[0]
                assert len(runners) == 3
                assert window.task_runner is runners[2]
                assert settings_seen[2].test_mode is True
                assert not window.settings_action.isEnabled()
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
                    if sys.platform == "win32":
                        # Offscreen Qt does not discover Windows system fonts.
                        fonts = Path(os.environ["WINDIR"]) / "Fonts"
                        for name in ("segoeui.ttf", "segoeuib.ttf"):
                            assert QFontDatabase.addApplicationFont(str(fonts / name)) >= 0
                        app.setFont(QFont("Segoe UI", 10))
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
                settings_gui.QMessageBox = MessageBox
                gui.QtTaskRunner = FakeTaskRunner
                gui.SETTINGS_PATH = log_folder.parent / "gui-settings.json"
                roi_gui.ROI_SETTINGS_PATH = log_folder.parent / "rois.json"
                qt = gui._require_pyside6()
                qt.update(QApplication=AppFactory, QMessageBox=MessageBox)
                gui._require_pyside6 = lambda: qt
                exit_code = gui.launch_gui()
                assert exit_code == 0, (exit_code, errors)
                assert observed == {"closed"}, (observed, errors)
                before_reopen = gui.SETTINGS_PATH.read_bytes()
                assert gui.launch_gui() == 0
                reopened = QApplication.instance()._sssep_launcher_window
                assert reopened.session_settings == settings_seen[-1]
                assert reopened.session_settings.show_timer is False
                assert reopened.plot_channel == "C4"
                assert reopened.stimulation_hz == 12.5
                assert list(reopened.plot_rois) == ["Central hands", "Left electrode"]
                assert set(reopened.plot_rois["Central hands"]) == {"C3", "Cz", "C4"}
                assert reopened.plot_rois["Left electrode"] == ("C3",)
                assert reopened.saved_plots_page.plot_rois == reopened.plot_rois
                assert reopened.saved_plots_page.stimulation_hz == 12.5
                assert reopened.pages.currentIndex() == 0
                def cancel_reopened():
                    dialog = QApplication.activeModalWidget()
                    assert not dialog.show_timer_checkbox.isChecked()
                    dialog.show_timer_checkbox.setChecked(True)
                    dialog.epochs_per_condition_spin.setValue(40)
                    dialog.break_prompt_edit.setText("Discard this")
                    while dialog.roi_list.count():
                        dialog.remove_roi_button.click()
                    assert dialog.plot_rois == {}
                    assert not dialog.edit_roi_button.isEnabled()
                    assert not dialog.remove_roi_button.isEnabled()
                    assert len(reopened.plot_rois) == 2
                    dialog.reject()
                QTimer.singleShot(0, cancel_reopened)
                reopened.settings_action.trigger()
                assert gui.SETTINGS_PATH.read_bytes() == before_reopen
                assert reopened.session_settings == settings_seen[-1]
                question_answers.append(MessageBox.No)
                reopened._start_task()
                assert reopened.task_runner is None
                assert len(runners) == 3
                selected = reopened.plot_rois
                reopened.plot_rois = {"Old extra": ("Previously selected",), "Another": ("Second extra",)}
                reopened.saved_plots_page.dataset = SimpleNamespace(channel_names=("Loaded extra",))
                @checked
                def inspect_available_channels():
                    dialog = QApplication.activeModalWidget()
                    assert set(gui.BIOSEMI64_CHANNELS).issubset(dialog._roi_available_channels)
                    assert "Loaded extra" in dialog._roi_available_channels
                    assert "Previously selected" in dialog._roi_available_channels
                    assert "Second extra" in dialog._roi_available_channels
                    assert dialog.plot_channel_combo.count() == 64
                    @checked
                    def inspect_nested_extras():
                        selector = QApplication.activeModalWidget()
                        assert selector._selected == {"Previously selected"}
                        assert {
                            selector.other_list.item(index).text()
                            for index in range(selector.other_list.count())
                        } == {"Loaded extra", "Previously selected", "Second extra"}
                        selector.reject()
                    QTimer.singleShot(0, inspect_nested_extras)
                    dialog.edit_roi_button.click()
                    dialog.reject()
                QTimer.singleShot(0, inspect_available_channels)
                reopened.settings_action.trigger()
                assert gui.SETTINGS_PATH.read_bytes() == before_reopen
                reopened.plot_rois = selected
                reopened.saved_plots_page.dataset = None
                assert reopened.close()

                gui.SETTINGS_PATH.write_text('{broken', encoding="utf-8")
                assert gui.launch_gui() == 0
                invalid = QApplication.instance()._sssep_launcher_window
                QApplication.processEvents()
                assert invalid._settings_need_review
                assert invalid.saved_plots_page.settings_need_review
                invalid.saved_plots_page._warn = lambda title, message: messages.append((title, message))
                invalid.saved_plots_page._start_plot("roi")
                assert messages[-1][0] == "Settings Need Attention"
                assert "File > Settings" in messages[-1][1]
                assert invalid.saved_plots_page.plot_worker is None
                assert gui.SETTINGS_PATH.read_text(encoding="utf-8") == '{broken'
                @checked
                def save_reviewed_settings():
                    dialog = QApplication.activeModalWidget()
                    dialog.task_log_edit.setText(str(log_folder))
                    dialog.save_folders_checkbox.setChecked(False)
                    dialog._save()
                QTimer.singleShot(0, save_reviewed_settings)
                invalid.settings_action.trigger()
                assert not invalid._settings_need_review
                assert not invalid.saved_plots_page.settings_need_review
                assert invalid.close()
                assert not errors, errors
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
