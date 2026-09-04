"""Participant-entered demographics shown before a normal SSSEP task."""

from __future__ import annotations

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .models import (
    PARTICIPANT_HANDEDNESS_VALUES,
    PARTICIPANT_SEX_VALUES,
    ParticipantInformation,
)


class ParticipantInformationDialog(QDialog):
    """Collect the required FPVS Studio participant-information fields."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Participant Information")
        self.setModal(True)
        self.setMinimumSize(600, 320)
        self.resize(600, 320)

        self.prompt_label = QLabel("Please enter the participant details.", self)

        self.participant_number_edit = QLineEdit(self)
        self.participant_number_edit.setPlaceholderText(
            "Digits only (for example, 0012)"
        )
        self.participant_number_edit.setFocus()

        self.age_edit = QLineEdit(self)
        self.age_edit.setPlaceholderText("Whole number from 1 to 120")
        self.age_edit.setValidator(QIntValidator(1, 120, self.age_edit))

        self.sex_combo = QComboBox(self)
        self.sex_combo.addItem("Select sex...", None)
        for value in PARTICIPANT_SEX_VALUES:
            self.sex_combo.addItem(value, value)

        self.handedness_combo = QComboBox(self)
        self.handedness_combo.addItem("Select handedness...", None)
        for value in PARTICIPANT_HANDEDNESS_VALUES:
            self.handedness_combo.addItem(value, value)

        self.colorblind_combo = QComboBox(self)
        self.colorblind_combo.addItem("Select yes or no...", None)
        self.colorblind_combo.addItem("No", False)
        self.colorblind_combo.addItem("Yes", True)

        form_layout = QFormLayout()
        form_layout.addRow("Participant Number", self.participant_number_edit)
        form_layout.addRow("Age", self.age_edit)
        form_layout.addRow("Sex", self.sex_combo)
        form_layout.addRow("Handedness", self.handedness_combo)
        form_layout.addRow("Are you colorblind?", self.colorblind_combo)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.prompt_label)
        layout.addLayout(form_layout)
        layout.addWidget(self.button_box)

    @property
    def participant_information(self) -> ParticipantInformation:
        """Return the validated values after the dialog has been accepted."""

        return ParticipantInformation(
            participant_number=self.participant_number_edit.text(),
            age=int(self.age_edit.text().strip()),
            sex=self.sex_combo.currentData(),
            handedness=self.handedness_combo.currentData(),
            colorblind=self.colorblind_combo.currentData(),
        )

    def accept(self) -> None:
        participant_number = self.participant_number_edit.text().strip()
        if not participant_number:
            self._warn(
                "Participant Number Required",
                "Enter a participant number to start the task.",
                self.participant_number_edit,
            )
            return
        if not participant_number.isdigit():
            self._warn(
                "Invalid Participant Number",
                "Participant number must contain digits only.",
                self.participant_number_edit,
                select_all=True,
            )
            return

        age_text = self.age_edit.text().strip()
        if not age_text:
            self._warn(
                "Age Required",
                "Enter the participant age to start the task.",
                self.age_edit,
            )
            return
        if not age_text.isdigit() or not 1 <= int(age_text) <= 120:
            self._warn(
                "Invalid Age",
                "Participant age must be a whole number from 1 to 120.",
                self.age_edit,
                select_all=True,
            )
            return
        if self.sex_combo.currentData() is None:
            self._warn(
                "Sex Required",
                "Select the participant sex to start the task.",
                self.sex_combo,
            )
            return
        if self.handedness_combo.currentData() is None:
            self._warn(
                "Handedness Required",
                "Select the participant handedness to start the task.",
                self.handedness_combo,
            )
            return
        if self.colorblind_combo.currentData() is None:
            self._warn(
                "Colorblind Status Required",
                "Select whether the participant is colorblind to start the task.",
                self.colorblind_combo,
            )
            return

        self.participant_number_edit.setText(participant_number)
        self.age_edit.setText(age_text)
        super().accept()

    def _warn(
        self,
        title: str,
        message: str,
        field: QWidget,
        *,
        select_all: bool = False,
    ) -> None:
        QMessageBox.warning(self, title, message)
        field.setFocus()
        if select_all and isinstance(field, QLineEdit):
            field.selectAll()


def collect_participant_information(
    parent: QWidget | None = None,
) -> ParticipantInformation | None:
    """Show the modal survey and return its values, or ``None`` if cancelled."""

    dialog = ParticipantInformationDialog(parent)
    if dialog.exec() != int(QDialog.DialogCode.Accepted):
        return None
    return dialog.participant_information
