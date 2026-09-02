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


def _write_all_conditions_fft(run_folder):
    source = _write_gui_fft(run_folder)
    template = pd.read_csv(source)
    records = []
    for participant, codes in (("P01", (11, 12, 21, 22)), ("P02", (11, 22))):
        for event_type, code in [("cue", code) for code in codes] + [("baseline", 1)]:
            record = template.copy()
            record["participant_id"] = participant
            record["file_name"] = participant + ".bdf"
            record["event_type"] = event_type
            record["trigger_code"] = code
            record["trigger_label"] = f"Condition {code}"
            record["target_hz"] = {11: 10.0, 12: 20.0, 22: 40.0}.get(code, float("nan"))
            records.append(record)
    pd.concat(records, ignore_index=True).to_csv(source, index=False)
    return source


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
                assert kwargs["stimulation_hz"] == 31.0
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
                panel.set_plot_settings(
                    roi_name="Central ROI", channels=("C3", "C4"), stimulation_hz=31.0,
                )
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
                assert panel.event_combo.count() == 2
                assert panel.event_combo.currentData() == ("cue", 11)
                assert panel.event_combo.findData("all") >= 0
                assert panel.dataset.channel_names == ("C3", "C4")
                assert panel.selected_channels == ("C3", "C4")
                assert panel.roi_name == "Central ROI"
                assert not hasattr(panel, "choose_roi_button")
                assert not hasattr(panel, "frequency_spin")
                assert panel.stimulation_hz == 31.0
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
                assert panel.selected_channels == ("C3", "C4")
                assert panel.roi_name == "Central ROI"
                assert panel.stimulation_hz == 31.0
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
                assert panel.selected_channels == ("C3", "C4")
                assert panel.roi_name == "Central ROI"
                assert panel.stimulation_hz == 31.0
                assert "Central ROI" in panel.plot_settings_label.text()
                assert "C3, C4" in panel.plot_settings_label.text()
                panel._start_plot("roi")
                pending = panel.plot_worker
                panel._start_plot("scalp")
                assert panel.plot_worker is pending
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
                assert panel.create_roi_button.isEnabled()
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
        panel.set_plot_settings(
            roi_name="Persistent ROI", channels=("C3", "C4"), stimulation_hz=41.0,
        )
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
        assert panel.stimulation_hz == 41.0
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
        assert panel.selected_channels == ("C3", "C4")
        assert panel.roi_name == "Persistent ROI"
        assert panel.stimulation_hz == 41.0
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
        assert panel.stimulation_hz == 41.0
        assert panel.dataset.events[0].target_hz is None
        panel.set_plot_settings(
            roi_name="Persistent ROI", channels=("C3", "C4"), stimulation_hz=None,
        )
        panel._populate_events()
        assert panel.stimulation_hz is None
        assert panel.dataset.events[0].target_hz is None
        assert (broken / "participant_fft_amplitudes.csv").read_bytes() == unmarked.read_bytes()

        FolderDialog.response = str(known.parent)
        panel._browse_results()
        wait_until(lambda: panel.load_worker is None)
        assert panel.stimulation_hz is None
        assert panel.selected_channels == ("C3", "C4")
        assert panel.roi_name == "Persistent ROI"
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


def _run_batch_plot_probe(tmp_path, name, body):
    source = _write_all_conditions_fft(tmp_path / "recorded_run")
    original_bytes = source.read_bytes()
    old_plot = source.parent / "saved_fft_plots" / "older.png"
    old_plot.parent.mkdir()
    old_plot.write_bytes(b"Preserve this previous plot")
    script = tmp_path / f"{name}.py"
    script.write_text(textwrap.dedent(r'''
        from pathlib import Path
        import sys
        import threading
        import time

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        import sssep_batch.saved_plots_gui as saved_gui

        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        source = Path(sys.argv[1])
        dataset = saved_gui.load_saved_fft_dataset(source)
        calls = []
        serial = 0

        def result_for(kind, kwargs):
            global serial
            assert threading.current_thread() is not threading.main_thread()
            assert kwargs["dataset"] is dataset
            serial += 1
            output_folder = source.parent / "saved_fft_plots"
            plot_path = output_folder / f"{kind}_{kwargs['trigger_code']}_{serial}.png"
            plot_path.write_bytes(f"Plot {serial}".encode())
            result = {"kind": kind, "output_folder": str(output_folder),
                      "plot_path": str(plot_path)}
            if kind == "roi":
                result.update(participant_count=1, used_channels=list(kwargs["channels"]))
            else:
                result.update(requested_frequency_hz=kwargs["frequency_hz"],
                              actual_frequency_hz=kwargs["frequency_hz"],
                              participant_count_min=1, participant_count_max=2)
            return result

        def wait_until(predicate):
            deadline = time.monotonic() + 8
            while not predicate() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            assert predicate(), "Timed out waiting for saved plot worker"
    ''') + textwrap.dedent(body), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(script), str(source)], cwd=repo_root,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root)),
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "SAVED_BATCH_OK" in completed.stdout
    assert source.read_bytes() == original_bytes
    assert old_plot.read_bytes() == b"Preserve this previous plot"


