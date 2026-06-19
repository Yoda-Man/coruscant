"""
coruscant.ui.dialogs.about
~~~~~~~~~~~~~~~~~~~~~~~~~~~
About dialog.

Opened from the Schema Browser's "About" button.  Shows the application
logo, version, author, licence, and the versions of the underlying runtime
(Python, PySide6, Qt) for support and bug-report purposes.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import PySide6
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextBrowser, QWidget, QApplication,
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, qVersion

from coruscant import __version__, __app_name__, __author__
from coruscant.ui import style
from coruscant.ui.style import dialog_stylesheet

# ── Logo resolution (same strategy as guide.py / app.py) ─────────────── #
_BASE = (
    Path(sys._MEIPASS)
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[3]
)
_ICON_PATH = str(_BASE / "docs" / "icon.png")

_REPO_URL = "https://github.com/Yoda-Man/coruscant"

# ── Stylesheet (shared design system — see coruscant.ui.style) ─────────── #
_DIALOG_STYLE = dialog_stylesheet()


def _about_html() -> str:
    """Build the About body, embedding live runtime versions."""
    py_ver = sys.version.split()[0]
    return f"""
    <div style="color:{style.TEXT}; line-height:1.6;">
      <p style="color:{style.TEXT_MUTED};">
        A lightweight, open-source desktop SQL IDE for PostgreSQL. Run multiple
        statements in one pass, with each <code>SELECT</code> getting its own
        persistent result tab. Browse your schema, manage transactions,
        search your script library, and export results, all in one window.
      </p>

      <p style="color:{style.TEXT_DIM}; font-style:italic; margin-top:4px;">
        Named after the galactic capital of Star Wars, a city-planet that is
        essentially one giant information hub.
      </p>

      <table cellspacing="0" cellpadding="4" style="margin-top:10px;">
        <tr><td style="color:{style.ACCENT_BLUE};">Version</td>
            <td style="color:{style.TEXT};">{__version__}</td></tr>
        <tr><td style="color:{style.ACCENT_BLUE};">Author</td>
            <td style="color:{style.TEXT};">{__author__}</td></tr>
        <tr><td style="color:{style.ACCENT_BLUE};">Licence</td>
            <td style="color:{style.TEXT};">MIT</td></tr>
        <tr><td style="color:{style.ACCENT_BLUE};">Project</td>
            <td><a style="color:{style.ACCENT_BLUE_LT};" href="{_REPO_URL}">{_REPO_URL}</a></td></tr>
      </table>

      <p style="color:{style.TEXT_FAINT}; font-size:11px; margin-top:12px;">
        Python {py_ver} &nbsp;·&nbsp; PySide6 {PySide6.__version__}
        &nbsp;·&nbsp; Qt {qVersion()}<br>
        {platform.system()} {platform.release()} ({platform.machine()})
      </p>

      <p style="color:{style.TEXT_FAINT}; font-size:11px;">
        © 2026 {__author__}. Released under the MIT Licence.
      </p>
    </div>
    """


class AboutDialog(QDialog):
    """
    Modal About dialog.

    Mirrors the Quick Reference Guide's visual style: a logo header with the
    app name and version, followed by a styled HTML body describing the
    application, its licence, and the runtime environment.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {__app_name__}")
        self.resize(540, 480)
        self.setStyleSheet(_DIALOG_STYLE)
        self.setModal(True)
        self._build_ui()

    # ── Construction ─────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())

        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setHtml(_about_html())
        body.verticalScrollBar().setValue(0)
        layout.addWidget(body)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _build_header(self) -> QWidget:
        """Logo + app name + version row — matches the Guide dialog header."""
        container = QWidget()
        container.setStyleSheet(
            "QWidget { background: #1a1a2e; border-radius: 8px; }"
        )
        row = QHBoxLayout(container)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(14)

        logo_lbl = QLabel()
        pixmap = QPixmap(_ICON_PATH)
        if not pixmap.isNull():
            logo_lbl.setPixmap(pixmap.scaled(
                52, 52,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            logo_lbl.setText("✦")
            logo_lbl.setStyleSheet("font-size: 32px; color: #89b4fa;")
        logo_lbl.setFixedSize(52, 52)
        row.addWidget(logo_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title = QLabel(__app_name__)
        title.setObjectName("title_label")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)
        title.setStyleSheet("color: #cdd6f4;")
        text_col.addWidget(title)

        subtitle = QLabel(f"v{__version__}  ·  PostgreSQL multi-query client")
        subtitle.setObjectName("subtitle_label")
        subtitle.setStyleSheet("color: #8888aa; font-size: 11px;")
        text_col.addWidget(subtitle)

        row.addLayout(text_col)
        row.addStretch()
        return container
