"""
Coruscant — PostgreSQL Multi-Query Tool
========================================
Author:  Marwa Trust Mutemasango
Version: 0.9.2

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


def main() -> None:
    app    = create_app()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
