"""
Tests for coruscant.core.database.

psycopg2 is mocked at import time so no PostgreSQL installation is needed.
All tests use unittest.mock — no live DB connections.
"""
from __future__ import annotations

import sys
import types
from itertools import count
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest


# ---------------------------------------------------------------------------
# Bootstrap: stub out psycopg2 before coruscant.core.database is imported
# ---------------------------------------------------------------------------

def _make_psycopg2_stub():
    mod = types.ModuleType("psycopg2")
    mod.connect = MagicMock()

    class _Err(Exception):
        pgcode = None
        statement = None
    class _OpErr(_Err): pass
    class _IfErr(_Err): pass
    class _DbErr(_Err): pass

    mod.Error              = _Err
    mod.OperationalError   = _OpErr
    mod.InterfaceError     = _IfErr
    mod.DatabaseError      = _DbErr

    extras = types.ModuleType("psycopg2.extras")
    exts   = types.ModuleType("psycopg2.extensions")
    exts.STATUS_IN_TRANSACTION = 1

    mod.extras     = extras
    mod.extensions = exts
    sys.modules.setdefault("psycopg2",            mod)
    sys.modules.setdefault("psycopg2.extras",     extras)
    sys.modules.setdefault("psycopg2.extensions", exts)
    return mod

_psycopg2 = _make_psycopg2_stub()

