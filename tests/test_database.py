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
    class _ProgErr(_Err): pass

    mod.Error              = _Err
    mod.OperationalError   = _OpErr
    mod.InterfaceError     = _IfErr
    mod.DatabaseError      = _DbErr
    mod.ProgrammingError   = _ProgErr

    extras = types.ModuleType("psycopg2.extras")
    exts   = types.ModuleType("psycopg2.extensions")
    exts.STATUS_IN_TRANSACTION = 2   # must match psycopg2's real value

    mod.extras     = extras
    mod.extensions = exts
    sys.modules.setdefault("psycopg2",            mod)
    sys.modules.setdefault("psycopg2.extras",     extras)
    sys.modules.setdefault("psycopg2.extensions", exts)
    return mod

_make_psycopg2_stub()

# Bind to whichever psycopg2 is actually in play, not to the stub object.
# setdefault() is a no-op when the real driver has already been imported (see
# tests/conftest.py), and in that case production code raises and catches the
# *real* psycopg2.Error — so tests raising the stub's error class would not be
# caught by the code under test.
_psycopg2 = sys.modules["psycopg2"]

from coruscant.core.database import (   # noqa: E402  (import after stub)
    DatabaseManager,
    QueryResult,
    CommandResult,
    PGCODE_QUERY_CANCELED,
    PROKIND_MIN_SERVER_VERSION,
    SCHEMA_ROUTINES_SQL,
    SCHEMA_ROUTINES_PRE11_SQL,
    quote_ident,
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
    mock_conn.status = _psycopg2.extensions.STATUS_IN_TRANSACTION
    mock_conn.server_version = 160000   # PostgreSQL 16.0 — has prokind

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
        mc.status = _psycopg2.extensions.STATUS_IN_TRANSACTION
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
    """
    Row shapes here mirror the catalog queries in database.py:

        relations : (schema, name, oid, relation_type)
        columns   : (schema, relation, column, type, attnum)
        indexes   : (schema, relation, index, definition)
        fks       : (schema, relation, constraint, definition)
        routines  : (schema, name, oid, identity_args, prokind, result_type)
    """

    def _mock_fetchall_sequence(self, cur, relation_rows, col_rows,
                                 idx_rows, fk_rows, fn_rows):
        """Make cur.fetchall() return different values on successive calls."""
        responses = iter([relation_rows, col_rows, idx_rows, fk_rows, fn_rows])
        cur.fetchall.side_effect = lambda: next(responses)

    # ── shape ──────────────────────────────────────────────────────────

    def test_returns_list(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("public", "users", 16384, "BASE TABLE")],
            [("public", "users", "id", "integer", 1)],
            [], [], [],
        )
        assert isinstance(db.get_schema_tree(), list)

    def test_schema_dict_shape(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("public", "users", 16384, "BASE TABLE")],
            [("public", "users", "id", "integer", 1)],
            [], [], [],
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
            [("public", "users", 16384, "BASE TABLE")],
            [("public", "users", "id", "integer", 1),
             ("public", "users", "name", "text", 2)],
            [], [], [],
        )
        table = db.get_schema_tree()[0]["tables"][0]
        assert len(table["columns"]) == 2
        assert table["columns"][0]["name"] == "id"

    def test_indexes_attached_to_table(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("public", "users", 16384, "BASE TABLE")],
            [],
            [("public", "users", "users_pkey", "CREATE UNIQUE INDEX ...")],
            [], [],
        )
        assert len(db.get_schema_tree()[0]["tables"][0]["indexes"]) == 1

    def test_functions_attached_to_schema(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [],
            [("public", "my_func", 20001, "", "f", "integer")],
        )
        schema = db.get_schema_tree()[0]
        assert schema["schema"] == "public"
        assert len(schema["functions"]) == 1
        assert schema["functions"][0]["name"] == "my_func"

    def test_fk_error_returns_empty_fks(self):
        """FK query failure must be silently swallowed (returns empty list)."""
        db, _, cur = _make_connected_db()
        relation_rows = [("public", "users", 16384, "BASE TABLE")]

        call_n = count()

        def _fetchall():
            n = next(call_n)
            if n == 0: return relation_rows
            if n == 1: return []          # columns
            if n == 2: return []          # indexes
            # n == 3 is the FK query — execute() raises, fetchall not reached
            if n == 3: return []          # routines
            return []

        cur.fetchall.side_effect = _fetchall
        cur.execute.side_effect = [
            None, None, None,
            _psycopg2.Error("no perms"),  # FK execute raises
            None,
        ]
        result = db.get_schema_tree()
        assert isinstance(result, list)
        assert result[0]["tables"][0]["foreign_keys"] == []

    def test_multiple_schemas_sorted(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("zschema", "t1", 1, "BASE TABLE"), ("aschema", "t2", 2, "BASE TABLE")],
            [], [], [], [],
        )
        names = [s["schema"] for s in db.get_schema_tree()]
        assert names == sorted(names)

    # ── OIDs: the handle every definition lookup is keyed on ───────────

    def test_relation_carries_its_oid(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [("public", "users", 16384, "BASE TABLE")], [], [], [], [],
        )
        assert db.get_schema_tree()[0]["tables"][0]["oid"] == 16384

    def test_routine_carries_its_oid(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [],
            [("public", "f", 20001, "", "f", "integer")],
        )
        assert db.get_schema_tree()[0]["functions"][0]["oid"] == 20001

    # ── relation kinds ─────────────────────────────────────────────────

    def test_materialised_view_is_listed(self):
        """
        information_schema.tables has no materialised views, so before the
        move to pg_class they were absent from the tree entirely.
        """
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [("public", "sales_mv", 30001, "MATERIALIZED VIEW")],
            [], [], [], [],
        )
        rel = db.get_schema_tree()[0]["tables"][0]
        assert rel["name"] == "sales_mv"
        assert rel["type"] == "MATERIALIZED VIEW"

    def test_view_type_is_preserved(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [("public", "v_users", 30002, "VIEW")], [], [], [], [],
        )
        assert db.get_schema_tree()[0]["tables"][0]["type"] == "VIEW"

    def test_matview_columns_attach(self):
        """pg_attribute covers matviews; information_schema.columns did not."""
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur,
            [("public", "sales_mv", 30001, "MATERIALIZED VIEW")],
            [("public", "sales_mv", "total", "numeric", 1)],
            [], [], [],
        )
        assert db.get_schema_tree()[0]["tables"][0]["columns"][0]["name"] == "total"

    # ── overloading: the reason routines needed an OID at all ──────────

    def test_overloads_are_distinguishable(self):
        """
        calc(integer) and calc(numeric) share a name.  Keyed on name alone
        they were two identical rows; they must now differ by OID and by the
        signature the tree displays.
        """
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [],
            [("public", "calc", 20001, "integer", "f", "integer"),
             ("public", "calc", 20002, "numeric", "f", "numeric")],
        )
        fns = db.get_schema_tree()[0]["functions"]
        assert len(fns) == 2
        assert {f["oid"] for f in fns} == {20001, 20002}
        assert {f["signature"] for f in fns} == {"calc(integer)", "calc(numeric)"}

    def test_signature_includes_arguments(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [],
            [("public", "f", 1, "a integer, b text", "f", "void")],
        )
        fn = db.get_schema_tree()[0]["functions"][0]
        assert fn["signature"] == "f(a integer, b text)"
        assert fn["arguments"] == "a integer, b text"

    def test_signature_of_zero_argument_routine(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [], [("public", "f", 1, "", "f", "void")],
        )
        assert db.get_schema_tree()[0]["functions"][0]["signature"] == "f()"

    def test_null_arguments_become_empty_string(self):
        """pg_get_function_identity_arguments() can return NULL."""
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [], [("public", "f", 1, None, "f", "void")],
        )
        fn = db.get_schema_tree()[0]["functions"][0]
        assert fn["arguments"] == ""
        assert fn["signature"] == "f()"

    def test_null_return_type_becomes_empty_string(self):
        """pg_get_function_result() returns NULL for a procedure."""
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [], [("public", "p", 1, "", "p", None)],
        )
        assert db.get_schema_tree()[0]["functions"][0]["return_type"] == ""

    # ── prokind → label, and whether source can be fetched ─────────────

    def test_procedure_is_labelled_procedure(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [], [("public", "p", 1, "", "p", None)],
        )
        assert db.get_schema_tree()[0]["functions"][0]["type"] == "PROCEDURE"

    def test_window_function_is_labelled_window(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [], [("public", "w", 1, "", "w", "integer")],
        )
        assert db.get_schema_tree()[0]["functions"][0]["type"] == "WINDOW"

    def test_unknown_prokind_falls_back_to_function(self):
        """A prokind from a future server must not break the tree."""
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [], [("public", "x", 1, "", "?", "integer")],
        )
        assert db.get_schema_tree()[0]["functions"][0]["type"] == "FUNCTION"

    def test_aggregate_is_marked_as_having_no_source(self):
        """
        pg_get_functiondef() raises on an aggregate.  The flag is what stops
        the UI offering an action that can only fail.
        """
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [], [("public", "agg", 1, "integer", "a", "integer")],
        )
        fn = db.get_schema_tree()[0]["functions"][0]
        assert fn["type"] == "AGGREGATE"
        assert fn["has_source"] is False

    def test_plain_function_has_source(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [], [("public", "f", 1, "", "f", "integer")],
        )
        assert db.get_schema_tree()[0]["functions"][0]["has_source"] is True

    def test_procedure_has_source(self):
        db, _, cur = _make_connected_db()
        self._mock_fetchall_sequence(
            cur, [], [], [], [], [("public", "p", 1, "", "p", None)],
        )
        assert db.get_schema_tree()[0]["functions"][0]["has_source"] is True




