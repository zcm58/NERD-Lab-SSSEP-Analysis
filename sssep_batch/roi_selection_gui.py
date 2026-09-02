"""Native electrode/ROI selector; selection changes never recompute FFT data.

Map geometry and FPVS example presets adapted from Zack Murphy's website,
``assets/js/roi-explorer.js`` at 3b797ad45fdecf688a9d82b869a6b7a908f7a555.
Coordinate source: https://www.biosemi.com/download/Cap_coords_all.xls.
The presets are examples from FPVS studies, not validated SSSEP definitions.
"""

from collections.abc import Iterable
from math import cos, pi, sin
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QBoxLayout, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from sssep_batch.gui_style import apply_launcher_style, hint_label
from sssep_batch.roi_settings import ROI_SETTINGS_PATH, load_custom_rois, save_custom_roi


_ELECTRODES = (
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
_PRESETS = {
    "lot": ("Left occipito-temporal", ("PO3", "P7", "PO7", "P9", "O1"), "#69d2ff"),
    "rot": ("Right occipito-temporal", ("PO4", "P8", "PO8", "P10", "O2"), "#ff9b73"),
    "central": ("Central", ("C1", "Cz", "C2", "CP1", "CPz", "CP2"), "#7de0b8"),
    "frontal": ("Fronto-central", ("Fz", "FC1", "FC2", "Cz"), "#d5a7ff"),
}


class _ElectrodeMap(QWidget):
    """Nose-up scalp drawing with native, keyboard-accessible toggle buttons."""

    selection_changed = Signal(str, bool)

    def __init__(self, available: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self._available = available
        self.setMinimumSize(520, 480)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.electrode_buttons = {}
        self._positions = {}
        self._colors = {}
        for label, theta, phi in _ELECTRODES:
            radius, angle = 0.5 - phi / 180, -theta * pi / 180
            self._positions[label] = (320 + 390 * radius * sin(angle), 300 - 390 * radius * cos(angle))
            button = QToolButton(self)
            button.setText(label)
            button.setCheckable(True)
            button.setEnabled(label.casefold() in available)
            button.setAccessibleName(f"Electrode {label}")
            button.setToolTip(
                f"{available[label.casefold()]}: click or press Space to select or clear."
                if button.isEnabled() else f"{label}: not available in this dataset."
            )
            button.toggled.connect(lambda checked, name=label: self.selection_changed.emit(name, checked))
            self.electrode_buttons[label] = button

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        # Wrapping sidebar labels make the row use height-for-width sizing.
        # A tall preferred height here would force scrolling even when the
        # scalable map fits comfortably in the available viewport.
        return QSize(640, 480)

    def _transform(self) -> tuple[float, float, float]:
        scale = min(self.width() / 640, self.height() / 590)
        return scale, (self.width() - 640 * scale) / 2, (self.height() - 590 * scale) / 2

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        scale, left, top = self._transform()
        diameter = max(30, round(34 * scale))
        for label, button in self.electrode_buttons.items():
            x, y = self._positions[label]
            button.setGeometry(round(left + x * scale - diameter / 2), round(top + y * scale - diameter / 2), diameter, diameter)
        self._style_buttons()

    def set_selection(self, selected: set[str], preset: str | None) -> None:
        membership = {}
        for key in _PRESETS:
            for label in _PRESETS[key][1]:
                if label not in membership or key == preset:
                    membership[label] = _PRESETS[key][2]
        self._colors = membership
        for label, button in self.electrode_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(self._available.get(label.casefold()) in selected)
        self._style_buttons()

    def _style_buttons(self) -> None:
        scale, _, _ = self._transform()
        for label, button in self.electrode_buttons.items():
            color = self._colors.get(label, "#6eb7ff")
            if not button.isEnabled():
                background, text, border = "#111d2a", "#627185", "#2a3c50"
            elif button.isChecked():
                background, text, border = color, "#07111f", "#f5f7fa"
            else:
                background = QColor(color).darker(240).name() if label in self._colors else "#142a40"
                text, border = "#d8e4ef", "#506c86"
            button.setStyleSheet(f"""
                QToolButton {{ background: {background}; color: {text};
                    border: {3 if button.isChecked() else 1}px solid {border};
                    border-radius: {button.width() // 2}px; padding: 0;
                    font-size: {max(11, round(11 * scale))}px; font-weight: 600; }}
                QToolButton:hover:enabled, QToolButton:focus {{ border: 3px solid #ffd166; }}
            """)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#07111f"))
        scale, left, top = self._transform()
        painter.translate(left, top)
        painter.scale(scale, scale)
        painter.setPen(QPen(QColor("#93a7bc"), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(320, 300), 195, 195)
        outline = QPainterPath(QPointF(289, 108))
        outline.lineTo(320, 77)
        outline.lineTo(351, 108)
        outline.moveTo(123, 262)
        outline.cubicTo(92, 267, 91, 333, 123, 338)
        outline.moveTo(517, 262)
        outline.cubicTo(548, 267, 549, 333, 517, 338)
        painter.drawPath(outline)
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#bcc8d4"))
        for text, rect in (
            ("FRONT", QRectF(260, 21, 120, 24)),
            ("BACK", QRectF(260, 560, 120, 24)),
            ("LEFT", QRectF(12, 288, 70, 24)),
            ("RIGHT", QRectF(558, 288, 70, 24)),
        ):
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class RoiSelectionDialog(QDialog):
    """Edit a draft selection; only Use ROI changes the returned values."""

    def __init__(
        self, available_channels: Iterable[str], selected_channels: Iterable[str],
        roi_name: str, parent=None, *, roi_settings_path: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose electrodes / ROI")
        self.setModal(True)
        self.selected_channels = tuple(selected_channels)
        self.roi_name = roi_name
        self._available = tuple(available_channels)
        self._lookup = {}
        for label in self._available:
            self._lookup.setdefault(label.casefold(), label)
        for label, _, _ in _ELECTRODES:
            if label in self._available:
                self._lookup[label.casefold()] = label
        unknown = [label for label in self.selected_channels if label.casefold() not in self._lookup]
        if unknown:
            raise ValueError(f"Selected electrodes are not available: {', '.join(unknown)}")
        self._selected = {
            label if label in self._available else self._lookup[label.casefold()]
            for label in self.selected_channels
        }
        self._active_preset = None
        self._missing_members: tuple[str, ...] = ()
        self._roi_settings_path = Path(roi_settings_path) if roi_settings_path is not None else ROI_SETTINGS_PATH
        self._saved_rois: dict[str, tuple[str, ...]] = {}
        self._roi_storage_error = ""
        self.map_widget = _ElectrodeMap(self._lookup)
        self.name_edit = QLineEdit(roi_name)
        self.name_edit.setPlaceholderText("Name this electrode or ROI")
        self.selection_label = QLabel()
        self.selection_label.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_label.setWordWrap(True)
        self.selection_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.missing_label = hint_label("")
        self.missing_label.setTextFormat(Qt.TextFormat.PlainText)
        self.save_button = QPushButton("Save Custom ROI")
        self.save_button.setAutoDefault(False)
        self.saved_combo = QComboBox()
        self.saved_combo.setToolTip("Choose a saved ROI to load its electrode selection.")
        self.roi_status_label = hint_label("")
        self.roi_status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.preset_buttons = {}
        self.other_list = QListWidget()
        self.other_list.setMaximumHeight(125)
        mapped = {self._lookup.get(label.casefold()) for label, _, _ in _ELECTRODES}
        for label in self._available:
            if label not in mapped:
                item = QListWidgetItem(label, self.other_list)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if label in self._selected else Qt.CheckState.Unchecked)
        self.clear_button = QPushButton("Clear")
        self.use_button = QPushButton("Use ROI")
        self.use_button.setProperty("uiRole", "primary")
        self.use_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.clear_button.setAutoDefault(False)
        self.cancel_button.setAutoDefault(False)
        self._build_layout()
        self.map_widget.selection_changed.connect(self._toggle_electrode)
        self.other_list.itemChanged.connect(lambda item: self._toggle_electrode(item.text(), item.checkState() == Qt.CheckState.Checked))
        self.name_edit.textChanged.connect(lambda _text: self._validate())
        self.save_button.clicked.connect(self._save_custom_roi)
        self.saved_combo.activated.connect(self._select_saved)
        self.clear_button.clicked.connect(self._clear)
        self.use_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        apply_launcher_style(self)
        try:
            self._saved_rois = load_custom_rois(self._roi_settings_path)
        except (OSError, ValueError) as exc:
            self._roi_storage_error = f"Could not load saved ROIs: {exc}"
            self.roi_status_label.setText(self._roi_storage_error)
        self._populate_saved_rois()
        self._refresh()
        screen = self.screen().availableGeometry()
        self.resize(min(1180, screen.width() - 48), min(850, screen.height() - 64))

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel("Choose electrodes or a region of interest")
        title.setProperty("uiRole", "sectionTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint_label("Select one electrode or several to define an ROI. Example ROIs can be a starting point."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        row = QBoxLayout(QBoxLayout.Direction.LeftToRight, content)
        self._content_row = row
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)
        row.addWidget(self.map_widget, 2)
        details = QWidget()
        self._details = details
        details.setMinimumWidth(290)
        details.setMaximumWidth(350)
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(0, 4, 10, 4)
        detail_layout.setSpacing(12)
        detail_layout.addWidget(QLabel("Electrode / ROI name"))
        detail_layout.addWidget(self.name_edit)
        detail_layout.addWidget(self.selection_label)
        detail_layout.addWidget(self.missing_label)
        detail_layout.addWidget(self.save_button)
        detail_layout.addWidget(QLabel("Saved custom ROIs"))
        detail_layout.addWidget(self.saved_combo)
        detail_layout.addWidget(self.roi_status_label)
        detail_layout.addWidget(QLabel("Example ROIs"))
        for key, (name, members, color) in _PRESETS.items():
            button = QPushButton(name)
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setEnabled(any(label.casefold() in self._lookup for label in members))
            button.setToolTip("Electrodes: " + ", ".join(members))
            button.setStyleSheet(f"QPushButton {{ border-left: 4px solid {color}; text-align: left; }} QPushButton:checked {{ border: 2px solid {color}; }}")
            button.clicked.connect(lambda _checked, preset=key: self._choose_preset(preset))
            self.preset_buttons[key] = button
            detail_layout.addWidget(button)
        detail_layout.addWidget(hint_label("FPVS example presets are not validated SSSEP ROIs. Follow your analysis plan."))
        other_label = QLabel("Other available electrodes")
        other_label.setVisible(self.other_list.count() > 0)
        self.other_list.setVisible(self.other_list.count() > 0)
        detail_layout.addWidget(other_label)
        detail_layout.addWidget(self.other_list)
        detail_layout.addStretch(1)
        row.addWidget(details, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        layout.addWidget(hint_label("Front is at the top; left is the participant's left. Grey electrodes are unavailable. Save Custom ROI keeps your definition for future sessions; Use ROI returns this selection to Settings."))
        footer = QHBoxLayout()
        footer.addWidget(self.clear_button)
        footer.addStretch(1)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.use_button)
        layout.addLayout(footer)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if not hasattr(self, "_content_row"):
            return
        narrow = self.width() < 1000
        self._content_row.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        )
        self._details.setMinimumWidth(0 if narrow else 290)
        self._details.setMaximumWidth(16777215 if narrow else 350)
        self.map_widget.setMaximumHeight(650 if narrow else 16777215)

    def _toggle_electrode(self, label: str, checked: bool) -> None:
        actual = label if label in self._available else self._lookup[label.casefold()]
        old_name = _PRESETS[self._active_preset][0] if self._active_preset else None
        self._selected.add(actual) if checked else self._selected.discard(actual)
        self._active_preset = None
        self._missing_members = ()
        self.saved_combo.setCurrentIndex(0)
        if len(self._selected) == 1 and (
            not self.name_edit.text().strip()
            or self.name_edit.text().strip() in self._available
            or self.name_edit.text() in (old_name, "Custom ROI")
        ):
            self.name_edit.setText(next(iter(self._selected)))
        elif self.name_edit.text().strip() in self._available or self.name_edit.text() == old_name:
            self.name_edit.setText("Custom ROI")
        self._refresh()

    def _choose_preset(self, key: str) -> None:
        name, members, _ = _PRESETS[key]
        self._active_preset = key
        self._selected = {self._lookup[label.casefold()] for label in members if label.casefold() in self._lookup}
        self._missing_members = tuple(label for label in members if label.casefold() not in self._lookup)
        self.saved_combo.setCurrentIndex(0)
        self.name_edit.setText(name)
        self._refresh()

    def _populate_saved_rois(self, selected_name: str | None = None) -> None:
        self.saved_combo.clear()
        self.saved_combo.addItem("Choose a saved ROI...", None)
        for name in self._saved_rois:
            self.saved_combo.addItem(name, name)
        if selected_name is not None:
            self.saved_combo.setCurrentIndex(self.saved_combo.findData(selected_name))
        self.saved_combo.setEnabled(bool(self._saved_rois))

    def _select_saved(self, index: int) -> None:
        name = self.saved_combo.itemData(index)
        if name is None:
            return
        members = self._saved_rois[name]
        self._selected = {
            label if label in self._available else self._lookup[label.casefold()]
            for label in members if label.casefold() in self._lookup
        }
        self._missing_members = tuple(label for label in members if label.casefold() not in self._lookup)
        self._active_preset = None
        self.name_edit.setText(name)
        self._refresh()

    def _save_custom_roi(self) -> None:
        """Save explicitly without applying the draft to the current plot."""
        if not self._selected or not self.name_edit.text().strip() or self._roi_storage_error:
            return
        name = self.name_edit.text().strip()
        channels = tuple(label for label in self._available if label in self._selected)
        try:
            current = load_custom_rois(self._roi_settings_path)
            previous = next((key for key in current if key.casefold() == name.casefold()), None)
            if previous is not None and current[previous] != channels:
                answer = QMessageBox.question(
                    self, "Replace Saved ROI?",
                    f'Replace the saved ROI "{previous}" with this electrode selection?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self._saved_rois = save_custom_roi(name, channels, self._roi_settings_path)
        except (OSError, ValueError) as exc:
            message = f"Could not save custom ROI: {exc}"
            self.roi_status_label.setText(message)
            QMessageBox.warning(self, "Could Not Save ROI", message)
            return
        self._populate_saved_rois(name)
        self.roi_status_label.setText(f'Saved "{name}" for future sessions.')

    def _clear(self) -> None:
        self._selected.clear()
        self._active_preset = None
        self._missing_members = ()
        self.saved_combo.setCurrentIndex(0)
        self.name_edit.clear()
        self._refresh()

    def _refresh(self) -> None:
        self.map_widget.set_selection(self._selected, self._active_preset)
        for key, button in self.preset_buttons.items():
            button.setChecked(key == self._active_preset)
        with QSignalBlocker(self.other_list):
            for index in range(self.other_list.count()):
                item = self.other_list.item(index)
                item.setCheckState(Qt.CheckState.Checked if item.text() in self._selected else Qt.CheckState.Unchecked)
        selected = [label for label in self._available if label in self._selected]
        self.selection_label.setText(f"{len(selected)} electrode(s) selected\n" + (", ".join(selected) or "Choose at least one electrode."))
        self.missing_label.setText(
            "Not available in this dataset: " + ", ".join(self._missing_members)
            if self._missing_members else ""
        )
        self.missing_label.setVisible(bool(self._missing_members))
        self._validate()

    def _validate(self) -> None:
        valid = bool(self._selected) and bool(self.name_edit.text().strip())
        self.use_button.setEnabled(valid)
        self.save_button.setEnabled(valid and not self._roi_storage_error)

    def accept(self) -> None:
        if not self._selected or not self.name_edit.text().strip():
            return
        self.selected_channels = tuple(label for label in self._available if label in self._selected)
        self.roi_name = self.name_edit.text().strip()
        super().accept()
