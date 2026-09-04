"""Exercise the participant-entered survey without opening a visible window."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_participant_information_dialog_matches_fpvs_studio_fields(tmp_path):
    script = tmp_path / "participant_information_probe.py"
    script.write_text(
        textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication, QDialog

            import sssep_batch.experiment.participant_information as module

            app = QApplication([])
            dialog = module.ParticipantInformationDialog()
            assert dialog.windowTitle() == "Participant Information"
            assert [
                dialog.sex_combo.itemText(index)
                for index in range(dialog.sex_combo.count())
            ] == ["Select sex...", "Female", "Male"]
            assert [
                dialog.handedness_combo.itemText(index)
                for index in range(dialog.handedness_combo.count())
            ] == [
                "Select handedness...",
                "Right handed",
                "Left handed",
                "Ambidextrous",
            ]
            assert [
                dialog.colorblind_combo.itemText(index)
                for index in range(dialog.colorblind_combo.count())
            ] == ["Select yes or no...", "No", "Yes"]

            warnings = []
            module.QMessageBox.warning = (
                lambda _parent, title, message: warnings.append((title, message))
            )
            dialog.accept()
            assert dialog.result() != int(QDialog.DialogCode.Accepted)

            dialog.participant_number_edit.setText(" 0012 ")
            dialog.age_edit.setText("24")
            dialog.sex_combo.setCurrentIndex(dialog.sex_combo.findData("Female"))
            dialog.handedness_combo.setCurrentIndex(
                dialog.handedness_combo.findData("Right handed")
            )
            dialog.colorblind_combo.setCurrentIndex(
                dialog.colorblind_combo.findData(False)
            )
            dialog.accept()

            assert dialog.result() == int(QDialog.DialogCode.Accepted)
            assert dialog.participant_information.participant_number == "0012"
            assert dialog.participant_information.age == 24
            assert dialog.participant_information.sex == "Female"
            assert dialog.participant_information.handedness == "Right handed"
            assert dialog.participant_information.colorblind is False
            assert warnings == [
                ("Participant Number Required", "Enter a participant number to start the task.")
            ]
            app.quit()
            """
        ),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=repo_root,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(repo_root)),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