# ---------------------------------------------------------------------------
# terminate_connections — behavioural
# ---------------------------------------------------------------------------

class TestTerminateConnections:
    """
    This kills live database backends, and until now the only test asserting
    anything about it was `"terminate_connections" in _fns(...)` — a check that
    the name exists. It passes whether the function targets idle sessions or
    every session on the server.

    The self-exclusion clause in particular is load-bearing: without it the
    repair terminates the connection issuing it.
    """

    @staticmethod
    def _sql(cur) -> str:
        return " ".join(str(c) for c in cur.execute.call_args_list)

    def test_returns_the_number_terminated(self):
        db, _, cur = _make_connected_db(fetchone_return=(7,))
        assert db.terminate_connections() == 7

    def test_zero_when_nothing_matched(self):
        db, _, cur = _make_connected_db(fetchone_return=(0,))
        assert db.terminate_connections() == 0

    def test_zero_when_no_row_came_back(self):
        db, _, cur = _make_connected_db(fetchone_return=None)
        assert db.terminate_connections() == 0

    def test_never_terminates_the_calling_session(self):
        """Without this guard the repair kills its own connection."""
        db, _, cur = _make_connected_db(fetchone_return=(1,))
        db.terminate_connections()
        assert "pid != pg_backend_pid()" in self._sql(cur), (
            "must exclude the current backend"
        )

    def test_filters_on_the_requested_state(self):
        db, _, cur = _make_connected_db(fetchone_return=(1,))
        db.terminate_connections(state="idle in transaction")
        args = cur.execute.call_args[0]
        assert "state = %s" in args[0]
        assert args[1] == ["idle in transaction"], (
            "state must be bound as a parameter, not interpolated"
        )

    def test_state_is_never_interpolated_into_the_sql(self):
        """
        A state value reaching the SQL *text* would be injectable. It must
        arrive as a bound parameter, so inspect the statement alone — the
        params tuple legitimately contains whatever was passed.
        """
        hostile = "idle'; DROP TABLE x; --"
        db, _, cur = _make_connected_db(fetchone_return=(0,))
        db.terminate_connections(state=hostile)
        statement, params = cur.execute.call_args[0]
        assert "DROP TABLE" not in statement, "state was interpolated into the SQL"
        assert params == [hostile], "state must travel as a bound parameter"

    def test_idle_threshold_omitted_by_default(self):
        db, _, cur = _make_connected_db(fetchone_return=(1,))
        db.terminate_connections()
        assert "state_change" not in self._sql(cur)

    def test_idle_threshold_applied_when_requested(self):
        db, _, cur = _make_connected_db(fetchone_return=(1,))
        db.terminate_connections(min_idle_mins=15)
        sql = self._sql(cur)
        assert "state_change" in sql and "15 minutes" in sql

    def test_idle_threshold_is_coerced_to_int(self):
        """It is formatted into the SQL, so it must not carry arbitrary text."""
        db, _, cur = _make_connected_db(fetchone_return=(0,))
        db.terminate_connections(min_idle_mins=True)   # bool is an int subclass
        assert "1 minutes" in self._sql(cur)

    def test_raises_when_not_connected(self):
        with pytest.raises(RuntimeError, match="Not connected"):
            DatabaseManager().terminate_connections()