from coruscant.core.database import (   # noqa: E402  (import after stub)
    DatabaseManager,
    QueryResult,
    CommandResult,
    PGCODE_QUERY_CANCELED,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _mock_col(name: str) -> MagicMock:
    col = MagicMock()
    col.name = name
    return col


def _make_connected_db(
    description=None,
    fetchall_return=None,
    fetchmany_return=None,
    fetchone_return=None,
    rowcount: int = -1,
    autocommit: bool = True,
):
    """
    Return (db, mock_conn, mock_cursor) where db._conn is already set.

    The first cursor() call (zombie-detection ping) returns ping_cursor.
    Every subsequent call returns mock_cursor.
    """
    db = DatabaseManager()

    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.description = description
    mock_cursor.fetchall.return_value = fetchall_return or []
    mock_cursor.fetchmany.return_value = fetchmany_return or []
    mock_cursor.fetchone.return_value = fetchone_return
    mock_cursor.rowcount = rowcount

    ping_cursor = MagicMock()
    ping_cursor.__enter__ = MagicMock(return_value=ping_cursor)
    ping_cursor.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.closed = 0    # psycopg2 uses int 0 = open, != 0 = closed
    mock_conn.autocommit = autocommit
    mock_conn.encoding = "utf-8"
    mock_conn.status = 1   # STATUS_IN_TRANSACTION

    _calls = count()
    mock_conn.cursor.side_effect = lambda: (
        ping_cursor if next(_calls) == 0 else mock_cursor
    )

    db._conn = mock_conn
    return db, mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class TestQueryResult:
    def test_all_attributes(self):
        qr = QueryResult("Q1", ["id", "name"], [(1, "Alice")], 12.5, False)
        assert qr.label      == "Q1"
        assert qr.columns    == ["id", "name"]
        assert qr.rows       == [(1, "Alice")]
        assert qr.elapsed_ms == 12.5
        assert qr.truncated  is False

    def test_truncated_flag_true(self):
        qr = QueryResult("Q", ["x"], [], 0.0, True)
        assert qr.truncated is True

    def test_slots_prevent_extra_attrs(self):
        qr = QueryResult("Q", [], [], 0.0)
        with pytest.raises(AttributeError):
            qr.nonexistent = 1


class TestCommandResult:
    def test_all_attributes(self):
        cr = CommandResult("Q2", "Rows affected: 7", 3.0)
        assert cr.label      == "Q2"
        assert cr.message    == "Rows affected: 7"
        assert cr.elapsed_ms == 3.0

    def test_slots_prevent_extra_attrs(self):
        cr = CommandResult("Q", "ok", 1.0)
        with pytest.raises(AttributeError):
            cr.extra = 1


class TestConstant:
    def test_pgcode_query_canceled(self):
        assert PGCODE_QUERY_CANCELED == "57014"


# ---------------------------------------------------------------------------
# is_connected
# ---------------------------------------------------------------------------

class TestIsConnected:
    def test_false_when_no_connection(self):
        db = DatabaseManager()
        assert db.is_connected is False

    def test_true_when_conn_open(self):
        db, mock_conn, _ = _make_connected_db()
        assert db.is_connected is True

    def test_false_when_conn_closed_int(self):
        db = DatabaseManager()
        mc = MagicMock()
        mc.closed = 1   # psycopg2 closed > 0 means closed
        db._conn = mc
        assert db.is_connected is False

    def test_false_after_disconnect(self):
        db, _, _ = _make_connected_db()
        db.disconnect()
        assert db.is_connected is False


# ---------------------------------------------------------------------------
# has_last_params
# ---------------------------------------------------------------------------

class TestHasLastParams:
    def test_false_initially(self):
        db = DatabaseManager()
        assert db.has_last_params is False

    def test_true_after_successful_connect(self):
        db = DatabaseManager()
        mc = MagicMock()
        mc.closed = 0
        with patch("coruscant.core.database.psycopg2.connect", return_value=mc):
            db.connect("h", 5432, "db", "u", "pw")
        assert db.has_last_params is True


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------

class TestDisconnect:
    def test_safe_when_not_connected(self):
        db = DatabaseManager()
        db.disconnect()   # must not raise

    def test_closes_open_connection(self):
        db, mc, _ = _make_connected_db()
        db.disconnect()
        mc.close.assert_called_once()
        assert db._conn is None

    def test_safe_to_call_twice(self):
        db, _, _ = _make_connected_db()
        db.disconnect()
        db.disconnect()   # must not raise


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------

class TestCancel:
    def test_safe_when_not_connected(self):
        db = DatabaseManager()
        db.cancel()   # must not raise

    def test_calls_conn_cancel(self):
        db, mc, _ = _make_connected_db()
        db.cancel()
        mc.cancel.assert_called_once()

    def test_swallows_exception(self):
        db, mc, _ = _make_connected_db()
        mc.cancel.side_effect = Exception("gone")
        db.cancel()   # must not propagate


# ---------------------------------------------------------------------------
# Transaction guards (not connected)
# ---------------------------------------------------------------------------

class TestTransactionGuardsNotConnected:
    """All mutating methods must raise RuntimeError when not connected
    AND no last_params are available for auto-reconnect."""

    def _fresh(self):
        db = DatabaseManager()
        assert db._conn is None
        assert db._last_params is None
        return db

    def test_set_autocommit_raises(self):
        with pytest.raises(RuntimeError, match="Not connected"):
            self._fresh().set_autocommit(False)

    def test_commit_raises(self):
        with pytest.raises(RuntimeError, match="Not connected"):
            self._fresh().commit()

    def test_rollback_raises(self):
        with pytest.raises(RuntimeError, match="Not connected"):
            self._fresh().rollback()

    def test_get_schema_tree_raises(self):
        with pytest.raises(RuntimeError, match="Not connected"):
            self._fresh().get_schema_tree()

    def test_execute_raises(self):
        with pytest.raises(RuntimeError, match="Not connected"):
            self._fresh().execute("SELECT 1")


# ---------------------------------------------------------------------------
# Transaction methods (connected)
# ---------------------------------------------------------------------------

class TestTransactionConnected:
    def test_set_autocommit_delegates(self):
        db, mc, _ = _make_connected_db()
        db.set_autocommit(False)
        assert mc.autocommit is False

    def test_set_autocommit_true(self):
        db, mc, _ = _make_connected_db(autocommit=False)
        db.set_autocommit(True)
        assert mc.autocommit is True

    def test_commit_delegates(self):
        db, mc, _ = _make_connected_db()
        db.commit()
        mc.commit.assert_called_once()

    def test_rollback_delegates(self):
        db, mc, _ = _make_connected_db()
        db.rollback()
        mc.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# in_transaction
# ---------------------------------------------------------------------------

class TestInTransaction:
    def test_false_when_not_connected(self):
        db = DatabaseManager()
        assert db.in_transaction is False

    def test_false_when_autocommit_on(self):
        db, mc, _ = _make_connected_db(autocommit=True)
        assert db.in_transaction is False

    def test_true_when_autocommit_off_and_in_transaction(self):
        db, mc, _ = _make_connected_db(autocommit=False)
        mc.status = 1   # STATUS_IN_TRANSACTION
        db._conn = mc
        # autocommit is False → in_transaction should be True
        assert db.in_transaction is True


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

class TestConnect:
    def test_calls_psycopg2_connect_with_correct_args(self):
        db = DatabaseManager()
        mc = MagicMock(); mc.closed = 0
        with patch("coruscant.core.database.psycopg2.connect", return_value=mc) as mock_c:
            db.connect("localhost", 5432, "testdb", "alice", "secret", "prefer")
        mock_c.assert_called_once_with(
            host="localhost", port=5432, dbname="testdb",
            user="alice", password="secret",
            connect_timeout=10, sslmode="prefer",
        )

    def test_sets_autocommit_true(self):
        db = DatabaseManager()
        mc = MagicMock(); mc.closed = 0
        with patch("coruscant.core.database.psycopg2.connect", return_value=mc):
            db.connect("h", 5432, "db", "u", "pw")
        assert mc.autocommit is True

    def test_stores_last_params(self):
        db = DatabaseManager()
        mc = MagicMock(); mc.closed = 0
        with patch("coruscant.core.database.psycopg2.connect", return_value=mc):
            db.connect("h", 5432, "db", "u", "pw", "require")
        assert db._last_params["host"] == "h"
        assert db._last_params["ssl_mode"] == "require"

    def test_closes_existing_before_reconnect(self):
        db = DatabaseManager()
        old_conn = MagicMock(); old_conn.closed = 0
        db._conn = old_conn
        new_conn = MagicMock(); new_conn.closed = 0
        with patch("coruscant.core.database.psycopg2.connect", return_value=new_conn):
            db.connect("h", 5432, "db", "u", "pw")
        old_conn.close.assert_called_once()
        assert db._conn is new_conn

    def test_propagates_operational_error(self):
        db = DatabaseManager()
        with patch("coruscant.core.database.psycopg2.connect",
                   side_effect=_psycopg2.OperationalError("refused")):
            with pytest.raises(_psycopg2.OperationalError):
                db.connect("bad-host", 5432, "db", "u", "pw")

    def test_ssl_mode_defaults_to_prefer(self):
        db = DatabaseManager()
        mc = MagicMock(); mc.closed = 0
        with patch("coruscant.core.database.psycopg2.connect", return_value=mc) as mock_c:
            db.connect("h", 5432, "db", "u", "pw")  # no ssl_mode arg
        _, kwargs = mock_c.call_args
        assert kwargs["sslmode"] == "prefer"


# ---------------------------------------------------------------------------
# execute() — input validation
# ---------------------------------------------------------------------------

class TestExecuteValidation:
    def test_raises_on_empty_string(self):
        db, _, _ = _make_connected_db()
        with pytest.raises(ValueError, match="No SQL statements"):
            db.execute("")

    def test_raises_on_whitespace_only(self):
        db, _, _ = _make_connected_db()
        with pytest.raises(ValueError, match="No SQL statements"):
            db.execute("   \n  ")

    def test_raises_on_semicolons_only(self):
        db, _, _ = _make_connected_db()
        with pytest.raises(ValueError, match="No SQL statements"):
            db.execute(";;;")


# ---------------------------------------------------------------------------
# execute() — SELECT results
# ---------------------------------------------------------------------------

class TestExecuteSelect:
    def test_returns_query_result(self):
        db, _, _ = _make_connected_db(
            description=[_mock_col("id"), _mock_col("name")],
            fetchall_return=[(1, "Alice"), (2, "Bob")],
        )
        results = db.execute("SELECT id, name FROM users")
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, QueryResult)
        assert r.label   == "Query 1"
        assert r.columns == ["id", "name"]
        assert r.rows    == [(1, "Alice"), (2, "Bob")]
        assert r.truncated is False

    def test_elapsed_ms_non_negative(self):
        db, _, _ = _make_connected_db(
            description=[_mock_col("x")], fetchall_return=[(1,)])
        results = db.execute("SELECT 1 AS x")
        assert results[0].elapsed_ms >= 0

    def test_row_limit_zero_uses_fetchall(self):
        db, _, cur = _make_connected_db(
            description=[_mock_col("id")], fetchall_return=[(1,), (2,)])
        db.execute("SELECT id FROM t", row_limit=0)
        cur.fetchall.assert_called_once()
        cur.fetchmany.assert_not_called()

    def test_row_limit_positive_uses_fetchmany(self):
        db, _, cur = _make_connected_db(
            description=[_mock_col("id")],
            fetchmany_return=[(1,)],
            fetchone_return=None,
        )
        db.execute("SELECT id FROM t", row_limit=10)
        cur.fetchmany.assert_called_once_with(10)

    def test_truncated_false_when_no_extra_row(self):
        db, _, cur = _make_connected_db(
            description=[_mock_col("id")],
            fetchmany_return=[(1,)],
            fetchone_return=None,
        )
        results = db.execute("SELECT id FROM t", row_limit=10)
        assert results[0].truncated is False

    def test_truncated_true_when_extra_row_exists(self):
        db, _, cur = _make_connected_db(
            description=[_mock_col("id")],
            fetchmany_return=[(1,), (2,)],
            fetchone_return=(3,),
        )
        results = db.execute("SELECT id FROM t", row_limit=2)
        assert results[0].truncated is True

    def test_truncated_drains_cursor(self):
        db, _, cur = _make_connected_db(
            description=[_mock_col("id")],
            fetchmany_return=[(1,)],
            fetchone_return=(2,),
        )
        db.execute("SELECT id FROM t", row_limit=1)
        cur.fetchall.assert_called()   # drain call after truncation


