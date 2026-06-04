"""
Tests for coruscant.core.worker.QueryWorker.

PySide6 and psycopg2 are both mocked at the module level — no Qt event
loop and no database driver are required.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Stub PySide6 and psycopg2 before importing worker
# ---------------------------------------------------------------------------

def _stub_pyside6():
    for name in list(sys.modules):
        if name.startswith("PySide6"):
            del sys.modules[name]

    pyside6     = types.ModuleType("PySide6")
    core        = types.ModuleType("PySide6.QtCore")

    class _Signal:
        """Minimal Signal replacement that supports .emit() and .connect()."""
        def __init__(self, *types_):
            self._handlers = []
        def connect(self, fn):
            self._handlers.append(fn)
        def emit(self, *args):
            for h in self._handlers:
                h(*args)

    class _QThread:
        """Minimal QThread: just run() + start()."""
        def __init__(self, parent=None):
            pass
        def start(self):
            self.run()
        def run(self):
            pass

    core.QThread  = _QThread
    core.Signal   = _Signal
    pyside6.QtCore = core
    sys.modules["PySide6"]        = pyside6
    sys.modules["PySide6.QtCore"] = core
    return core

_qt = _stub_pyside6()


def _stub_psycopg2():
    import types as _t
    mod = _t.ModuleType("psycopg2")
    class _Err(Exception):
        pgcode = None
        statement = None
    class _OpErr(_Err): pass
    mod.Error = _Err
    mod.OperationalError = _OpErr
    exts = _t.ModuleType("psycopg2.extensions")
    extras = _t.ModuleType("psycopg2.extras")
    mod.extensions = exts
    mod.extras = extras
    sys.modules.setdefault("psycopg2",            mod)
    sys.modules.setdefault("psycopg2.extensions", exts)
    sys.modules.setdefault("psycopg2.extras",     extras)
    return mod

_psycopg2 = _stub_psycopg2()

# Now safe to import
from coruscant.core.worker import QueryWorker          # noqa: E402
from coruscant.core.database import DatabaseManager, QueryResult, CommandResult  # noqa: E402
PGCODE_QUERY_CANCELED = "57014"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_worker(sql="SELECT 1", row_limit=0, params=None):
    db = MagicMock(spec=DatabaseManager)
    w = QueryWorker(db, sql, row_limit=row_limit, params=params)
    return w, db


def _result(label="Q1"):
    return QueryResult(label, ["id"], [(1,)], 5.0, False)


def _get_psycopg2_error():
    """Return the psycopg2.Error that worker.py actually imports — safe across test orderings."""
    import sys
    return sys.modules["psycopg2"].Error


def _make_exc(msg="err", pgcode="00000", statement=""):
    """Construct a psycopg2.Error compatible with whichever stub is active."""
    ErrCls = _get_psycopg2_error()
    exc = ErrCls(msg)
    exc.pgcode = pgcode
    exc.statement = statement
    return exc


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestQueryWorkerConstruction:
    def test_stores_sql(self):
        w, _ = _make_worker("SELECT 42")
        assert w._sql == "SELECT 42"

    def test_stores_row_limit(self):
        w, _ = _make_worker(row_limit=100)
        assert w._row_limit == 100

    def test_stores_params(self):
        p = {"id": 1}
        w, _ = _make_worker(params=p)
        assert w._params == p

    def test_params_none_stays_none(self):
        w, _ = _make_worker(params=None)
        assert w._params is None

    def test_empty_dict_params_normalised_to_none(self):
        # {} is falsy — worker stores None
        w, _ = _make_worker(params={})
        assert w._params is None


# ---------------------------------------------------------------------------
# run() — success path
# ---------------------------------------------------------------------------

class TestQueryWorkerRunSuccess:
    def test_finished_emitted_with_results(self):
        w, db = _make_worker()
        results = [_result()]
        db.execute.return_value = results

        received = []
        w.finished.connect(lambda r: received.extend(r))
        w.run()

        assert received == results

    def test_error_not_emitted_on_success(self):
        w, db = _make_worker()
        db.execute.return_value = [_result()]

        errors = []
        w.error.connect(errors.append)
        w.run()
        assert errors == []

    def test_db_execute_called_with_correct_args(self):
        w, db = _make_worker("SELECT 1", row_limit=50, params={"x": 1})
        db.execute.return_value = []
        w.run()
        db.execute.assert_called_once_with("SELECT 1", row_limit=50, params={"x": 1})

    def test_multiple_results_all_emitted(self):
        w, db = _make_worker("SELECT 1; SELECT 2;")
        results = [_result("Q1"), _result("Q2")]
        db.execute.return_value = results

        received = []
        w.finished.connect(received.extend)
        w.run()
        assert len(received) == 2


# ---------------------------------------------------------------------------
# run() — cancelled path (SQLSTATE 57014)
# ---------------------------------------------------------------------------

class TestQueryWorkerRunCancelled:
    def test_cancelled_emitted_on_57014(self):
        w, db = _make_worker()
        exc = _make_exc("cancel", pgcode=PGCODE_QUERY_CANCELED)
        db.execute.side_effect = exc

        fired = []
        w.cancelled.connect(lambda: fired.append(True))
        w.run()
        assert fired == [True]

    def test_error_not_emitted_on_cancel(self):
        w, db = _make_worker()
        exc = _make_exc("cancel", pgcode=PGCODE_QUERY_CANCELED)
        db.execute.side_effect = exc

        errors = []
        w.error.connect(errors.append)
        w.run()
        assert errors == []

    def test_finished_not_emitted_on_cancel(self):
        w, db = _make_worker()
        exc = _make_exc("cancel", pgcode=PGCODE_QUERY_CANCELED)
        db.execute.side_effect = exc

        finished = []
        w.finished.connect(finished.extend)
        w.run()
        assert finished == []


# ---------------------------------------------------------------------------
# run() — database error path
# ---------------------------------------------------------------------------

class TestQueryWorkerRunDbError:
    def test_error_emitted_on_db_error(self):
        w, db = _make_worker()
        exc = _make_exc("syntax error", pgcode="42601", statement="SELECT bad")
        db.execute.side_effect = exc

        errors = []
        w.error.connect(errors.append)
        w.run()
        assert len(errors) == 1

    def test_error_message_contains_detail(self):
        w, db = _make_worker()
        exc = _make_exc("column does not exist", pgcode="42703")
        db.execute.side_effect = exc

        errors = []
        w.error.connect(errors.append)
        w.run()
        assert "column does not exist" in errors[0]

    def test_error_message_contains_failed_statement(self):
        w, db = _make_worker()
        exc = _make_exc("err", pgcode="42601", statement="SELECT bad_col")
        db.execute.side_effect = exc

        errors = []
        w.error.connect(errors.append)
        w.run()
        assert "SELECT bad_col" in errors[0]

    def test_finished_not_emitted_on_db_error(self):
        w, db = _make_worker()
        exc = _make_exc("err", pgcode="42601")
        db.execute.side_effect = exc

        finished = []
        w.finished.connect(finished.extend)
        w.run()
        assert finished == []

    def test_cancelled_not_emitted_on_db_error(self):
        w, db = _make_worker()
        exc = _make_exc("err", pgcode="00000")
        db.execute.side_effect = exc

        cancelled = []
        w.cancelled.connect(lambda: cancelled.append(True))
        w.run()
        assert cancelled == []


# ---------------------------------------------------------------------------
# run() — unexpected (non-psycopg2) error
# ---------------------------------------------------------------------------

class TestQueryWorkerRunUnexpectedError:
    def test_error_emitted_on_generic_exception(self):
        w, db = _make_worker()
        db.execute.side_effect = RuntimeError("totally unexpected")

        errors = []
        w.error.connect(errors.append)
        w.run()
        assert len(errors) == 1
        assert "totally unexpected" in errors[0]

    def test_finished_not_emitted_on_generic_exception(self):
        w, db = _make_worker()
        db.execute.side_effect = ValueError("bad value")

        finished = []
        w.finished.connect(finished.extend)
        w.run()
        assert finished == []