# ---------------------------------------------------------------------------
# quote_ident()
# ---------------------------------------------------------------------------

class TestQuoteIdent:
    """
    A definition is fetched so it can be edited and run again.  An identifier
    that does not survive that round trip makes the whole feature a trap.
    """

    def test_wraps_in_double_quotes(self):
        assert quote_ident("users") == '"users"'

    def test_preserves_spaces(self):
        assert quote_ident("Order Details") == '"Order Details"'

    def test_preserves_case(self):
        assert quote_ident("MyView") == '"MyView"'

    def test_doubles_an_embedded_quote(self):
        assert quote_ident('we"ird') == '"we""ird"'

    def test_doubles_every_embedded_quote(self):
        assert quote_ident('a"b"c') == '"a""b""c"'

    def test_empty_identifier(self):
        assert quote_ident("") == '""'


# ---------------------------------------------------------------------------
# server_version
# ---------------------------------------------------------------------------

class TestServerVersion:
    def test_reports_the_drivers_version(self):
        db, conn, _ = _make_connected_db()
        conn.server_version = 160002
        assert db.server_version == 160002

    def test_zero_when_not_connected(self):
        assert DatabaseManager().server_version == 0

    def test_zero_when_driver_reports_none(self):
        db, conn, _ = _make_connected_db()
        conn.server_version = None
        assert db.server_version == 0

    def test_zero_when_driver_reports_nonsense(self):
        db, conn, _ = _make_connected_db()
        conn.server_version = "not a version"
        assert db.server_version == 0


