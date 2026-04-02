"""
coruscant.core.worker
~~~~~~~~~~~~~~~~~~~~~
Background QThread that runs DatabaseManager.execute() off the GUI thread.

Signals
-------
finished(list)  – list of StatementResult on success
error(str)      – formatted error message on failure
cancelled()     – query was cancelled by the user (SQLSTATE 57014)

Logging
-------
DEBUG   : worker started and finished (result count).
WARNING : query cancelled by user.
ERROR   : unexpected non-database exceptions (database errors are already
          logged by DatabaseManager before being re-raised here).

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import logging

import psycopg2

from PySide6.QtCore import QThread, Signal

from coruscant.core.database import DatabaseManager, PGCODE_QUERY_CANCELED

log = logging.getLogger(__name__)


class QueryWorker(QThread):
    """Executes a SQL string in a background thread."""

    finished:  Signal = Signal(list)
    error:     Signal = Signal(str)
    cancelled: Signal = Signal()

    def __init__(
        self,
        db: DatabaseManager,
        sql: str,
        row_limit: int = 0,
        params: dict | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db        = db
        self._sql       = sql
        self._row_limit = row_limit
        self._params    = params or None

    def run(self) -> None:
        log.debug("QueryWorker started")
        try:
            results = self._db.execute(
                self._sql,
                row_limit=self._row_limit,
                params=self._params,
            )
            log.debug("QueryWorker finished  results=%d", len(results))
            self.finished.emit(results)

        except psycopg2.Error as exc:
            if getattr(exc, "pgcode", None) == PGCODE_QUERY_CANCELED:
                log.warning("Query cancelled by user")
                self.cancelled.emit()
                return

            stmt   = getattr(exc, "statement", "")
            detail = str(exc).strip()
            msg    = f"Database error:\n\n{detail}"
            if stmt:
                msg += f"\n\nFailed statement:\n{stmt}"
            # database.py already logged the error; emit for the UI
            self.error.emit(msg)

        except Exception as exc:
            log.exception("Unexpected error in QueryWorker")
            self.error.emit(str(exc))
