"""
coruscant.ui.dialogs.message
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Premium styled message dialogs — drop-in replacements for QMessageBox.

Each dialog shows the Coruscant banner image, a colour-coded header strip
that reflects the severity, and the message body, keeping the same dark
aesthetic as the connection dialog.

Usage (identical surface to QMessageBox):
    StyledMessageBox.information(parent, "Title", "text")
    StyledMessageBox.warning(parent, "Title", "text")
    StyledMessageBox.critical(parent, "Title", "text")

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QFont

_BANNER_PATH = str(Path(__file__).resolve().parents[3] / "docs" / "coruscant3.png")

# Severity constants
_INFO     = "info"
_WARNING  = "warning"
_CRITICAL = "critical"

_SEVERITY_META = {
    _INFO:     {"icon": "✔", "label": "Information",
                "strip_bg": "#0a2a0a", "strip_border": "#2E7D32",
                "icon_color": "#66BB6A", "title_color": "#A5D6A7"},
    _WARNING:  {"icon": "⚠", "label": "Warning",
                "strip_bg": "#2a1a00", "strip_border": "#E65100",
                "icon_color": "#FFA726", "title_color": "#FFCC80"},
    _CRITICAL: {"icon": "✕", "label": "Error",
                "strip_bg": "#2a0a0a", "strip_border": "#C62828",
                "icon_color": "#EF5350", "title_color": "#FFCDD2"},
}

_DIALOG_STYLE = """
    QDialog {
        background: #12121e;
    }
    QScrollArea {
        border: none;
        background: transparent;
    }
    QWidget#body {
        background: transparent;
    }
    QLabel#message {
        color: #cdd6f4;
        font-size: 13px;
        line-height: 1.5;
        background: transparent;
    }
    QPushButton#ok_btn {
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 #3c3c52, stop:1 #2e2e42);
        border: 1px solid #555570;
        border-radius: 5px;
        padding: 7px 32px;
        color: #ddd;
        font-size: 12px;
        font-weight: 600;
        min-width: 80px;
    }
    QPushButton#ok_btn:hover {
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 #4a4a62, stop:1 #3c3c52);
        border-color: #7070a0;
        color: #fff;
    }
    QPushButton#ok_btn:pressed {
        background: #4361ee;
        border-color: #4361ee;
        color: #fff;
    }
"""


class StyledMessageBox(QDialog):
    """
    A branded, dark-themed message dialog.

    Do not instantiate directly — use the class-method shortcuts:
        StyledMessageBox.information(parent, title, text)
        StyledMessageBox.warning(parent, title, text)
        StyledMessageBox.critical(parent, title, text)
    """

    def __init__(self, parent, title: str, text: str, severity: str) -> None:
        super().__init__(parent)
        meta = _SEVERITY_META.get(severity, _SEVERITY_META[_INFO])

        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.setMaximumWidth(620)
        self.setModal(True)
        self.setStyleSheet(_DIALOG_STYLE)

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Banner ────────────────────────────────────────────────────── #
        banner = QLabel()
        banner.setFixedHeight(100)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet("background: #0d0d1a;")
        pixmap = QPixmap(_BANNER_PATH)
        if not pixmap.isNull():
            banner.setPixmap(
                pixmap.scaledToHeight(100, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            banner.setText("✦  Coruscant  ✦")
            f = QFont(); f.setPointSize(16); f.setBold(True)
            banner.setFont(f)
            banner.setStyleSheet("background: #0d0d1a; color: #89b4fa;")
        root.addWidget(banner)

        # ── Colour-coded header strip ─────────────────────────────────── #
        strip = QWidget()
        strip.setFixedHeight(44)
        strip.setStyleSheet(
            f"background: {meta['strip_bg']};"
            f"border-top: 1px solid {meta['strip_border']};"
            f"border-bottom: 1px solid {meta['strip_border']};"
        )
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(16, 0, 16, 0)
        strip_layout.setSpacing(10)

        icon_lbl = QLabel(meta["icon"])
        icon_lbl.setStyleSheet(
            f"color: {meta['icon_color']}; font-size: 18px; background: transparent;"
        )
        strip_layout.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {meta['title_color']}; font-size: 13px;"
            f"font-weight: 700; letter-spacing: 0.5px; background: transparent;"
        )
        strip_layout.addWidget(title_lbl)
        strip_layout.addStretch()
        root.addWidget(strip)

        # ── Scrollable message body ───────────────────────────────────── #
        body_widget = QWidget()
        body_widget.setObjectName("body")
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(20, 16, 20, 16)

        msg_lbl = QLabel(text)
        msg_lbl.setObjectName("message")
        msg_lbl.setWordWrap(True)
        msg_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        body_layout.addWidget(msg_lbl)

        scroll = QScrollArea()
        scroll.setObjectName("body")
        scroll.setWidget(body_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMaximumHeight(220)
        root.addWidget(scroll)

        # ── Divider ───────────────────────────────────────────────────── #
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #252535;")
        root.addWidget(divider)

        # ── Footer with OK button ─────────────────────────────────────── #
        footer = QWidget()
        footer.setStyleSheet("background: #0e0e1c;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 12)
        footer_layout.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("ok_btn")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        footer_layout.addWidget(ok_btn)
        root.addWidget(footer)

    # ── Static convenience methods (QMessageBox drop-in) ─────────────── #

    @staticmethod
    def information(parent, title: str, text: str) -> None:
        StyledMessageBox(parent, title, text, _INFO).exec()

    @staticmethod
    def warning(parent, title: str, text: str) -> None:
        StyledMessageBox(parent, title, text, _WARNING).exec()

    @staticmethod
    def critical(parent, title: str, text: str) -> None:
        StyledMessageBox(parent, title, text, _CRITICAL).exec()