# ---------------------------------------------------------------------------
# execute() — DML / DDL results
# ---------------------------------------------------------------------------

class TestExecuteCommand:
    def test_returns_command_result(self):
        db, _, cur = _make_connected_db(description=None, rowcount=5)
        results = db.execute("DELETE FROM t WHERE id = 1")
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, CommandResult)
        assert r.label == "Query 1"
        assert "5" in r.message

    def test_rowcount_negative_shown_as_na(self):
        db, _, cur = _make_connected_db(description=None, rowcount=-1)
        results = db.execute("CREATE INDEX idx ON t(id)")
        assert "N/A" in results[0].message

    def test_rowcount_zero_shown_as_zero(self):
        db, _, cur = _make_connected_db(description=None, rowcount=0)
        results = db.execute("DELETE FROM t WHERE 1=0")
        assert "0" in results[0].message


# ---------------------------------------------------------------------------
# execute() — multiple statements
# ---------------------------------------------------------------------------

class TestExecuteMultiple:
    def test_two_selects_produce_two_results(self):
        db, _, cur = _make_connected_db(
            description=[_mock_col("n")], fetchall_return=[(1,)])
        results = db.execute("SELECT 1; SELECT 2;")
        assert len(results) == 2
        assert results[0].label == "Query 1"
        assert results[1].label == "Query 2"

    def test_mixed_select_and_dml(self):
        db, _, cur = _make_connected_db()
        _call_n = count()

        def _exec(sql, *a, **kw):
            n = next(_call_n)
            if n == 0:
                cur.description = [_mock_col("id")]
                cur.fetchall.return_value = [(1,)]
            else:
                cur.description = None
                cur.rowcount = 3

        cur.execute.side_effect = _exec
        results = db.execute("SELECT id FROM t; DELETE FROM t WHERE id = 1;")
        assert len(results) == 2
        assert isinstance(results[0], QueryResult)
        assert isinstance(results[1], CommandResult)

    def test_label_numbering_sequential(self):
        db, _, cur = _make_connected_db(description=None, rowcount=0)
        results = db.execute("DELETE FROM a; DELETE FROM b; DELETE FROM c;")
        assert [r.label for r in results] == ["Query 1", "Query 2", "Query 3"]