# ---------------------------------------------------------------------------
# _routines_sql() — version-dependent catalog query
# ---------------------------------------------------------------------------

class TestRoutinesSql:
    """
    prokind replaced proisagg/proiswindow in PostgreSQL 11.  Naming a column
    the server does not have is a parse error, so the wrong query here does
    not degrade — it empties the tree of every routine.
    """

    def test_modern_server_uses_prokind(self):
        db, conn, _ = _make_connected_db()
        conn.server_version = 160000
        assert db._routines_sql() is SCHEMA_ROUTINES_SQL

    def test_pre_11_server_uses_the_boolean_columns(self):
        db, conn, _ = _make_connected_db()
        conn.server_version = 100000        # PostgreSQL 10
        assert db._routines_sql() is SCHEMA_ROUTINES_PRE11_SQL

    def test_boundary_version_uses_prokind(self):
        db, conn, _ = _make_connected_db()
        conn.server_version = PROKIND_MIN_SERVER_VERSION
        assert db._routines_sql() is SCHEMA_ROUTINES_SQL

    def test_one_below_boundary_uses_the_boolean_columns(self):
        db, conn, _ = _make_connected_db()
        conn.server_version = PROKIND_MIN_SERVER_VERSION - 1
        assert db._routines_sql() is SCHEMA_ROUTINES_PRE11_SQL

    def test_unknown_version_uses_the_modern_query(self):
        """
        Zero means "the driver did not say", not "ancient".  Guessing old
        would break every supported server to accommodate a rare unsupported
        one.
        """
        db, conn, _ = _make_connected_db()
        conn.server_version = None
        assert db.server_version == 0
        assert db._routines_sql() is SCHEMA_ROUTINES_SQL

    def test_the_two_queries_reference_the_right_columns(self):
        assert "prokind" in SCHEMA_ROUTINES_SQL
        assert "proisagg" not in SCHEMA_ROUTINES_SQL
        assert "proisagg" in SCHEMA_ROUTINES_PRE11_SQL
        assert "proiswindow" in SCHEMA_ROUTINES_PRE11_SQL
        assert "prokind" not in SCHEMA_ROUTINES_PRE11_SQL

    def test_both_queries_select_the_same_six_columns(self):
        """The row unpacking in get_schema_tree() serves both."""
        for sql in (SCHEMA_ROUTINES_SQL, SCHEMA_ROUTINES_PRE11_SQL):
            assert "p.oid" in sql
            assert "pg_get_function_identity_arguments" in sql
            assert "pg_get_function_result" in sql


