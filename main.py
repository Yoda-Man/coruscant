"""
Coruscant — PostgreSQL Multi-Query Tool
========================================
Author:  Marwa Trust Mutemasango
Version: 1.0.3

Usage
-----
    pip install pyside6 psycopg2-binary sqlparse
    python main.py

Log file (written on every run):
    Windows : %APPDATA%\\Coruscant\\logs\\coruscant.log
    macOS   : ~/Library/Logs/Coruscant/coruscant.log
    Linux   : ~/.local/share/Coruscant/logs/coruscant.log

Set CORUSCANT_LOG_LEVEL=DEBUG for verbose SQL and timing output.
"""

from __future__ import annotations

import sys

from coruscant.utils.logging_config import setup_logging

setup_logging()   # must be first — before any other coruscant import

from coruscant.app import create_app
from coruscant.ui.main_window import MainWindow


def _splash_text(message: str) -> None:
    """Update the PyInstaller boot-splash caption, if a splash is showing.

    ``pyi_splash`` only exists inside a frozen Windows/Linux build that was
    bundled with a Splash screen. In dev runs, and in the macOS .app bundle
    (where Splash is unsupported), the import fails and this is a no-op.
    """
    try:
        import pyi_splash  # type: ignore
    except ImportError:
        return
    try:
        pyi_splash.update_text(message)
    except Exception:
        pass


def _close_splash() -> None:
    """Close the PyInstaller boot splash, if one is showing."""
    try:
        import pyi_splash  # type: ignore
    except ImportError:
        return
    try:
        pyi_splash.close()
    except Exception:
        pass


def main() -> None:
    _splash_text("Loading interface…")
    app    = create_app()
    _splash_text("Restoring your session…")
    window = MainWindow()
    window.show()
    _close_splash()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
