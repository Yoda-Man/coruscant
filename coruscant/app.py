"""
coruscant.app
~~~~~~~~~~~~~
Application factory — creates and configures the QApplication.

Responsibilities
----------------
- Create the QApplication with Fusion style.
- Apply the persisted theme (dark by default).
- Install a Qt message handler that routes Qt's internal warnings and
  errors into the Python logging system.
- Log a startup environment snapshot (Python, PySide6, Qt, OS versions).

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import logging
import platform
import sys

import PySide6
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings, qVersion
from PySide6.QtCore import QtMsgType, qInstallMessageHandler

from coruscant import __version__, __app_name__
import coruscant.utils.themes as themes

log = logging.getLogger(__name__)
_qt_log = logging.getLogger("Qt")


def _qt_message_handler(msg_type: QtMsgType, _context, message: str) -> None:
    """Route Qt's own diagnostic messages into the Python log."""
    if msg_type == QtMsgType.QtDebugMsg:
        _qt_log.debug("%s", message)
    elif msg_type == QtMsgType.QtInfoMsg:
        _qt_log.info("%s", message)
    elif msg_type == QtMsgType.QtWarningMsg:
        _qt_log.warning("%s", message)
    elif msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        _qt_log.error("%s", message)

_SETTINGS_ORG = "Coruscant"
_SETTINGS_APP = "Coruscant"


def create_app() -> QApplication:
    """Create, style, and return the QApplication instance."""
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(_SETTINGS_ORG)
    app.setStyle("Fusion")

    qInstallMessageHandler(_qt_message_handler)

    settings    = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    saved_theme = themes.current_theme(settings)

    log.info(
        "Starting %s v%s  theme=%s  Python=%s  PySide6=%s  Qt=%s  OS=%s %s %s",
        __app_name__, __version__, saved_theme,
        sys.version.split()[0],
        PySide6.__version__,
        qVersion(),
        platform.system(), platform.release(), platform.machine(),
    )

    if saved_theme == "light":
        themes.apply_light(app)
    else:
        themes.apply_dark(app)

    log.debug("Theme applied: %s", saved_theme)
    return app
