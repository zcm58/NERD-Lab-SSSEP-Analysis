"""Exercise saved-FFT loading and post-processing GUI worker lifecycle."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pandas as pd


def _write_gui_fft(run_folder, target_hz=10.0):
    run_folder.mkdir(parents=True, exist_ok=True)
    count = 6
    pd.DataFrame(
        {
            "participant_id": ["P01"] * count,
            "file_name": ["P01.bdf"] * count,
            "event_type": ["cue"] * count,
            "trigger_code": [11] * count,
            "trigger_label": ["BothHands Left Hand"] * count,
            "target_hz": [target_hz] * count,
            "usable_epochs": [4] * count,
            "processing_method": ["fpvs_amplitude_v1"] * count,
            "fft_schema_version": [1] * count,
            "fpvs_reference_commit": [
                "185d803f0056daebee04e5f28cc6b554c47336ce"
            ] * count,
            "montage_name": ["standard_1005"] * count,
            "sampling_rate_hz": [100.0] * count,
            "analysis_window_sec": [0.1] * count,
            "plot_fmin_hz": [3.0] * count,
            "plot_fmax_hz": [50.0] * count,
            "analysis_channels": ["C3;C4"] * count,
            "frequency_hz": [index * 10.0 for index in range(count)],
            "analysis_mean_amplitude_uv": [index + 1.5 for index in range(count)],
            "C3_amplitude_uv": [index + 1.0 for index in range(count)],
            "C4_amplitude_uv": [index + 2.0 for index in range(count)],
        }
    ).to_csv(run_folder / "participant_fft_amplitudes.csv", index=False)
    return run_folder / "participant_fft_amplitudes.csv"


def test_saved_fft_view_loads_results_and_runs_plot_off_ui_thread(tmp_path):
    """The FFT view loads reusable data and retains its background plot worker."""

    run_folder = tmp_path / "run_test"
    _write_gui_fft(run_folder)

    script = tmp_path / "saved_plot_gui_probe.py"
    script.write_text(
        textwrap.dedent(
            r'''
            from pathlib import Path
            from dataclasses import replace
            import sys
            import threading
            import traceback

            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            import sssep_batch.gui as gui
            import sssep_batch.saved_plots_gui as saved_gui

            def fake_roi_outputs(dataset, **kwargs):
                assert threading.current_thread() is not threading.main_thread()
                assert dataset.participant_ids == ("P01",)
                assert kwargs["event_type"] == "cue"
                assert kwargs["trigger_code"] == 11
                assert kwargs["channels"] == ("C3", "C4")
                assert kwargs["roi_name"] == "Central ROI"
                assert kwargs["participant_id"] is None
                assert kwargs["stimulation_hz"] == 10.0
                started.set()
                assert release.wait(10), "GUI did not release saved plot worker"
                output_folder = run_folder / "saved_fft_plots"
                output_folder.mkdir(parents=True)
                return {
                    "kind": "roi",
                    "output_folder": str(output_folder),
                    "plot_path": str(output_folder / "plot.png"),
                    "participant_count": 1,
                    "used_channels": ["C3", "C4"],
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
                window = QApplication.instance()._sssep_launcher_window
                panel = window.saved_plots_page
                assert window.view_actions[2].text() == "Generate FFT Plots"
                assert Path(panel.results_edit.text()) == run_folder.parent
                window.view_actions[2].trigger()
                assert window.pages.currentWidget() is panel
                assert not panel.create_roi_button.isEnabled()
                assert panel.load_worker is not None
                pending = panel.load_worker
                panel.ensure_results_loaded()
                assert panel.load_worker is pending
                QTimer.singleShot(10, wait_for_load)

            @checked
            def wait_for_load():
                window = QApplication.instance()._sssep_launcher_window
                panel = window.saved_plots_page
                if panel.load_worker is not None:
                    QTimer.singleShot(10, wait_for_load)
                    return
                assert panel.dataset is not None
                assert panel.participant_combo.count() == 1
                assert panel.event_combo.count() == 1
                assert panel.channel_list.count() == 2
                assert panel.frequency_spin.value() == 10.0
                assert panel.create_roi_button.isEnabled()
                assert Path(panel.results_edit.text()) == run_folder
                assert str(run_folder) in panel.status_label.text()
                original_dataset = panel.dataset
                window.view_actions[0].trigger()
                window.view_actions[2].trigger()
                assert panel.dataset is original_dataset
                assert panel.load_worker is None

                panel.results_edit.setText(str(run_folder.parent / "another_run"))
                assert panel.dataset is None
                assert panel.participant_combo.count() == 0
                assert panel.event_combo.count() == 0
                assert panel.channel_list.count() == 0
                assert not panel.create_roi_button.isEnabled()
                assert not panel.view_button.isEnabled()
                assert "Finish entering the path" in panel.status_label.text()

                panel.results_edit.setText(str(run_folder))
                panel.results_edit.editingFinished.emit()
                assert panel.load_worker is not None
                QTimer.singleShot(10, wait_for_reload)

            @checked
            def wait_for_reload():
                window = QApplication.instance()._sssep_launcher_window
                panel = window.saved_plots_page
                if panel.load_worker is not None:
                    QTimer.singleShot(10, wait_for_reload)
                    return
                assert panel.dataset is not None
                for index in range(panel.channel_list.count()):
                    panel.channel_list.item(index).setSelected(True)
                panel.roi_name_edit.setText("Central ROI")
                panel._start_plot("roi")
                QTimer.singleShot(10, wait_for_plot_start)

            @checked
            def wait_for_plot_start():
                window = QApplication.instance()._sssep_launcher_window
                panel = window.saved_plots_page
                if not started.is_set():
                    QTimer.singleShot(10, wait_for_plot_start)
                    return
                assert panel.plot_worker is not None
                assert panel.plot_worker.isRunning()
                assert all(not action.isEnabled() for action in window.view_actions)
                assert not window.settings_action.isEnabled()
                window._show_view(0)
                assert window.pages.currentWidget() is panel
                assert not window.close(), "Active saved plot worker accepted close"
                release.set()
                QTimer.singleShot(10, wait_for_plot_finish)

            @checked
            def wait_for_plot_finish():
                window = QApplication.instance()._sssep_launcher_window
                panel = window.saved_plots_page
                if panel.plot_worker is not None:
                    QTimer.singleShot(10, wait_for_plot_finish)
                    return
                assert all(action.isEnabled() for action in window.view_actions)
                assert window.settings_action.isEnabled()
                assert panel.view_button.isEnabled()
                assert "using C3, C4" in panel.status_label.text()
                panel._view_plot()
                assert opened == [str(run_folder / "saved_fft_plots")]
                assert not messages
                assert window.close(), "Stopped saved plot worker prevented close"
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
                run_folder = Path(sys.argv[1])
                started, release = threading.Event(), threading.Event()
                opened, messages, errors = [], [], []
                observed = set()
                saved_gui.create_saved_roi_outputs = fake_roi_outputs
                saved_gui.QMessageBox = MessageBox
                saved_gui.QDesktopServices = DesktopServices
                gui.load_launcher_settings = lambda defaults, **kwargs: replace(
                    defaults, output_root=str(run_folder.parent)
                )
                gui.save_folder_defaults = lambda *args, **kwargs: None
                qt = gui._require_pyside6()
                qt.update(
                    QApplication=AppFactory,
                    QMessageBox=MessageBox,
                    QDesktopServices=DesktopServices,
                )
                gui._require_pyside6 = lambda: qt
                exit_code = gui.launch_gui()
                assert exit_code == 0, (exit_code, errors)
                assert observed == {"closed"}, (observed, errors)
                print("SAVED_PLOT_GUI_OK")
            '''
        ),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root))
    completed = subprocess.run(
        [sys.executable, str(script), str(run_folder)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "SAVED_PLOT_GUI_OK" in completed.stdout


def test_output_root_selects_newest_immediate_run_with_deterministic_ties(tmp_path):
    from sssep_batch.saved_plots_gui import _saved_results_source

    older = _write_gui_fft(tmp_path / "older")
    newer = _write_gui_fft(tmp_path / "newer")
    tied_last = _write_gui_fft(tmp_path / "z_tied")
    nested = _write_gui_fft(tmp_path / "archive" / "nested")
    for source, stamp in ((older, 1000), (newer, 2000), (tied_last, 2000), (nested, 3000)):
        os.utime(source, (stamp, stamp))

    assert _saved_results_source(str(tmp_path)) == tied_last
    assert _saved_results_source(str(older.parent)) == older
    assert _saved_results_source(str(older)) == older
    direct = _write_gui_fft(tmp_path)
    assert _saved_results_source(str(tmp_path)) == direct


def test_output_root_does_not_fall_back_from_invalid_newest_run(tmp_path):
    from sssep_batch.saved_plots_gui import SavedFftLoadWorker

    older = _write_gui_fft(tmp_path / "older")
    newer = _write_gui_fft(tmp_path / "newer")
    newer.write_text("not,a,valid,fft\n", encoding="utf-8")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    worker = SavedFftLoadWorker(str(tmp_path), None)

    worker.run()

    assert worker.dataset is None
    assert worker.error is not None
    assert str(newer) in str(worker.error)


def test_output_root_without_immediate_fft_data_reports_selected_folder(tmp_path):
    from sssep_batch.saved_plots_gui import SavedFftLoadWorker

    _write_gui_fft(tmp_path / "archive" / "nested")
    worker = SavedFftLoadWorker(str(tmp_path), None)
    worker.run()

    assert worker.dataset is None
    assert "immediate run folders" in str(worker.error)
    assert str(tmp_path) in str(worker.error)


def test_auto_load_failures_retry_and_worker_guards(tmp_path):
    known = _write_gui_fft(tmp_path / "known")
    unmarked = _write_gui_fft(tmp_path / "unmarked", target_hz=None)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "participant_fft_amplitudes.csv").write_text("bad,data\n", encoding="utf-8")
    script = tmp_path / "auto_load_probe.py"
    script.write_text(textwrap.dedent(r'''
        from pathlib import Path
        import sys
        import threading
        import time
        import traceback

        from PySide6.QtCore import QEvent, QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication
        import sssep_batch.gui as gui
        import sssep_batch.saved_plots_gui as saved_gui

        app = QApplication([])
        messages, calls, callback_errors = [], [], []
        started, release = threading.Event(), threading.Event()
        real_load = saved_gui.load_saved_fft_dataset

        def controlled_load(path):
            assert threading.current_thread() is not threading.main_thread()
            calls.append(Path(path))
            started.set()
            assert release.wait(5)
            return real_load(path)

        class MessageBox:
            @staticmethod
            def warning(parent, title, message):
                messages.append((title, message))
                loop = QEventLoop()
                def check_during_modal():
                    try:
                        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                        assert window.saved_plots_page.load_worker is None
                        assert window.saved_plots_page.plot_worker is None
                        window._shutdown_application()
                    except BaseException:
                        callback_errors.append(traceback.format_exc())
                    finally:
                        loop.quit()
                QTimer.singleShot(0, check_during_modal)
                loop.exec()
            critical = warning

        class FolderDialog:
            response = ""
            @staticmethod
            def getExistingDirectory(*args):
                return FolderDialog.response

        def wait_until(predicate):
            deadline = time.monotonic() + 8
            while not predicate() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            assert predicate(), "Timed out waiting for GUI worker"

        known, unmarked, broken = map(Path, sys.argv[1:])
        gui.load_launcher_settings = lambda defaults, **kwargs: defaults
        gui.save_folder_defaults = lambda *args, **kwargs: None
        saved_gui.QMessageBox = MessageBox
        saved_gui.QFileDialog = FolderDialog
        saved_gui.load_saved_fft_dataset = controlled_load
        qt = gui._require_pyside6()
        qt["QMessageBox"] = MessageBox
        gui._require_pyside6 = lambda: qt
        gui.launch_gui()
        window = app._sssep_launcher_window
        panel = window.saved_plots_page
        window.view_actions[2].trigger()
        assert not messages
        assert panel.load_worker is None
        assert "Choose a processed results folder" in panel.status_label.text()
        assert panel.results_load_button.text() == "Reload Results"

        FolderDialog.response = str(known.parent)
        panel._browse_results()
        wait_until(started.is_set)
        worker = panel.load_worker
        panel.ensure_results_loaded()
        panel.results_edit.editingFinished.emit()
        assert panel.load_worker is worker
        assert len(calls) == 1
        assert all(not action.isEnabled() for action in window.view_actions)
        assert not window.settings_action.isEnabled()
        assert not window.close()
        release.set()
        wait_until(lambda: panel.load_worker is None)
        assert panel.dataset is not None
        assert panel.frequency_spin.value() == 10.0
        assert all(action.isEnabled() for action in window.view_actions)

        loaded = panel.dataset
        FolderDialog.response = ""
        panel._browse_results()
        assert panel.dataset is loaded
        assert len(calls) == 1

        missing = known.parent.parent / "missing"
        panel.results_edit.setText(str(missing))
        assert panel.dataset is None
        assert not panel.create_roi_button.isEnabled()
        assert panel.channel_list.count() == 0
        panel.results_edit.editingFinished.emit()
        wait_until(lambda: panel.load_worker is None)
        assert panel.dataset is None
        assert str(missing) in messages[-1][1]
        assert not panel.create_scalp_button.isEnabled()

        FolderDialog.response = str(broken)
        panel._browse_results()
        wait_until(lambda: panel.load_worker is None)
        assert panel.dataset is None
        assert str(broken) in messages[-1][1]

        (broken / "participant_fft_amplitudes.csv").write_bytes(unmarked.read_bytes())
        panel.results_load_button.click()
        wait_until(lambda: panel.load_worker is None)
        assert panel.dataset is not None
        assert panel.frequency_spin.value() == 26.0
        assert panel.dataset.events[0].target_hz is None
        panel.frequency_spin.setValue(41.0)
        panel._event_changed()
        assert panel.frequency_spin.value() == 26.0
        assert panel.dataset.events[0].target_hz is None
        assert (broken / "participant_fft_amplitudes.csv").read_bytes() == unmarked.read_bytes()

        FolderDialog.response = str(known.parent)
        panel._browse_results()
        wait_until(lambda: panel.load_worker is None)
        assert panel.frequency_spin.value() == 10.0
        assert panel.dataset.events[0].target_hz == 10.0
        def fail_roi(**kwargs):
            raise OSError("Synthetic saved plot failure")
        saved_gui.create_saved_roi_outputs = fail_roi
        panel._start_plot("roi")
        wait_until(lambda: panel.plot_worker is None)
        assert "Synthetic saved plot failure" in messages[-1][1]
        assert len(messages) == 3, messages
        assert not callback_errors, callback_errors
        assert window.close()
        print("AUTO_LOAD_GUI_OK")
    '''), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(script), str(known), str(unmarked), str(broken)],
        cwd=repo_root,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root)),
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "AUTO_LOAD_GUI_OK" in completed.stdout
