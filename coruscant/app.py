"""
coruscant.app
~~~~~~~~~~~~~
Application factory — creates and configures the QApplication.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from coruscant import __version__, __app_name__
import coruscant.utils.themes as themes

_SETTINGS_ORG = "Coruscant"
_SETTINGS_APP = "Coruscant"


def create_app() -> QApplication:
    """Create, style, and return the QApplication instance."""
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(_SETTINGS_ORG)
    app.setStyle("Fusion")

    settings    = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    saved_theme = themes.current_theme(settings)

    if saved_theme == "light":
        themes.apply_light(app)
    else:
        themes.apply_dark(app)

    return app