# ---------------------------------------------------------------------------
# _scalar_guarded() — savepoint containment
# ---------------------------------------------------------------------------

def _executed(cur):
    """Every SQL string passed to cur.execute(), in order."""
    return [c.args[0] for c in cur.execute.call_args_list]


class TestScalarGuarded:
    """
    These lookups share the connection the user runs queries on.  With
    autocommit off a failed statement aborts the surrounding transaction and
    every later statement in it — so an unguarded lookup for an object
    somebody has just dropped silently discards uncommitted work.
    """

    def test_returns_the_first_column(self):
        db, _, _ = _make_connected_db(fetchone_return=("value",))
        assert db._scalar_guarded("SELECT 1", ()) == "value"

    def test_returns_none_when_no_row(self):
        db, _, _ = _make_connected_db(fetchone_return=None)
        assert db._scalar_guarded("SELECT 1", ()) is None

    def test_passes_parameters_to_the_driver(self):
        """Bound, not interpolated: the OID never reaches the SQL text."""
        db, _, cur = _make_connected_db(fetchone_return=("x",), autocommit=True)
        db._scalar_guarded("SELECT %s", (42,))
        assert cur.execute.call_args_list[0].args[1] == (42,)

    def test_requires_a_connection(self):
        with pytest.raises(RuntimeError):
            DatabaseManager()._scalar_guarded("SELECT 1", ())

    # ── autocommit on: nothing to protect ──────────────────────────────

    def test_autocommit_issues_no_savepoint(self):
        db, _, cur = _make_connected_db(fetchone_return=("x",), autocommit=True)
        db._scalar_guarded("SELECT 1", ())
        assert not any("SAVEPOINT" in s for s in _executed(cur))

    def test_autocommit_failure_issues_no_rollback(self):
        db, _, cur = _make_connected_db(autocommit=True)
        cur.execute.side_effect = _psycopg2.Error("boom")
        with pytest.raises(_psycopg2.Error):
            db._scalar_guarded("SELECT 1", ())
        assert not any("SAVEPOINT" in s for s in _executed(cur))

    # ── autocommit off: the lookup must be containable ─────────────────

    def test_savepoint_brackets_the_query(self):
        db, _, cur = _make_connected_db(fetchone_return=("x",), autocommit=False)
        db._scalar_guarded("SELECT 1", ())
        sqls = _executed(cur)
        assert sqls[0].startswith("SAVEPOINT ")
        assert sqls[-1].startswith("RELEASE SAVEPOINT ")

    def test_savepoint_is_released_on_success(self):
        db, _, cur = _make_connected_db(fetchone_return=("x",), autocommit=False)
        db._scalar_guarded("SELECT 1", ())
        assert sum(s.startswith("RELEASE SAVEPOINT ") for s in _executed(cur)) == 1

    def test_failure_rolls_back_to_the_savepoint(self):
        db, _, cur = _make_connected_db(autocommit=False)
        cur.execute.side_effect = [
            None,                          # SAVEPOINT
            _psycopg2.Error("boom"),       # the lookup
            None,                          # ROLLBACK TO SAVEPOINT
            None,                          # RELEASE SAVEPOINT
        ]
        with pytest.raises(_psycopg2.Error):
            db._scalar_guarded("SELECT 1", ())
        sqls = _executed(cur)
        assert any(s.startswith("ROLLBACK TO SAVEPOINT ") for s in sqls)
        assert any(s.startswith("RELEASE SAVEPOINT ") for s in sqls)

    def test_rollback_precedes_release(self):
        db, _, cur = _make_connected_db(autocommit=False)
        cur.execute.side_effect = [None, _psycopg2.Error("boom"), None, None]
        with pytest.raises(_psycopg2.Error):
            db._scalar_guarded("SELECT 1", ())
        sqls = _executed(cur)
        rollback = next(i for i, s in enumerate(sqls) if s.startswith("ROLLBACK TO"))
        release = next(i for i, s in enumerate(sqls) if s.startswith("RELEASE"))
        assert rollback < release

    def test_the_error_still_reaches_the_caller(self):
        """Containing the damage must not swallow the diagnosis."""
        db, _, cur = _make_connected_db(autocommit=False)
        cur.execute.side_effect = [None, _psycopg2.Error("boom"), None, None]
        with pytest.raises(_psycopg2.Error):
            db._scalar_guarded("SELECT 1", ())

    def test_guarded_even_before_a_transaction_is_open(self):
        """
        in_transaction is False until a statement runs, but with autocommit
        off this statement is the one that opens the transaction — a failure
        would leave it aborted behind us.  The guard keys on autocommit for
        exactly this case.
        """
        db, conn, cur = _make_connected_db(fetchone_return=("x",), autocommit=False)
        conn.status = 0                     # STATUS_READY — nothing open yet
        assert db.in_transaction is False
        db._scalar_guarded("SELECT 1", ())
        assert any(s.startswith("SAVEPOINT ") for s in _executed(cur))

    def test_same_savepoint_name_throughout(self):
        db, _, cur = _make_connected_db(fetchone_return=("x",), autocommit=False)
        db._scalar_guarded("SELECT 1", ())
        names = {s.split()[-1] for s in _executed(cur) if "SAVEPOINT" in s}
        assert len(names) == 1


