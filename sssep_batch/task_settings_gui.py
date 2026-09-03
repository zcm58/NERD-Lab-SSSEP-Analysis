"""File > Settings editor for the SSSEP launcher."""

from collections.abc import Callable
from dataclasses import replace
from math import isfinite
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sssep_batch.experiment import TaskSettings
from sssep_batch.gui_style import (
    SectionCard,
    apply_launcher_style,
    build_page,
    hint_label,
    make_form,
)
from sssep_batch.roi_selection_gui import RoiSelectionDialog
from sssep_batch.launcher_settings import validate_plot_rois


class TaskSettingsDialog(QDialog):
    """Edit a draft; nothing reaches the launcher until Save succeeds."""

    def __init__(
        self, settings: TaskSettings, *, channels: tuple[str, ...],
        plot_channel: str, stimulation_hz: float | None, remember_folders: bool,
        plot_rois: dict[str, tuple[str, ...]],
        roi_available_channels: tuple[str, ...],
        parent: QWidget,
        on_save: Callable[
            [TaskSettings, str, float | None, bool, dict[str, tuple[str, ...]]], None
        ] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("SSSEP Settings")
        self.settings = settings
        self.plot_channel = plot_channel
        self.stimulation_hz = stimulation_hz
        self.remember_folders = remember_folders
        self.plot_rois = validate_plot_rois(plot_rois)
        self._roi_available_channels = roi_available_channels
        self._on_save = on_save

        self.epoch_duration_spin = self._duration_spin(settings.epoch_duration_sec)
        self.break_duration_spin = self._duration_spin(settings.break_duration_sec)
        self.epochs_per_condition_spin = QSpinBox()
        self.epochs_per_condition_spin.setRange(2, 10000)
        self.epochs_per_condition_spin.setSingleStep(2)
        self.epochs_per_condition_spin.setValue(settings.epochs_per_condition)
        self.epochs_per_condition_spin.setToolTip(
            "Equal epoch counts for the two trigger codes in each condition, "
            "in a fresh random order."
        )
        self.task_log_edit = QLineEdit(
            str(settings.output_folder) if settings.output_folder else ""
        )
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_task_log)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.task_log_edit)
        folder_row.addWidget(browse)
        self.test_mode_checkbox = QCheckBox("Test mode (no BioSemi triggers)")
        self.test_mode_checkbox.setChecked(settings.test_mode)
        self.show_timer_checkbox = QCheckBox("Show countdown timer")
        self.show_timer_checkbox.setChecked(settings.show_timer)

        session_card = SectionCard("Session settings")
        session_form = make_form()
        session_form.addRow("Duration of each epoch", self.epoch_duration_spin)
        session_form.addRow("Break between epochs", self.break_duration_spin)
        session_form.addRow("Epochs per condition (even)", self.epochs_per_condition_spin)
        session_form.addRow("Task log folder", folder_row)
        session_card.body.addLayout(session_form)
        session_card.body.addWidget(self.show_timer_checkbox)
        session_card.body.addWidget(self.test_mode_checkbox)
        session_card.body.addWidget(hint_label(
            "Both hands always runs first, followed by right hand / right ankle. "
            "Each condition uses the epoch count above. TENS is controlled externally."
        ))

        trigger_card = SectionCard("BioSemi trigger codes (fixed)")
        trigger_form = make_form()
        self.trigger_spins = []
        codes = settings.trigger_codes
        for label, code in (
            ("Both hands: left hand", codes.both_hands_left_hand),
            ("Both hands: right hand", codes.both_hands_right_hand),
            ("Hand/ankle: right hand", codes.right_hand_and_ankle_right_hand),
            ("Hand/ankle: right ankle", codes.right_hand_and_ankle_right_ankle),
        ):
            spin = QSpinBox()
            spin.setRange(code, code)
            spin.setValue(code)
            spin.setEnabled(False)
            trigger_form.addRow(label, spin)
            self.trigger_spins.append(spin)
        trigger_card.body.addLayout(trigger_form)
        for card in (session_card, trigger_card):
            card.layout().setContentsMargins(14, 10, 14, 10)
            card.layout().setSpacing(6)
            card.body.setSpacing(6)
        session_form.setVerticalSpacing(6)
        trigger_form.setVerticalSpacing(6)

        text_card = SectionCard("Participant text", "The words shown during timed screens.")
        text_form = make_form()
        for name, label in (
            ("left_hand_prompt", "Left hand text"),
            ("right_hand_prompt", "Right hand text"),
            ("right_ankle_prompt", "Right ankle text"),
            ("break_prompt", "Break text"),
        ):
            edit = QLineEdit(getattr(settings, name))
            setattr(self, f"{name}_edit", edit)
            text_form.addRow(label, edit)
        text_card.body.addLayout(text_form)

        self.plot_channel_combo = QComboBox()
        self.plot_channel_combo.addItems(channels)
        self.plot_channel_combo.setCurrentText(plot_channel)
        self.stimulation_frequency_edit = QLineEdit(
            "" if stimulation_hz is None else f"{stimulation_hz:g}"
        )
        self.stimulation_frequency_edit.setPlaceholderText("Optional")
        self.save_folders_checkbox = QCheckBox("Save recording folders for next time")
        self.save_folders_checkbox.setChecked(remember_folders)
        analysis_card = SectionCard("Recording analysis")
        analysis_form = make_form()
        analysis_form.addRow("Electrode for processing plots", self.plot_channel_combo)
        analysis_form.addRow(
            "TENS Unit Stimulation Frequency (Hz)", self.stimulation_frequency_edit
        )
        analysis_card.body.addLayout(analysis_form)
        analysis_card.body.addWidget(self.save_folders_checkbox)
        analysis_card.body.addWidget(hint_label(
            "Analysis uses both conditions and the session duration and epoch count. "
            "Match these settings to the recordings before processing. "
            "For saved plots, a blank frequency uses each condition's saved value."
        ))

        roi_card = SectionCard(
            "Regions of Interest", "Each entry creates a separate FFT plot for each selected condition."
        )
        self.roi_list = QListWidget()
        self.roi_list.setMinimumHeight(220)
        self.roi_list.setAccessibleName("ROIs to plot separately")
        self.roi_list.currentRowChanged.connect(self._update_roi_actions)
        self.roi_list.itemDoubleClicked.connect(lambda _item: self._edit_roi())
        self.add_roi_button = QPushButton("Add ROI...")
        self.add_roi_button.clicked.connect(lambda: self._edit_roi(add=True))
        self.edit_roi_button = QPushButton("Edit ROI...")
        self.edit_roi_button.clicked.connect(lambda: self._edit_roi())
        self.remove_roi_button = QPushButton("Remove")
        self.remove_roi_button.clicked.connect(self._remove_roi)
        roi_actions = QHBoxLayout()
        for button in (self.add_roi_button, self.edit_roi_button, self.remove_roi_button):
            roi_actions.addWidget(button)
        roi_card.body.addWidget(self.roi_list)
        roi_card.body.addLayout(roi_actions)
        self._refresh_roi_list()

        tabs = QTabWidget()
        session_body = None
        for title, cards in (
            ("Session", (session_card, trigger_card)),
            ("Participant text", (text_card,)),
            ("Analysis", (analysis_card,)),
            ("Regions of Interest", (roi_card,)),
        ):
            page = QWidget()
            body, footer = build_page(page)
            footer.parentWidget().hide()
            for card in cards:
                body.addWidget(card)
            tabs.addTab(page, title)
            if title == "Session":
                session_body = body
        self.tabs = tabs
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty("uiRole", "primary")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)
        apply_launcher_style(self)
        self.ensurePolished()
        available = self.screen().availableGeometry()
        chrome_height = (
            tabs.tabBar().sizeHint().height() + buttons.sizeHint().height()
            + layout.contentsMargins().top() + layout.contentsMargins().bottom()
            + layout.spacing()
        )
        content_height = session_body.parentWidget().sizeHint().height()
        self.resize(
            min(780, available.width() - 48),
            min(max(820, content_height + chrome_height), available.height() - 64),
        )

    @staticmethod
    def _duration_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.1, 3600.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.5)
        spin.setValue(value)
        spin.setSuffix(" seconds")
        return spin

    def _browse_task_log(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose Task Log Folder", self.task_log_edit.text().strip()
        )
        if folder:
            self.task_log_edit.setText(folder)

    def _edit_roi(self, *, add: bool = False) -> None:
        item = self.roi_list.currentItem()
        old_name = None if add or item is None else item.data(Qt.ItemDataRole.UserRole)
        if not add and old_name is None:
            return
        dialog = RoiSelectionDialog(
            available_channels=self._roi_available_channels,
            selected_channels=() if add else self.plot_rois[old_name],
            roi_name="" if add else old_name,
            parent=self,
        )
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                name, channels = next(iter(validate_plot_rois({
                    dialog.roi_name: dialog.selected_channels,
                }).items()))
                if any(
                    key != old_name and key.casefold() == name.casefold()
                    for key in self.plot_rois
                ):
                    QMessageBox.warning(
                        self, "ROI Name Already Used",
                        f"An ROI named {name!r} is already in the list. "
                        "Edit that entry or choose a different name.",
                    )
                    return
                if old_name is None:
                    self.plot_rois[name] = channels
                else:
                    self.plot_rois = {
                        name if key == old_name else key:
                        channels if key == old_name else value
                        for key, value in self.plot_rois.items()
                    }
                self._refresh_roi_list(name)
        except ValueError as exc:
            QMessageBox.warning(self, "ROI Needs Attention", str(exc))
        finally:
            dialog.deleteLater()

    def _refresh_roi_list(self, selected_name: str | None = None) -> None:
        self.roi_list.clear()
        for name, channels in self.plot_rois.items():
            item = QListWidgetItem(f"{name}\n{', '.join(channels)}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.roi_list.addItem(item)
            if name == selected_name:
                self.roi_list.setCurrentItem(item)
        if self.roi_list.currentRow() < 0 and self.roi_list.count():
            self.roi_list.setCurrentRow(0)
        self._update_roi_actions()

    def _update_roi_actions(self) -> None:
        selected = self.roi_list.currentItem() is not None
        self.edit_roi_button.setEnabled(selected)
        self.remove_roi_button.setEnabled(selected)

    def _remove_roi(self) -> None:
        item = self.roi_list.currentItem()
        if item is not None:
            del self.plot_rois[item.data(Qt.ItemDataRole.UserRole)]
            self._refresh_roi_list()

    def _save(self) -> None:
        try:
            frequency_text = self.stimulation_frequency_edit.text().strip()
            try:
                frequency = float(frequency_text) if frequency_text else None
            except ValueError as exc:
                raise ValueError(
                    "Stimulation frequency must be a number, or left blank."
                ) from exc
            if frequency is not None and (not isfinite(frequency) or frequency <= 0):
                raise ValueError("Stimulation frequency must be a finite number above zero.")
            folder = self.task_log_edit.text().strip()
            settings = replace(
                self.settings,
                epoch_duration_sec=self.epoch_duration_spin.value(),
                epochs_per_condition=self.epochs_per_condition_spin.value(),
                break_duration_sec=self.break_duration_spin.value(),
                output_folder=Path(folder) if folder else None,
                test_mode=self.test_mode_checkbox.isChecked(),
                show_timer=self.show_timer_checkbox.isChecked(),
                left_hand_prompt=self.left_hand_prompt_edit.text(),
                right_hand_prompt=self.right_hand_prompt_edit.text(),
                right_ankle_prompt=self.right_ankle_prompt_edit.text(),
                break_prompt=self.break_prompt_edit.text(),
            )
            plot_channel = self.plot_channel_combo.currentText()
            remember_folders = self.save_folders_checkbox.isChecked()
            if self._on_save is not None:
                self._on_save(
                    settings, plot_channel, frequency, remember_folders,
                    validate_plot_rois(self.plot_rois),
                )
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Settings Need Attention", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(
                self, "Could Not Save Settings",
                f"Settings were not changed. Please try again.\n\n{exc}",
            )
            return
        self.settings = settings
        self.plot_channel = plot_channel
        self.stimulation_hz = frequency
        self.remember_folders = remember_folders
        self.accept()
