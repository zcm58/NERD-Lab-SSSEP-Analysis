"""Exercise saved-FFT loading and post-processing GUI worker lifecycle."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pandas as pd


def test_saved_fft_tab_loads_results_and_runs_plot_off_ui_thread(tmp_path):
    """The third tab should load reusable FFT data and retain its plot worker."""

    run_folder = tmp_path / "run_test"
    run_folder.mkdir()
    pd.DataFrame(
        {
            "participant_id": ["P01", "P01", "P01"],
            "file_name": ["P01.bdf"] * 3,
            "event_type": ["cue"] * 3,
            "trigger_code": [11] * 3,
            "trigger_label": ["BothHands Left Hand"] * 3,
            "target_hz": [10.0] * 3,
            "usable_epochs": [4] * 3,
            "processing_method": ["fpvs_amplitude_v1"] * 3,
            "fft_schema_version": [1] * 3,
            "fpvs_reference_commit": [
                "185d803f0056daebee04e5f28cc6b554c47336ce"
            ] * 3,
            "montage_name": ["standard_1005"] * 3,
            "sampling_rate_hz": [40.0] * 3,
            "analysis_window_sec": [0.1] * 3,
            "plot_fmin_hz": [3.0] * 3,
            "plot_fmax_hz": [50.0] * 3,
            "analysis_channels": ["C3;C4"] * 3,
            "frequency_hz": [0.0, 10.0, 20.0],
            "analysis_mean_amplitude_uv": [1.5, 3.5, 5.5],
            "C3_amplitude_uv": [1.0, 3.0, 5.0],
            "C4_amplitude_uv": [2.0, 4.0, 6.0],
        }
    ).to_csv(run_folder / "participant_fft_amplitudes.csv", index=False)

    script = tmp_path / "saved_plot_gui_probe.py"
    script.write_text(
        textwrap.dedent(
            r'''
            from pathlib import Path
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
                started.set()
                assert release.wait(10), "GUI did not release saved plot worker"
                output_folder = run_folder / "saved_fft_plots" / "plot_test"
                output_folder.mkdir(parents=True)
                return {
                    "kind": "roi",
                    "output_folder": str(output_folder),
                    "plot_path": str(output_folder / "plot.png"),
                    "source_csv": str(output_folder / "plot_data.csv"),
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
                panel = window.saved_plots_tab
                assert window.tabs.tabText(2) == "Plot Saved FFT"
                assert not panel.create_roi_button.isEnabled()
                panel.results_edit.setText(str(run_folder))
                panel._load_results()
                assert panel.load_worker is not None
                QTimer.singleShot(10, wait_for_load)

            @checked
            def wait_for_load():
                window = QApplication.instance()._sssep_launcher_window
                panel = window.saved_plots_tab
                if panel.load_worker is not None:
                    QTimer.singleShot(10, wait_for_load)
                    return
                assert panel.dataset is not None
                assert panel.participant_combo.count() == 1
                assert panel.event_combo.count() == 1
                assert panel.channel_list.count() == 2
                assert panel.frequency_spin.value() == 10.0
                assert panel.create_roi_button.isEnabled()

                panel.results_edit.setText(str(run_folder.parent / "another_run"))
                assert panel.dataset is None
                assert panel.participant_combo.count() == 0
                assert panel.event_combo.count() == 0
                assert panel.channel_list.count() == 0
                assert not panel.create_roi_button.isEnabled()
                assert not panel.view_button.isEnabled()
                assert "Click Load Results" in panel.status_label.text()

                panel.results_edit.setText(str(run_folder))
                panel._load_results()
                QTimer.singleShot(10, wait_for_reload)

            @checked
            def wait_for_reload():
                window = QApplication.instance()._sssep_launcher_window
                panel = window.saved_plots_tab
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
                panel = window.saved_plots_tab
                if not started.is_set():
                    QTimer.singleShot(10, wait_for_plot_start)
                    return
                assert panel.plot_worker is not None
                assert panel.plot_worker.isRunning()
                assert not window.tabs.isTabEnabled(0)
                assert not window.tabs.isTabEnabled(1)
                assert not window.close(), "Active saved plot worker accepted close"
                release.set()
                QTimer.singleShot(10, wait_for_plot_finish)

            @checked
            def wait_for_plot_finish():
                window = QApplication.instance()._sssep_launcher_window
                panel = window.saved_plots_tab
                if panel.plot_worker is not None:
                    QTimer.singleShot(10, wait_for_plot_finish)
                    return
                assert window.tabs.isTabEnabled(0)
                assert window.tabs.isTabEnabled(1)
                assert panel.view_button.isEnabled()
                assert "using C3, C4" in panel.status_label.text()
                panel._view_plot()
                assert opened == [str(run_folder / "saved_fft_plots" / "plot_test")]
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
                gui.load_saved_folders = lambda: {}
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