# ---------------------------------------------------------------------------
# get_routine_definition()
# ---------------------------------------------------------------------------

_FUNCDEF = (
    "CREATE OR REPLACE FUNCTION public.calc(a integer)\n"
    " RETURNS integer\n LANGUAGE sql\nAS $function$ SELECT a $function$\n"
)


class TestGetRoutineDefinition:
    def test_returns_the_servers_statement_unchanged(self):
        """
        pg_get_functiondef() already emits a complete CREATE OR REPLACE.
        Rewriting it would only risk corrupting a valid statement.
        """
        db, _, _ = _make_connected_db(fetchone_return=(_FUNCDEF,))
        assert db.get_routine_definition(20001) == _FUNCDEF

    def test_result_is_runnable_as_a_replacement(self):
        db, _, _ = _make_connected_db(fetchone_return=(_FUNCDEF,))
        assert db.get_routine_definition(20001).startswith("CREATE OR REPLACE FUNCTION")

    def test_binds_the_oid_as_a_parameter(self):
        db, _, cur = _make_connected_db(fetchone_return=(_FUNCDEF,), autocommit=True)
        db.get_routine_definition(20001)
        sql, params = cur.execute.call_args_list[0].args[:2]
        assert params == (20001,)
        assert "%s" in sql
        assert "20001" not in sql

    def test_requires_a_connection(self):
        with pytest.raises(RuntimeError):
            DatabaseManager().get_routine_definition(1)

    def test_lookup_error_when_the_oid_has_no_row(self):
        db, _, _ = _make_connected_db(fetchone_return=None)
        with pytest.raises(LookupError):
            db.get_routine_definition(999)

    def test_lookup_error_when_the_definition_is_null(self):
        db, _, _ = _make_connected_db(fetchone_return=(None,))
        with pytest.raises(LookupError):
            db.get_routine_definition(999)

    def test_lookup_error_when_the_definition_is_empty(self):
        db, _, _ = _make_connected_db(fetchone_return=("",))
        with pytest.raises(LookupError):
            db.get_routine_definition(999)

    def test_driver_error_propagates(self):
        db, _, cur = _make_connected_db(autocommit=True)
        cur.execute.side_effect = _psycopg2.Error("is an aggregate function")
        with pytest.raises(_psycopg2.Error):
            db.get_routine_definition(1)


# ---------------------------------------------------------------------------
# get_view_definition()
# ---------------------------------------------------------------------------

