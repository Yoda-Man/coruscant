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
from typing import Callable
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


#: Optional presenter for unhandled exceptions, registered by the UI layer.
#:
#: Logging must work before any GUI exists, and utils sits below ui, so this
#: module cannot import a dialog. The UI supplies one via set_crash_reporter();
#: when nothing is registered the crash is still logged, just not shown.
_crash_reporter: Callable[[str, str], None] | None = None


def set_crash_reporter(fn: Callable[[str, str], None] | None) -> None:
    """Register a callable taking (title, html_body) to display a crash."""
    global _crash_reporter
    _crash_reporter = fn


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

        # Tell the user, if a presenter has been registered. utils must not
        # import from ui — the UI registers a callback instead (see
        # set_crash_reporter and coruscant.app), so the dependency points
        # inward like every other one in the codebase.
        try:
            import traceback

            if _crash_reporter is not None:
                tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                body   = (
                    f"An unexpected error occurred and Coruscant must close.<br><br>"
                    f"<b>{exc_type.__name__}:</b> {exc_value}<br><br>"
                    f"Details have been saved to:<br/><code>{log_file}</code><br><br>"
                    f"<b>Traceback:</b><br/>"
                    f"<pre style='font-family: monospace; font-size: 11px;'>{tb_str}</pre>"
                )
                _crash_reporter("Unexpected Error", body)
        except Exception:
            pass  # never let the crash handler itself crash

        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