def test_saved_plot_worker_batches_events_and_uses_each_saved_frequency(tmp_path):
    _run_batch_plot_probe(tmp_path, "batch_worker", '''
        def roi_outputs(**kwargs):
            assert kwargs["channels"] == ("C3", "C4")
            assert kwargs["roi_name"] == "Configured ROI"
            calls.append(("roi", dict(kwargs)))
            return result_for("roi", kwargs)

        def scalp_outputs(**kwargs):
            calls.append(("scalp", dict(kwargs)))
            if kwargs["frequency_hz"] > 50:
                raise ValueError("Frequency exceeds saved FFT bounds")
            return result_for("scalp", kwargs)

        saved_gui.create_saved_roi_outputs = roi_outputs
        saved_gui.create_saved_scalp_outputs = scalp_outputs
        events = tuple(("cue", code) for code in (11, 12, 21, 22))
        base_request = dict(events=events, participant_id=None, channels=("c3", "C4", "MISSING"),
                            roi_name="Configured ROI", stimulation_hz=None)

        def run_worker(kind, **overrides):
            request = dict(base_request, kind=kind)
            request.update(overrides)
            worker = saved_gui.SavedPlotWorker(dataset, request, None)
            progress = []
            worker.progress.connect(progress.append, Qt.ConnectionType.DirectConnection)
            worker.start()
            assert worker.wait(5000), "Saved plot worker did not finish"
            app.processEvents()
            assert worker.error is None, worker.error
            assert worker.result["kind"] == kind
            assert worker.result["requested_count"] == len(request["events"])
            assert len(progress) >= len(request["events"])
            assert all(isinstance(message, str) and message for message in progress)
            return worker.result

        result = run_worker("roi")
        assert not result["failures"]
        assert len(result["outputs"]) == 4
        assert [output["trigger_code"] for output in result["outputs"]] == [11, 12, 21, 22]
        assert all(output["event_type"] == "cue" for output in result["outputs"])
        assert [output["trigger_label"] for output in result["outputs"]] == [
            "Condition 11", "Condition 12", "Condition 21", "Condition 22",
        ]
        assert [kwargs["stimulation_hz"] for _, kwargs in calls] == [10.0, 20.0, None, 40.0]
        assert all(kwargs["participant_id"] is None for _, kwargs in calls)
        assert all(Path(output["plot_path"]).is_file() for output in result["outputs"])
        assert base_request["channels"] == ("c3", "C4", "MISSING")

        calls.clear()
        scalp = run_worker("scalp")
        assert len(scalp["outputs"]) == 3
        assert len(scalp["failures"]) == 1
        assert "21" in scalp["failures"][0] and "Settings" in scalp["failures"][0]
        assert [kwargs["trigger_code"] for _, kwargs in calls] == [11, 12, 22]
        assert [kwargs["frequency_hz"] for _, kwargs in calls] == [10.0, 20.0, 40.0]

        calls.clear()
        override = run_worker("scalp", stimulation_hz=31.0)
        assert len(override["outputs"]) == 4 and not override["failures"]
        assert [kwargs["frequency_hz"] for _, kwargs in calls] == [31.0] * 4

        calls.clear()
        outside = run_worker("scalp", stimulation_hz=51.0)
        assert not outside["outputs"] and len(outside["failures"]) == 4
        assert not calls
        assert all("50 Hz" in failure and "Settings" in failure for failure in outside["failures"])

        absent = run_worker("roi", channels=("MISSING",))
        assert not absent["outputs"] and len(absent["failures"]) == 4
        assert absent["missing_channels"] == ["MISSING"]
        assert all("Settings" in failure for failure in absent["failures"])
        assert not calls
        print("SAVED_BATCH_OK")
    ''')