class TestGetViewDefinition:
    """
    pg_get_viewdef() returns the SELECT body alone — not a statement.  The
    CREATE has to be rebuilt around it, which is where the quoting and the
    semicolon handling have to be right.
    """

    def _db(self, body=" SELECT id, name FROM users;"):
        db, _, _ = _make_connected_db(fetchone_return=(body,))
        return db

    def test_wraps_the_body_in_create_or_replace(self):
        sql = self._db().get_view_definition("public", "v_users", 30002)
        assert sql.startswith('CREATE OR REPLACE VIEW "public"."v_users" AS')

    def test_keeps_the_body(self):
        sql = self._db().get_view_definition("public", "v_users", 30002)
        assert "SELECT id, name FROM users" in sql

    def test_statement_is_terminated(self):
        sql = self._db().get_view_definition("public", "v_users", 30002)
        assert sql.rstrip().endswith(";")

    def test_does_not_double_the_semicolon(self):
        """pg_get_viewdef() ends the body with one; appending gives two."""
        sql = self._db("SELECT 1;").get_view_definition("public", "v", 1)
        assert not sql.rstrip().endswith(";;")

    def test_adds_a_semicolon_when_the_body_lacks_one(self):
        sql = self._db("SELECT 1").get_view_definition("public", "v", 1)
        assert sql.rstrip().endswith(";")

    def test_quotes_identifiers_that_need_it(self):
        sql = self._db().get_view_definition("My Schema", "Order Details", 1)
        assert '"My Schema"."Order Details"' in sql

    def test_escapes_an_embedded_quote(self):
        sql = self._db().get_view_definition("public", 'we"ird', 1)
        assert '"we""ird"' in sql

    def test_binds_the_oid_as_a_parameter(self):
        db, _, cur = _make_connected_db(fetchone_return=("SELECT 1",),
                                        autocommit=True)
        db.get_view_definition("public", "v", 30002)
        sql, params = cur.execute.call_args_list[0].args[:2]
        assert params == (30002,)
        assert "%s" in sql

    def test_requires_a_connection(self):
        with pytest.raises(RuntimeError):
            DatabaseManager().get_view_definition("public", "v", 1)

    def test_lookup_error_when_the_oid_has_no_row(self):
        db, _, _ = _make_connected_db(fetchone_return=None)
        with pytest.raises(LookupError):
            db.get_view_definition("public", "v", 999)

    def test_lookup_error_when_the_body_is_empty(self):
        db, _, _ = _make_connected_db(fetchone_return=("",))
        with pytest.raises(LookupError):
            db.get_view_definition("public", "v", 999)

    def test_driver_error_propagates(self):
        db, _, cur = _make_connected_db(autocommit=True)
        cur.execute.side_effect = _psycopg2.Error("permission denied")
        with pytest.raises(_psycopg2.Error):
            db.get_view_definition("public", "v", 1)

    # ── materialised views: no replace form exists ─────────────────────

    def test_materialised_view_is_not_create_or_replace(self):
        """
        PostgreSQL has no CREATE OR REPLACE MATERIALIZED VIEW.  Emitting one
        would hand the user a statement that cannot run.

        Asserted against the statement alone: the comment above it names the
        missing form in prose, which is not the same as emitting it.
        """
        sql = self._db().get_view_definition("public", "mv", 1, materialized=True)
        statement = sql[sql.index("CREATE MATERIALIZED VIEW"):]
        assert "CREATE OR REPLACE" not in statement

    def test_materialised_view_uses_the_plain_create(self):
        sql = self._db().get_view_definition("public", "mv", 1, materialized=True)
        assert 'CREATE MATERIALIZED VIEW "public"."mv" AS' in sql

    def test_materialised_view_warns_before_the_statement(self):
        """The warning has to be read before the statement is run, not after."""
        sql = self._db().get_view_definition("public", "mv", 1, materialized=True)
        assert sql.startswith("--")
        assert sql.index("--") < sql.index("CREATE MATERIALIZED VIEW")

    def test_materialised_view_warning_names_the_cost(self):
        sql = self._db().get_view_definition("public", "mv", 1, materialized=True)
        assert "DROP" in sql

    def test_every_warning_line_is_a_comment(self):
        """An un-commented prose line would be a syntax error on execute."""
        sql = self._db().get_view_definition("public", "mv", 1, materialized=True)
        preamble = sql.split("CREATE MATERIALIZED VIEW")[0]
        for line in preamble.splitlines():
            if line.strip():
                assert line.lstrip().startswith("--"), line

    def test_plain_view_carries_no_warning(self):
        sql = self._db().get_view_definition("public", "v", 1)
        assert not sql.startswith("--")