# ---------------------------------------------------------------------------
# execute() — error handling
# ---------------------------------------------------------------------------

class TestExecuteErrors:
    def test_db_error_propagates(self):
        db, _, cur = _make_connected_db()
        cur.execute.side_effect = _psycopg2.OperationalError("boom")
        with pytest.raises(_psycopg2.OperationalError):
            db.execute("SELECT 1")

    def test_error_attaches_statement_to_exc(self):
        db, _, cur = _make_connected_db()
        exc = _psycopg2.OperationalError("boom")
        cur.execute.side_effect = exc
        with pytest.raises(_psycopg2.OperationalError) as exc_info:
            db.execute("SELECT bad_col FROM t")
        assert hasattr(exc_info.value, "statement")

    def test_closed_connection_nulled_after_error(self):
        db, mc, cur = _make_connected_db()
        cur.execute.side_effect = _psycopg2.OperationalError("lost")
        # Make conn.closed return True on the error-handling path
        type(mc).closed = PropertyMock(side_effect=[0, 0, 1])
        with pytest.raises(_psycopg2.OperationalError):
            db.execute("SELECT 1")
        assert db._conn is None
        assert db.is_connected is False

    def test_non_closed_conn_kept_after_error(self):
        db, mc, cur = _make_connected_db()
        cur.execute.side_effect = _psycopg2.OperationalError("transient")
        mc.closed = 0   # connection still open
        with pytest.raises(_psycopg2.OperationalError):
            db.execute("SELECT 1")
        # conn is NOT nulled when closed == 0
        assert db._conn is mc


