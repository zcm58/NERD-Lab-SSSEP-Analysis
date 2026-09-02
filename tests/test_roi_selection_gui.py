"""Exercise the native ROI selector against the website's BioSemi reference."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


# assets/js/roi-explorer.js at website commit 3b797ad45fdecf688a9d82b869a6b7a908f7a555.
# Keep this independent reference in the test; no website checkout is required.
WEBSITE_ELECTRODES = (
    ("Fp1", 18, -2), ("AF7", 36, -2), ("AF3", 25, 16),
    ("F1", 22, 40), ("F3", 39, 30), ("F5", 49, 15),
    ("F7", 54, -2), ("FT7", 72, -2), ("FC5", 69, 18),
    ("FC3", 62, 40), ("FC1", 45, 58), ("C1", 90, 67),
    ("C3", 90, 44), ("C5", 90, 21), ("T7", 90, -2),
    ("TP7", 108, -2), ("CP5", 111, 18), ("CP3", 118, 40),
    ("CP1", 135, 58), ("P1", 158, 40), ("P3", 141, 30),
    ("P5", 131, 15), ("P7", 126, -2), ("P9", 126, -25),
    ("PO7", 144, -2), ("PO3", 155, 16), ("O1", 162, -2),
    ("Iz", -180, -25), ("Oz", -180, -2), ("POz", -180, 21),
    ("Pz", -180, 44), ("CPz", -180, 67),
    ("Fpz", 0, -2), ("Fp2", -18, -2), ("AF8", -36, -2),
    ("AF4", -25, 16), ("AFz", 0, 21), ("Fz", 0, 44),
    ("F2", -22, 40), ("F4", -39, 30), ("F6", -49, 15),
    ("F8", -54, -2), ("FT8", -72, -2), ("FC6", -69, 18),
    ("FC4", -62, 40), ("FC2", -45, 58), ("FCz", 0, 67),
    ("Cz", -90, 90), ("C2", -90, 67), ("C4", -90, 44),
    ("C6", -90, 21), ("T8", -90, -2), ("TP8", -108, -2),
    ("CP6", -111, 18), ("CP4", -118, 40), ("CP2", -135, 58),
    ("P2", -158, 40), ("P4", -141, 30), ("P6", -131, 15),
    ("P8", -126, -2), ("P10", -126, -25), ("PO8", -144, -2),
    ("PO4", -155, 16), ("O2", -162, -2),
)
WEBSITE_PRESETS = {
    "lot": ("PO3", "P7", "PO7", "P9", "O1"),
    "rot": ("PO4", "P8", "PO8", "P10", "O2"),
    "central": ("C1", "Cz", "C2", "CP1", "CPz", "CP2"),
    "frontal": ("Fz", "FC1", "FC2", "Cz"),
}


def test_roi_selector_geometry_presets_custom_selection_and_validation(tmp_path):
    script = tmp_path / "roi_selector_probe.py"
    script.write_text(
        f"REFERENCE_ELECTRODES = {WEBSITE_ELECTRODES!r}\n"
        f"REFERENCE_PRESETS = {WEBSITE_PRESETS!r}\n"
        + textwrap.dedent(r'''
            from math import cos, pi, sin
            import os
            from pathlib import Path

            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtGui import QFont, QFontDatabase
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QDialog, QScrollArea, QTabBar
            from sssep_batch.roi_selection_gui import RoiSelectionDialog

            app = QApplication([])
            app.setQuitOnLastWindowClosed(False)
            font_folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            for name in ("segoeui.ttf", "segoeuib.ttf"):
                if (font_folder / name).is_file():
                    QFontDatabase.addApplicationFont(str(font_folder / name))
            app.setFont(QFont("Segoe UI", 10))
            settings_path = Path(__file__).with_name("rois.json")

            def selected_map(dialog):
                return {name for name, button in dialog.map_widget.electrode_buttons.items()
                        if button.isChecked()}

            def click(button):
                assert button.isVisible()
                assert button.isEnabled()
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                app.processEvents()

            names = tuple(item[0] for item in REFERENCE_ELECTRODES)
            dialog = RoiSelectionDialog(names, ("C3",), "Original ROI", roi_settings_path=settings_path)
            dialog.show()
            app.processEvents()
            canvas = dialog.map_widget
            buttons = canvas.electrode_buttons
            assert len(buttons) == 64
            assert set(buttons) == set(names)
            assert all(button.text() == name for name, button in buttons.items())
            assert all(button.isEnabled() for button in buttons.values())
            assert selected_map(dialog) == {"C3"}

            for extra_width in (0, 180):
                dialog.resize(dialog.width() + extra_width, dialog.height())
                app.processEvents()
                scale = min(canvas.width() / 640, canvas.height() / 590)
                left = (canvas.width() - 640 * scale) / 2
                top = (canvas.height() - 590 * scale) / 2
                for name, theta, phi in REFERENCE_ELECTRODES:
                    angle = -theta * pi / 180
                    radius = 390 * (0.5 - phi / 180)
                    expected_x = left + (320 + radius * sin(angle)) * scale
                    expected_y = top + (300 - radius * cos(angle)) * scale
                    actual = buttons[name].geometry().center()
                    assert abs(actual.x() - expected_x) <= 1.5, (name, actual, expected_x)
                    assert abs(actual.y() - expected_y) <= 1.5, (name, actual, expected_y)
                assert buttons["Fp1"].y() < buttons["O1"].y()
                assert buttons["C3"].x() < buttons["Cz"].x() < buttons["C4"].x()
                assert buttons["Fp1"].x() < buttons["Fp2"].x()

            click(buttons["C3"])
            click(buttons["C4"])
            assert selected_map(dialog) == {"C4"}
            buttons["Cz"].setFocus()
            QTest.keyClick(buttons["Cz"], Qt.Key.Key_Space)
            assert selected_map(dialog) == {"C4", "Cz"}
            assert dialog.selected_channels == ("C3",)
            assert dialog.roi_name == "Original ROI"

            assert set(dialog.preset_buttons) == set(REFERENCE_PRESETS)
            assert not dialog.findChildren(QTabBar)
            for preset, members in REFERENCE_PRESETS.items():
                click(dialog.preset_buttons[preset])
                assert selected_map(dialog) == set(members), preset

            click(dialog.preset_buttons["central"])
            click(buttons["C1"])
            click(buttons["C3"])
            custom = set(REFERENCE_PRESETS["central"]) - {"C1"} | {"C3"}
            assert selected_map(dialog) == custom
            dialog.name_edit.setText("Custom central")

            desktop_size = dialog.size()
            dialog.resize(800, 600)
            app.processEvents()
            QTest.qWait(10)
            app.processEvents()
            assert dialog.width() == 800 and dialog.height() == 600
            assert selected_map(dialog) == custom
            assert dialog.name_edit.text() == "Custom central"
            for scroll in dialog.findChildren(QScrollArea):
                assert scroll.horizontalScrollBar().maximum() == 0
            for button in (dialog.clear_button, dialog.cancel_button, dialog.use_button):
                origin = button.mapTo(dialog, QPoint(0, 0))
                assert origin.x() >= 0 and origin.y() >= 0
                assert origin.x() + button.width() <= dialog.width()
                assert origin.y() + button.height() <= dialog.height()
            dialog.resize(desktop_size)
            app.processEvents()
            assert selected_map(dialog) == custom

            dialog.name_edit.setText("   ")
            assert not dialog.use_button.isEnabled()
            assert not dialog.save_button.isEnabled()
            QTest.keyClick(dialog.name_edit, Qt.Key.Key_Return)
            assert dialog.result() != QDialog.DialogCode.Accepted
            dialog.name_edit.setText("Valid name")
            assert dialog.use_button.isEnabled()
            click(dialog.clear_button)
            assert selected_map(dialog) == set()
            assert not dialog.use_button.isEnabled()
            assert not dialog.save_button.isEnabled()
            click(buttons["C3"])
            click(buttons["C4"])
            dialog.name_edit.setText("  Bilateral central  ")
            click(dialog.use_button)
            assert dialog.result() == QDialog.DialogCode.Accepted
            assert dialog.selected_channels == ("C3", "C4")
            assert dialog.roi_name == "Bilateral central"

            available = ("c3", "C4", "X1")
            original = ("C3", "x1")
            limited = RoiSelectionDialog(available, original, "Original name", roi_settings_path=settings_path)
            limited.show()
            app.processEvents()
            limited_buttons = limited.map_widget.electrode_buttons
            assert selected_map(limited) == {"C3"}
            assert limited_buttons["C3"].isEnabled()
            assert not limited_buttons["Fp1"].isEnabled()
            limited_buttons["Fp1"].click()
            assert selected_map(limited) == {"C3"}
            assert limited.other_list.count() == 1
            extra = limited.other_list.item(0)
            assert extra.text() == "X1"
            assert extra.checkState() == Qt.CheckState.Checked
            extra.setCheckState(Qt.CheckState.Unchecked)
            click(limited_buttons["C4"])
            limited.name_edit.setText("Changed draft")
            assert limited.selected_channels == original
            assert limited.roi_name == "Original name"
            click(limited.cancel_button)
            assert limited.result() == QDialog.DialogCode.Rejected
            assert limited.selected_channels == original
            assert limited.roi_name == "Original name"

            confirmed = RoiSelectionDialog(available, original, "Case preserved", roi_settings_path=settings_path)
            confirmed.show()
            app.processEvents()
            click(confirmed.use_button)
            assert confirmed.selected_channels == ("c3", "X1")
            assert confirmed.roi_name == "Case preserved"

            partial = RoiSelectionDialog(("PO7", "P7", "X1"), ("X1",), "Original", roi_settings_path=settings_path)
            partial.show()
            app.processEvents()
            click(partial.preset_buttons["lot"])
            assert selected_map(partial) == {"PO7", "P7"}
            assert partial.other_list.item(0).checkState() == Qt.CheckState.Unchecked
            assert partial.missing_label.isVisible()
            assert partial.missing_label.text().endswith("PO3, P9, O1")
            assert not partial.preset_buttons["rot"].isEnabled()
            click(partial.use_button)
            assert partial.selected_channels == ("PO7", "P7")

            # Distinct saved labels must remain selectable even if they share a casefold.
            collision = RoiSelectionDialog(("c3", "C3", "X1"), ("c3",), "Original", roi_settings_path=settings_path)
            collision.show()
            app.processEvents()
            assert selected_map(collision) == set()
            assert collision.other_list.count() == 2
            duplicate = collision.other_list.item(0)
            assert duplicate.text() == "c3"
            assert duplicate.checkState() == Qt.CheckState.Checked
            click(collision.map_widget.electrode_buttons["C3"])
            assert duplicate.checkState() == Qt.CheckState.Checked
            click(collision.use_button)
            assert collision.selected_channels == ("c3", "C3")
            assert not settings_path.exists()
            print("ROI_SELECTION_GUI_OK")
        '''),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(script)], cwd=repo_root,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root)),
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ROI_SELECTION_GUI_OK" in completed.stdout


def _run_persistence_probe(tmp_path, name, body):
    script = tmp_path / f"{name}.py"
    script.write_text(textwrap.dedent(r'''
        import os
        from pathlib import Path
        import sys

        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
        import sssep_batch.roi_selection_gui as roi_gui
        from sssep_batch.roi_settings import load_custom_rois

        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        font_folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for font in ("segoeui.ttf", "segoeuib.ttf"):
            if (font_folder / font).is_file():
                QFontDatabase.addApplicationFont(str(font_folder / font))
        app.setFont(QFont("Segoe UI", 10))
        settings_path = Path(sys.argv[1])
        warnings = []
        questions = []
        answers = []

        def question(parent, title, message, buttons, default):
            questions.append((title, message, buttons, default))
            assert answers, "Unexpected overwrite confirmation"
            return answers.pop(0)

        QMessageBox.question = question
        QMessageBox.warning = lambda parent, title, message: warnings.append(message)

        def dialog_for(channels=("C3", "C4", "Cz"), selected=("Cz",), name="Original"):
            dialog = roi_gui.RoiSelectionDialog(
                channels, selected, name, roi_settings_path=settings_path,
            )
            dialog.show()
            app.processEvents()
            return dialog

        def click(button):
            assert button.isVisible() and button.isEnabled()
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            app.processEvents()

        def selected_map(dialog):
            return {name for name, button in dialog.map_widget.electrode_buttons.items()
                    if button.isChecked()}

        def select_saved(dialog, name):
            index = dialog.saved_combo.findData(name)
            assert index > 0, name
            dialog.saved_combo.setCurrentIndex(index)
            dialog.saved_combo.activated.emit(index)
            app.processEvents()
    ''') + textwrap.dedent(body) + '\nprint("ROI_PERSISTENCE_OK")\n', encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "custom_rois.json")], cwd=repo_root,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root)),
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ROI_PERSISTENCE_OK" in completed.stdout


def test_custom_single_and_multiple_electrode_rois_survive_restart_and_cancel(tmp_path):
    _run_persistence_probe(tmp_path, "save_custom_rois", '''
        dialog = dialog_for()
        assert dialog.saved_combo.itemData(0) is None
        click(dialog.clear_button)
        dialog.name_edit.setText("Left hand")
        click(dialog.map_widget.electrode_buttons["C3"])
        assert dialog.name_edit.text() == "Left hand"
        click(dialog.save_button)
        assert dialog.isVisible()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert dialog.selected_channels == ("Cz",)
        assert dialog.roi_name == "Original"
        assert load_custom_rois(settings_path) == {"Left hand": ("C3",)}

        click(dialog.map_widget.electrode_buttons["C4"])
        dialog.name_edit.setText("Bilateral hand")
        click(dialog.save_button)
        assert load_custom_rois(settings_path) == {
            "Left hand": ("C3",), "Bilateral hand": ("C3", "C4"),
        }
        click(dialog.cancel_button)
        assert dialog.selected_channels == ("Cz",)
        assert dialog.roi_name == "Original"

        reopened = dialog_for()
        select_saved(reopened, "Left hand")
        assert selected_map(reopened) == {"C3"}
        assert reopened.name_edit.text() == "Left hand"
        assert reopened.selected_channels == ("Cz",)
        click(reopened.use_button)
        assert reopened.selected_channels == ("C3",)
        assert reopened.roi_name == "Left hand"
        assert not warnings and not questions
    ''')
    before_restart = (tmp_path / "custom_rois.json").read_bytes()
    _run_persistence_probe(tmp_path, "load_after_restart", '''
        dialog = dialog_for()
        assert dialog.saved_combo.count() == 3
        select_saved(dialog, "Bilateral hand")
        assert selected_map(dialog) == {"C3", "C4"}
        assert dialog.name_edit.text() == "Bilateral hand"
        assert dialog.selected_channels == ("Cz",)
        click(dialog.use_button)
        assert dialog.selected_channels == ("C3", "C4")
        assert dialog.roi_name == "Bilateral hand"

        partial = dialog_for(("c3", "Cz"))
        select_saved(partial, "Bilateral hand")
        assert selected_map(partial) == {"C3"}
        assert partial.missing_label.isVisible()
        assert partial.missing_label.text().endswith("C4")
        click(partial.use_button)
        assert partial.selected_channels == ("c3",)

        unavailable = dialog_for(("Cz",))
        select_saved(unavailable, "Bilateral hand")
        assert selected_map(unavailable) == set()
        assert not unavailable.use_button.isEnabled()
        assert not unavailable.save_button.isEnabled()
        assert unavailable.missing_label.text().endswith("C3, C4")
        click(unavailable.cancel_button)
        assert not warnings and not questions
    ''')
    assert (tmp_path / "custom_rois.json").read_bytes() == before_restart


def test_custom_roi_overwrite_confirmation_and_failed_save_recovery(tmp_path):
    _run_persistence_probe(tmp_path, "overwrite_and_failure", '''
        dialog = dialog_for(selected=("C3",))
        dialog.name_edit.setText("Hand ROI")
        click(dialog.save_button)
        original_bytes = settings_path.read_bytes()

        click(dialog.map_widget.electrode_buttons["C4"])
        dialog.name_edit.setText("hand roi")
        answers.append(QMessageBox.StandardButton.No)
        click(dialog.save_button)
        assert settings_path.read_bytes() == original_bytes
        assert selected_map(dialog) == {"C3", "C4"}
        assert questions[-1][3] == QMessageBox.StandardButton.No
        assert questions[-1][2] == (
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        answers.append(QMessageBox.StandardButton.Yes)
        click(dialog.save_button)
        saved = load_custom_rois(settings_path)
        assert len(saved) == 1
        saved_name = next(iter(saved))
        assert saved_name.casefold() == "hand roi"
        assert saved[saved_name] == ("C3", "C4")

        # An OS replacement error must preserve disk and allow a later retry.
        import sssep_batch.roi_settings as roi_storage
        real_replace = roi_storage.os.replace
        def failed_replace(*args, **kwargs):
            raise PermissionError("Test ROI file is locked")
        roi_storage.os.replace = failed_replace
        dialog.name_edit.setText("Retry ROI")
        saved_bytes = settings_path.read_bytes()
        click(dialog.save_button)
        assert settings_path.read_bytes() == saved_bytes
        assert len(warnings) == 1 and "locked" in warnings[0]
        assert dialog.save_button.isEnabled() and dialog.use_button.isEnabled()
        assert dialog.saved_combo.findData("Retry ROI") == -1
        assert dialog.selected_channels == ("C3",)
        roi_storage.os.replace = real_replace
        click(dialog.save_button)
        assert load_custom_rois(settings_path)["Retry ROI"] == ("C3", "C4")
        assert dialog.saved_combo.findData("Retry ROI") > 0
        click(dialog.cancel_button)
        assert dialog.selected_channels == ("C3",)
        assert dialog.roi_name == "Original"
    ''')


def test_invalid_saved_roi_file_is_reported_and_preserved(tmp_path):
    settings_path = tmp_path / "custom_rois.json"
    settings_path.write_text('{"unfinished":', encoding="utf-8")
    original_bytes = settings_path.read_bytes()
    _run_persistence_probe(tmp_path, "invalid_saved_rois", '''
        dialog = dialog_for(selected=("C3",))
        assert "Could not load" in dialog.roi_status_label.text()
        assert not dialog.save_button.isEnabled()
        assert dialog.use_button.isEnabled()
        click(dialog.map_widget.electrode_buttons["C4"])
        dialog.name_edit.setText("Unsaved ROI")
        assert not dialog.save_button.isEnabled()
        click(dialog.use_button)
        assert dialog.selected_channels == ("C3", "C4")
        assert dialog.roi_name == "Unsaved ROI"
    ''')
    assert settings_path.read_bytes() == original_bytes