def test_all_conditions_panel_restricts_participant_and_continues_after_failure(tmp_path):
    _run_batch_plot_probe(tmp_path, "all_conditions_panel", '''
        from PySide6.QtWidgets import QDoubleSpinBox, QLabel
        from sssep_batch.gui_style import SectionCard

        middle_started, release = threading.Event(), threading.Event()
        messages, results, busy = [], [], []
        mode = "partial_failure"

        def roi_outputs(**kwargs):
            assert kwargs["channels"] == ("C3", "C4")
            assert kwargs["stimulation_hz"] == 31.0
            calls.append(dict(kwargs))
            if mode == "partial_failure" and kwargs["trigger_code"] == 12:
                middle_started.set()
                assert release.wait(5), "GUI did not release middle condition"
            if mode == "partial_failure" and kwargs["trigger_code"] == 21:
                raise ValueError("No usable ROI electrodes for condition 21")
            return result_for("roi", kwargs)

        class MessageBox:
            @staticmethod
            def warning(parent, title, message):
                assert panel.plot_worker is None
                assert not panel.is_busy()
                assert panel.create_roi_button.isEnabled()
                messages.append((title, message))
            critical = warning

        saved_gui.create_saved_roi_outputs = roi_outputs
        saved_gui.QMessageBox = MessageBox
        panel = saved_gui.SavedPlotsPanel()
        panel.set_plot_settings(roi_name="Configured ROI", channels=("C3", "C4"),
                                stimulation_hz=31.0)
        panel._results_loaded(dataset)
        panel._refresh_controls(False)
        panel.show()
        app.processEvents()
        assert len(panel.findChildren(SectionCard)) == 2
        assert not panel.findChildren(QDoubleSpinBox)
        assert not hasattr(panel, "choose_roi_button")
        assert any("Settings" in label.text() for label in panel.findChildren(QLabel))
        assert panel.event_combo.currentData() == ("cue", 11)
        assert ("baseline", 1) in [panel.event_combo.itemData(index)
                                    for index in range(panel.event_combo.count())]
        assert panel.event_combo.itemText(panel.event_combo.findData("all")) == "All conditions"
        panel.event_combo.setCurrentIndex(panel.event_combo.findData("all"))
        panel.busy_changed.connect(busy.append)
        panel._start_plot("roi")
        worker = panel.plot_worker
        worker.finished.connect(lambda: results.append(worker.result))
        assert worker.request["events"] == tuple(("cue", code) for code in (11, 12, 21, 22))
        wait_until(middle_started.is_set)
        assert panel.is_busy() and busy == [True]
        assert len(calls) == 2
        assert len(list((source.parent / "saved_fft_plots").glob("roi_11_*.png"))) == 1
        for widget in (panel.results_edit, panel.results_browse_button, panel.results_load_button,
                       panel.level_combo, panel.event_combo, panel.create_roi_button,
                       panel.create_scalp_button, panel.view_button):
            assert not widget.isEnabled()
        panel._start_plot("scalp")
        panel.ensure_results_loaded()
        assert panel.plot_worker is worker and panel.load_worker is None
        release.set()
        wait_until(lambda: panel.plot_worker is None)
        assert busy == [True, False]
        assert [call["trigger_code"] for call in calls] == [11, 12, 21, 22]
        assert all(call["event_type"] == "cue" for call in calls)
        assert len(results) == 1 and len(results[0]["outputs"]) == 3
        assert len(results[0]["failures"]) == 1
        assert len(messages) == 1 and "21" in messages[0][1]
        assert panel.view_button.isEnabled()
        assert panel.plot_output_folder == str(source.parent / "saved_fft_plots")
        successful_plots = {Path(result["plot_path"]): Path(result["plot_path"]).read_bytes()
                            for result in results[0]["outputs"]}

        calls.clear()
        mode = "success"
        panel.level_combo.setCurrentIndex(panel.level_combo.findData("participant"))
        panel.participant_combo.setCurrentIndex(panel.participant_combo.findData("P02"))
        participant_events = [panel.event_combo.itemData(index)
                              for index in range(panel.event_combo.count())]
        assert ("cue", 12) not in participant_events
        assert ("cue", 21) not in participant_events
        panel.event_combo.setCurrentIndex(panel.event_combo.findData("all"))
        panel._start_plot("roi")
        assert panel.plot_worker.request["events"] == (("cue", 11), ("cue", 22))
        wait_until(lambda: panel.plot_worker is None)
        assert [call["trigger_code"] for call in calls] == [11, 22]
        assert all(call["participant_id"] == "P02" for call in calls)
        assert panel.selected_channels == ("C3", "C4")
        assert panel.roi_name == "Configured ROI" and panel.stimulation_hz == 31.0

        calls.clear()
        panel.event_combo.setCurrentIndex(participant_events.index(("baseline", 1)))
        panel._populate_events()
        assert panel.event_combo.currentData() == ("baseline", 1)
        panel._start_plot("roi")
        assert panel.plot_worker.request["events"] == (("baseline", 1),)
        wait_until(lambda: panel.plot_worker is None)
        assert len(calls) == 1 and calls[0]["event_type"] == "baseline"
        panel.level_combo.setCurrentIndex(panel.level_combo.findData("group"))
        assert panel.event_combo.currentData() == ("baseline", 1)
        second_condition = next(index for index in range(panel.event_combo.count())
                                if panel.event_combo.itemData(index) == ("cue", 12))
        panel.event_combo.setCurrentIndex(second_condition)
        panel._populate_events()
        assert panel.event_combo.currentData() == ("cue", 12)
        assert all(path.read_bytes() == data for path, data in successful_plots.items())
        assert len(messages) == 1
        panel.close()
        print("SAVED_BATCH_OK")
    ''')