# ---------------------------------------------------------------------------
# execute() — params substitution path (mogrify)
# ---------------------------------------------------------------------------

class TestExecuteParams:
    def test_params_causes_mogrify_call(self):
        db, mc, cur = _make_connected_db(description=None, rowcount=1)
        cur.mogrify.return_value = b"SELECT 1 WHERE id = 42"
        db.execute("SELECT 1 WHERE id = %(id)s", params={"id": 42})
        cur.mogrify.assert_called_once()

    def test_params_none_skips_mogrify(self):
        db, mc, cur = _make_connected_db(description=None, rowcount=1)
        db.execute("DELETE FROM t", params=None)
        cur.mogrify.assert_not_called()


# ---------------------------------------------------------------------------
# get_schema_tree()
# ---------------------------------------------------------------------------

class TestGetSchemaTree:
    def _mock_fetchall_sequence(self, cur, table_rows, col_rows,
                                 idx_rows, fk_rows, fn_rows):
        """Make cur.fetchall() return different values on successive calls."""
        responses = iter([table_rows, col_rows, idx_rows, fk_rows, fn_rows])
        cur.fetchall.side_effect = lambda: next(responses)

    def test_returns_list(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("public", "users", "BASE TABLE")],
            [("public", "users", "id", "integer", 1)],
            [],
            [],
            [],
        )
        result = db.get_schema_tree()
        assert isinstance(result, list)

    def test_schema_dict_shape(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("public", "users", "BASE TABLE")],
            [("public", "users", "id", "integer", 1)],
            [],
            [],
            [],
        )
        result = db.get_schema_tree()
        assert len(result) == 1
        schema = result[0]
        assert "schema"    in schema
        assert "tables"    in schema
        assert "functions" in schema

    def test_columns_attached_to_table(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("public", "users", "BASE TABLE")],
            [("public", "users", "id", "integer", 1),
             ("public", "users", "name", "text", 2)],
            [],
            [],
            [],
        )
        result = db.get_schema_tree()
        table = result[0]["tables"][0]
        assert len(table["columns"]) == 2
        assert table["columns"][0]["name"] == "id"

    def test_indexes_attached_to_table(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("public", "users", "BASE TABLE")],
            [],
            [("public", "users", "users_pkey", "CREATE UNIQUE INDEX ...")],
            [],
            [],
        )
        result = db.get_schema_tree()
        table = result[0]["tables"][0]
        assert len(table["indexes"]) == 1

    def test_functions_attached_to_schema(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [],
            [],
            [],
            [],
            [("public", "my_func", "FUNCTION", "integer")],
        )
        result = db.get_schema_tree()
        schema = result[0]
        assert schema["schema"] == "public"
        assert len(schema["functions"]) == 1
        assert schema["functions"][0]["name"] == "my_func"

    def test_fk_error_returns_empty_fks(self):
        """FK query failure must be silently swallowed (returns empty list)."""
        db, _, cur = _make_connected_db()
        table_rows = [("public", "users", "BASE TABLE")]
        col_rows   = []
        idx_rows   = []
        fn_rows    = []

        call_n = count()

        def _fetchall():
            n = next(call_n)
            if n == 0: return table_rows
            if n == 1: return col_rows
            if n == 2: return idx_rows
            # n==3 is the FK query — execute() raises, so fetchall not called
            if n == 3: return fn_rows   # functions
            return []

        cur.fetchall.side_effect = _fetchall
        cur.execute.side_effect = [
            None, None, None,
            _psycopg2.Error("no perms"),  # FK execute raises
            None,
        ]
        result = db.get_schema_tree()
        assert isinstance(result, list)

    def test_multiple_schemas_sorted(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("zschema", "t1", "BASE TABLE"), ("aschema", "t2", "BASE TABLE")],
            [],
            [],
            [],
            [],
        )
        result = db.get_schema_tree()
        names = [s["schema"] for s in result]
        assert names == sorted(names)
