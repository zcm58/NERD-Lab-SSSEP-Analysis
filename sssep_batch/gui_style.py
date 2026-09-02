"""Small launcher-only layout and theme helpers inspired by FPVS Studio.

Visual reference: FPVS-Studio-2.0 at f3073347bad0afeca8c9a6b6a1a988a3ce96fc9c,
``gui/design_system.py`` and ``gui/components.py``. No runtime code is shared.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class SectionCard(QFrame):
    """A named settings group with a short optional explanation."""

    def __init__(
        self, title: str, subtitle: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setProperty("uiRole", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        label = QLabel(title, self)
        label.setProperty("uiRole", "sectionTitle")
        label.setWordWrap(True)
        layout.addWidget(label)
        if subtitle:
            layout.addWidget(hint_label(subtitle))
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        layout.addLayout(self.body)


def make_form() -> QFormLayout:
    """Keep form fields aligned while allowing long rows to wrap."""
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(10)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return form


def hint_label(text: str) -> QLabel:
    """Create a wrapping secondary label without changing its meaning."""
    label = QLabel(text)
    label.setProperty("uiRole", "muted")
    label.setWordWrap(True)
    return label


def build_page(widget: QWidget) -> tuple[QVBoxLayout, QHBoxLayout]:
    """Separate scrollable settings from always-visible actions and status."""
    outer = QVBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    scroll = QScrollArea(widget)
    scroll.setObjectName("pageScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    content.setObjectName("pageBody")
    body = QVBoxLayout(content)
    body.setContentsMargins(24, 18, 24, 18)
    body.setSpacing(12)
    body.setAlignment(Qt.AlignmentFlag.AlignTop)
    scroll.setWidget(content)
    outer.addWidget(scroll, 1)
    footer_frame = QFrame(widget)
    footer_frame.setProperty("uiRole", "footer")
    footer_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    footer = QHBoxLayout(footer_frame)
    footer.setContentsMargins(24, 12, 24, 12)
    footer.setSpacing(12)
    outer.addWidget(footer_frame)
    return body, footer


def apply_launcher_style(window: QWidget) -> None:
    """Use the system light/dark scheme, scoped away from participant screens."""
    dark = window.palette().color(QPalette.ColorRole.Window).lightness() < 128
    if dark:
        page, surface, elevated, alternate = "#202124", "#24272d", "#30343b", "#2d333b"
        border, soft, text, muted = "#566170", "#3f4854", "#f3f6fb", "#aeb8c7"
        blue, hover, selected = "#60a5fa", "#93c5fd", "#07111f"
        disabled, disabled_bg = "#727d8c", "#2b3139"
    else:
        page, surface, elevated, alternate = "#f4f7fb", "#f8fafc", "#ffffff", "#eef3f9"
        border, soft, text, muted = "#c7d0dd", "#d7dfea", "#1f2f44", "#455a72"
        blue, hover, selected = "#2563eb", "#1d4ed8", "#ffffff"
        disabled, disabled_bg = "#8a97a8", "#eef3f9"
    window.setObjectName("sssepLauncher")
    window.setStyleSheet(f"""
        QWidget {{
            font-size: 13px; color: {text};
        }}
        QWidget#sssepLauncher, QWidget#pageBody, QScrollArea#pageScrollArea {{
            background: {page};
        }}
        QFrame[uiRole="card"] {{
            background: {surface}; border: 1px solid {border}; border-radius: 10px;
        }}
        QFrame[uiRole="footer"] {{
            background: {surface}; border-top: 1px solid {soft};
        }}
        QLabel[uiRole="title"] {{ font-size: 24px; font-weight: 700; }}
        QLabel[uiRole="sectionTitle"] {{ font-size: 16px; font-weight: 700; }}
        QLabel[uiRole="muted"] {{ color: {muted}; }}
        QMenuBar {{ background: {page}; padding: 2px 0; }}
        QMenuBar::item {{ padding: 6px 10px; border-radius: 4px; }}
        QMenuBar::item:selected, QMenu::item:selected {{ background: {alternate}; }}
        QMenu {{ background: {surface}; border: 1px solid {border}; padding: 4px; }}
        QMenu::item {{ padding: 7px 24px; }}
        QMenu::item:disabled {{ color: {disabled}; }}
        QTabWidget::pane {{ border: none; background: {page}; }}
        QTabBar::tab {{
            padding: 10px 18px; margin-right: 4px; color: {muted};
            border: none; border-bottom: 3px solid transparent;
        }}
        QTabBar::tab:selected {{ color: {blue}; border-bottom-color: {blue}; font-weight: 700; }}
        QTabBar::tab:hover {{ background: {alternate}; }}
        QTabBar::tab:disabled {{ color: {disabled}; }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {{
            border: 1px solid {border}; border-radius: 6px;
            background: {elevated}; padding: 5px 8px;
            selection-background-color: {blue}; selection-color: {selected};
        }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ min-height: 22px; }}
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
        QListWidget:focus {{ border-color: {blue}; }}
        QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
        QComboBox:disabled, QListWidget:disabled {{
            color: {disabled}; background: {disabled_bg}; border-color: {soft};
        }}
        QComboBox QAbstractItemView {{
            background: {elevated}; color: {text};
            selection-background-color: {blue}; selection-color: {selected};
        }}
        QListWidget::item {{ padding: 4px 6px; border-radius: 4px; }}
        QListWidget::item:selected {{ background: {blue}; color: {selected}; }}
        QPushButton {{
            background: {elevated}; border: 1px solid {border}; border-radius: 10px;
            padding: 6px 12px; min-height: 24px;
        }}
        QPushButton:hover {{ background: {alternate}; border-color: {blue}; }}
        QPushButton:pressed {{ background: {alternate}; }}
        QPushButton:focus {{ border: 2px solid {blue}; }}
        QPushButton[uiRole="primary"] {{
            background: {blue}; border-color: {blue}; color: {selected}; font-weight: 700;
        }}
        QPushButton[uiRole="primary"]:hover {{ background: {hover}; }}
        QPushButton:disabled, QPushButton[uiRole="primary"]:disabled {{
            background: {disabled_bg}; color: {disabled}; border-color: {soft};
        }}
        QCheckBox {{ spacing: 8px; }}
        QCheckBox:disabled, QLabel:disabled {{ color: {disabled}; }}
        QToolTip {{ background: {elevated}; color: {text}; border: 1px solid {border}; }}
    """)
