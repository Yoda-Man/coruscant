"""
coruscant.utils.logging_config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Application-wide logging initialisation.

Call ``setup_logging()`` once in main.py before any other coruscant
imports start using loggers.

Log file location
-----------------
  Windows : %APPDATA%\\Coruscant\\logs\\coruscant.log
  macOS   : ~/Library/Logs/Coruscant/coruscant.log
  Linux   : ~/.local/share/Coruscant/logs/coruscant.log

Up to 3 rotated files of 5 MB each are kept (15 MB max on disk).

Tuning the log level
--------------------
Set the environment variable before launching::

    set CORUSCANT_LOG_LEVEL=DEBUG   # Windows
    export CORUSCANT_LOG_LEVEL=DEBUG  # Linux / macOS

DEBUG captures full SQL text, row counts, and per-statement timing.
INFO  (default) captures connections, schema loads, and query summaries.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

_FMT        = "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-38s | %(message)s"
_DATE_FMT   = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES  = 5 * 1024 * 1024   # 5 MB per file
_BACKUPS    = 3                  # keep 3 rotated files → 15 MB max


def _log_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME",
                                   str(Path.home() / ".local" / "share")))
    return base / "Coruscant" / "logs"


def setup_logging() -> Path:
    """
    Configure the root logger.  Returns the path to the active log file.

    Safe to call more than once — subsequent calls are no-ops (handlers
    are only added when the root logger has none yet).
    """
    root = logging.getLogger()
    if root.handlers:
        return _log_dir() / "coruscant.log"   # already initialised

    level_name = os.environ.get("CORUSCANT_LOG_LEVEL", "INFO").upper()
    level      = getattr(logging, level_name, logging.INFO)

    log_dir  = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "coruscant.log"

    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # ── Rotating file handler (always DEBUG so the file captures everything) ─ #
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root.setLevel(level)
    root.addHandler(file_handler)

    # ── Console handler — only when a real TTY is attached ──────────────── #
    if sys.stderr and hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console.setLevel(level)
        root.addHandler(console)

    # Silence noisy third-party loggers
    logging.getLogger("psycopg2").setLevel(logging.WARNING)

    _install_excepthook(log_file)

    log = logging.getLogger(__name__)
    log.info("Logging initialised  level=%s  file=%s", level_name, log_file)
    return log_file


def _install_excepthook(log_file: Path) -> None:
    """
    Replace sys.excepthook so unhandled exceptions are logged with a full
    traceback before the process exits.  A user-facing dialog is shown when
    a Qt application is already running.
    """
    crash_log = logging.getLogger("coruscant.crash")

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        crash_log.critical(
            "Unhandled exception — application will close",
            exc_info=(exc_type, exc_value, exc_tb),
        )

        # Show a dialog when Qt is already running so the user is not left
        # wondering why the window disappeared.
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance():
                QMessageBox.critical(
                    None,
                    "Unexpected Error",
                    f"An unexpected error occurred and Coruscant must close.\n\n"
                    f"{exc_type.__name__}: {exc_value}\n\n"
                    f"Details have been saved to:\n{log_file}",
                )
        except Exception:
            pass  # never let the crash handler itself crash

        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
