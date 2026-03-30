"""
Coruscant — PostgreSQL Multi-Query Tool
========================================
Author:  Marwa Trust Mutemasango
Version: 0.9.0

Usage
-----
    pip install pyside6 psycopg2-binary sqlparse
    python main.py
"""

from __future__ import annotations

import sys

from coruscant.app import create_app
from coruscant.ui.main_window import MainWindow


def main() -> None:
    app    = create_app()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
