"""
Tests for coruscant.core.database.

All tests use unittest.mock — no live PostgreSQL connection required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import psycopg2
import pytest

from coruscant.core.database import (
    DatabaseManager,
    QueryResult,
    CommandResult,
    PGCODE_QUERY_CANCELED,
)


# ---------------------------------------------------------------------------
# Helpers
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
    Return a DatabaseManager whose _conn is fully mocked.
    By default the cursor simulates a non-SELECT result (description=None).
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

    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_conn.autocommit = autocommit
    mock_conn.encoding = "utf-8"
    mock_conn.cursor.return_value = mock_cursor

    db._conn = mock_conn
    return db, mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class TestQueryResult:
    def test_attributes(self):
        qr = QueryResult("Query 1", ["id", "name"], [(1, "Alice")], 12.5, False)
        assert qr.label == "Query 1"
        assert qr.columns == ["id", "name"]
        assert qr.rows == [(1, "Alice")]
        assert qr.elapsed_ms == 12.5
        assert qr.truncated is False

    def test_truncated_flag(self):
        qr = QueryResult("Q", ["x"], [], 0.0, True)
        assert qr.truncated is True


class TestCommandResult:
    def test_attributes(self):
        cr = CommandResult("Query 2", "Rows affected: 7", 3.0)
        assert cr.label == "Query 2"
        assert cr.message == "Rows affected: 7"
        assert cr.elapsed_ms == 3.0


# ---------------------------------------------------------------------------
# Connection state
# ---------------------------------------------------------------------------

class TestIsConnected:
    def test_false_when_no_connection(self):
        db = DatabaseManager()
        assert db.is_connected is False

    def test_true_when_conn_open(self):
        db, mock_conn, _ = _make_connected_db()
        assert db.is_connected is True

    def test_false_when_conn_closed(self):
        db = DatabaseManager()
        mock_conn = MagicMock()
        mock_conn.closed = True
        db._conn = mock_conn
        assert db.is_connected is False


class TestDisconnect:
    def test_safe_when_not_connected(self):
        db = DatabaseManager()
        db.disconnect()  # must not raise

    def test_closes_open_connection(self):
        db, mock_conn, _ = _make_connected_db()
        db.disconnect()
        mock_conn.close.assert_called_once()
        assert db._conn is None

    def test_safe_to_call_twice(self):
        db, mock_conn, _ = _make_connected_db()
        db.disconnect()
        db.disconnect()  # second call — conn is already None, must not raise


class TestCancel:
    def test_safe_when_not_connected(self):
        db = DatabaseManager()
        db.cancel()  # must not raise

    def test_calls_conn_cancel(self):
        db, mock_conn, _ = _make_connected_db()
        db.cancel()
        mock_conn.cancel.assert_called_once()

    def test_swallows_exception_from_cancel(self):
        db, mock_conn, _ = _make_connected_db()
        mock_conn.cancel.side_effect = Exception("already gone")
        db.cancel()  # must not propagate


# ---------------------------------------------------------------------------
# Transaction control guards (not connected)
# ---------------------------------------------------------------------------

class TestTransactionGuards:
    def test_set_autocommit_raises(self):
        db = DatabaseManager()
        with pytest.raises(RuntimeError, match="Not connected"):
            db.set_autocommit(False)

    def test_commit_raises(self):
        db = DatabaseManager()
        with pytest.raises(RuntimeError, match="Not connected"):
            db.commit()

    def test_rollback_raises(self):
        db = DatabaseManager()
        with pytest.raises(RuntimeError, match="Not connected"):
            db.rollback()

    def test_get_schema_tree_raises(self):
        db = DatabaseManager()
        with pytest.raises(RuntimeError, match="Not connected"):
            db.get_schema_tree()


class TestTransactionConnected:
    def test_set_autocommit_delegates(self):
        db, mock_conn, _ = _make_connected_db()
        db.set_autocommit(False)
        assert mock_conn.autocommit is False

    def test_commit_delegates(self):
        db, mock_conn, _ = _make_connected_db()
        db.commit()
        mock_conn.commit.assert_called_once()

    def test_rollback_delegates(self):
        db, mock_conn, _ = _make_connected_db()
        db.rollback()
        mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# execute() — input validation
# ---------------------------------------------------------------------------

class TestExecuteValidation:
    def test_raises_when_not_connected(self):
        db = DatabaseManager()
        with pytest.raises(RuntimeError, match="Not connected"):
            db.execute("SELECT 1")

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
        assert r.label == "Query 1"
        assert r.columns == ["id", "name"]
        assert r.rows == [(1, "Alice"), (2, "Bob")]
        assert r.truncated is False

    def test_elapsed_ms_is_non_negative(self):
        db, _, _ = _make_connected_db(
            description=[_mock_col("x")],
            fetchall_return=[(1,)],
        )
        results = db.execute("SELECT 1 AS x")
        assert results[0].elapsed_ms >= 0

    def test_not_truncated_when_no_extra_row(self):
        db, _, mock_cursor = _make_connected_db(
            description=[_mock_col("id")],
            fetchmany_return=[(1,)],
            fetchone_return=None,   # no extra row
        )
        results = db.execute("SELECT id FROM t", row_limit=10)
        assert results[0].truncated is False

    def test_truncated_when_extra_row_exists(self):
        db, _, mock_cursor = _make_connected_db(
            description=[_mock_col("id")],
            fetchmany_return=[(1,), (2,)],
            fetchone_return=(3,),   # extra row beyond limit
        )
        results = db.execute("SELECT id FROM t", row_limit=2)
        assert results[0].truncated is True

    def test_row_limit_zero_uses_fetchall(self):
        db, _, mock_cursor = _make_connected_db(
            description=[_mock_col("id")],
            fetchall_return=[(1,), (2,), (3,)],
        )
        db.execute("SELECT id FROM t", row_limit=0)
        mock_cursor.fetchall.assert_called_once()
        mock_cursor.fetchmany.assert_not_called()


# ---------------------------------------------------------------------------
# execute() — DML / DDL results
# ---------------------------------------------------------------------------

class TestExecuteCommand:
    def test_returns_command_result(self):
        db, _, mock_cursor = _make_connected_db(description=None, rowcount=5)
        results = db.execute("DELETE FROM t WHERE id = 1")
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, CommandResult)
        assert r.label == "Query 1"
        assert "5" in r.message

    def test_rowcount_negative_shown_as_na(self):
        db, _, mock_cursor = _make_connected_db(description=None, rowcount=-1)
        results = db.execute("CREATE INDEX idx ON t(id)")
        assert "N/A" in results[0].message


# ---------------------------------------------------------------------------
# execute() — multiple statements
# ---------------------------------------------------------------------------

class TestExecuteMultiple:
    def test_two_selects_produce_two_results(self):
        db, _, mock_cursor = _make_connected_db(
            description=[_mock_col("n")],
            fetchall_return=[(1,)],
        )
        results = db.execute("SELECT 1; SELECT 2;")
        assert len(results) == 2
        assert results[0].label == "Query 1"
        assert results[1].label == "Query 2"

    def test_mixed_select_and_dml(self):
        db, _, mock_cursor = _make_connected_db()

        call_count = 0

        def dynamic_description():
            return [_mock_col("id")] if call_count % 2 == 0 else None

        # Alternate SELECT / DML by toggling description per execute call
        original_execute = mock_cursor.execute.side_effect

        results_acc = []

        def patched_execute(sql, *args, **kwargs):
            nonlocal call_count
            if call_count == 0:
                mock_cursor.description = [_mock_col("id")]
                mock_cursor.fetchall.return_value = [(1,)]
            else:
                mock_cursor.description = None
                mock_cursor.rowcount = 3
            call_count += 1

        mock_cursor.execute.side_effect = patched_execute

        results = db.execute("SELECT id FROM t; DELETE FROM t WHERE id = 1;")
        assert len(results) == 2
        assert isinstance(results[0], QueryResult)
        assert isinstance(results[1], CommandResult)


# ---------------------------------------------------------------------------
# execute() — error handling
# ---------------------------------------------------------------------------

class TestExecuteErrors:
    def test_db_error_propagates(self):
        db, _, mock_cursor = _make_connected_db()
        mock_cursor.execute.side_effect = psycopg2.OperationalError("boom")
        with pytest.raises(psycopg2.OperationalError):
            db.execute("SELECT 1")

    def test_closed_connection_nulled_after_error(self):
        from unittest.mock import PropertyMock
        db, mock_conn, mock_cursor = _make_connected_db()
        mock_cursor.execute.side_effect = psycopg2.OperationalError("lost")
        # closed returns False on the first check (is_connected guard at top of
        # execute) and True on the second check (inside the except handler).
        type(mock_conn).closed = PropertyMock(side_effect=[False, True])
        with pytest.raises(psycopg2.OperationalError):
            db.execute("SELECT 1")
        assert db._conn is None
        assert db.is_connected is False

    def test_cancelled_query_pgcode(self):
        """PGCODE_QUERY_CANCELED constant must match PostgreSQL SQLSTATE 57014."""
        assert PGCODE_QUERY_CANCELED == "57014"


# ---------------------------------------------------------------------------
# connect() — delegates to psycopg2.connect
# ---------------------------------------------------------------------------

class TestConnect:
    def test_calls_psycopg2_connect(self):
        db = DatabaseManager()
        mock_conn = MagicMock()
        mock_conn.closed = False

        with patch("coruscant.core.database.psycopg2.connect", return_value=mock_conn) as mock_connect:
            db.connect(
                host="localhost",
                port=5432,
                database="testdb",
                user="alice",
                password="secret",
                ssl_mode="prefer",
            )

        mock_connect.assert_called_once_with(
            host="localhost",
            port=5432,
            dbname="testdb",
            user="alice",
            password="secret",
            connect_timeout=10,
            sslmode="prefer",
        )
        assert db._conn is mock_conn

    def test_sets_autocommit_true_after_connect(self):
        db = DatabaseManager()
        mock_conn = MagicMock()
        mock_conn.closed = False

        with patch("coruscant.core.database.psycopg2.connect", return_value=mock_conn):
            db.connect("localhost", 5432, "db", "user", "pw")

        assert mock_conn.autocommit is True

    def test_closes_existing_connection_before_reconnect(self):
        db = DatabaseManager()
        old_conn = MagicMock()
        old_conn.closed = False
        db._conn = old_conn

        new_conn = MagicMock()
        new_conn.closed = False

        with patch("coruscant.core.database.psycopg2.connect", return_value=new_conn):
            db.connect("localhost", 5432, "db", "user", "pw")

        old_conn.close.assert_called_once()
        assert db._conn is new_conn

    def test_propagates_operational_error(self):
        db = DatabaseManager()
        with patch(
            "coruscant.core.database.psycopg2.connect",
            side_effect=psycopg2.OperationalError("refused"),
        ):
            with pytest.raises(psycopg2.OperationalError):
                db.connect("bad-host", 5432, "db", "user", "pw")
