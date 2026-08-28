"""
tests/test_recovery.py
~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the recovery/server-mode feature hardened in v1.0.7.

Key regressions guarded:
  1. pg_is_wal_replay_paused() must be wrapped in CASE WHEN pg_is_in_recovery()
     to avoid "Recovery control functions can only be executed during recovery"
     on a primary server.
  2. promote_standby() must fall back from pg_promote() to pg_wal_replay_resume()
     on PostgreSQL < 12.
  3. RecoveryDialog must show a green "Operating Normally" UI for primary servers
     and only enable the Promote button when actually in recovery.
  4. MainWindow footer must define _sb_primary_style / _sb_recovery_style and
     _check_recovery_on_connect().
"""
from __future__ import annotations

import ast
import sys
import types
from itertools import count
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# psycopg2 stub
# ---------------------------------------------------------------------------

def _make_psycopg2_stub():
    mod = types.ModuleType("psycopg2")
    mod.connect = MagicMock()

    class _Err(Exception):
        pgcode = None
        statement = None
    class _OpErr(_Err): pass
    class _ProgErr(_Err): pass
    class _DbErr(_Err): pass

    mod.Error            = _Err
    mod.OperationalError = _OpErr
    mod.ProgrammingError = _ProgErr
    mod.DatabaseError    = _DbErr

    extras = types.ModuleType("psycopg2.extras")
    exts   = types.ModuleType("psycopg2.extensions")
    exts.STATUS_IN_TRANSACTION = 1
    mod.extras     = extras
    mod.extensions = exts
    sys.modules.setdefault("psycopg2",            mod)
    sys.modules.setdefault("psycopg2.extras",     extras)
    sys.modules.setdefault("psycopg2.extensions", exts)
    # If a prior test already registered the stub, ensure ProgrammingError is present.
    existing = sys.modules.get("psycopg2")
    if existing and not hasattr(existing, "ProgrammingError"):
        existing.ProgrammingError = _ProgErr
    return existing if existing is not mod else mod


_psycopg2 = _make_psycopg2_stub()

from coruscant.core.database import DatabaseManager  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Column names returned by check_recovery_status() SQL, in order.
_RECOVERY_COLS = [
    "is_in_recovery", "last_wal_receive_lsn", "last_wal_replay_lsn",
    "last_xact_replay_ts", "replication_delay_secs", "server_start_time",
    "pg_version", "wal_replay_paused",
]


def _mock_col(name):
    c = MagicMock(); c.name = name; return c


def _make_db(fetchone=None, fetchall=None, exec_side_effect=None,
             description=None):
    db  = DatabaseManager()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__  = MagicMock(return_value=False)
    cur.fetchone.return_value  = fetchone
    cur.fetchall.return_value  = fetchall or []
    # Default description matches check_recovery_status() column list.
    cur.description = description if description is not None else [
        _mock_col(c) for c in _RECOVERY_COLS
    ]
    cur.rowcount    = -1
    if exec_side_effect is not None:
        cur.execute.side_effect = exec_side_effect

    ping = MagicMock()
    ping.__enter__ = MagicMock(return_value=ping)
    ping.__exit__  = MagicMock(return_value=False)

    conn = MagicMock()
    conn.closed     = 0
    conn.autocommit = True
    conn.encoding   = "utf-8"
    conn.status     = 1
    _n = count()
    conn.cursor.side_effect = lambda: ping if next(_n) == 0 else cur
    db._conn = conn
    return db, cur


def _src(rel):
    return (_ROOT / rel).read_text(encoding="utf-8")


def _tree(rel):
    return ast.parse(_src(rel))


def _fns(tree):
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _cls(tree):
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


# ===========================================================================
# 1. check_recovery_status() SQL safety on primary servers
# ===========================================================================

class TestCheckRecoveryStatusSQL:
    """Regression: pg_is_wal_replay_paused() must never be called bare on primary."""

    def test_case_guard_present_in_source(self):
        src = _src("coruscant/core/database.py")
        assert "CASE WHEN pg_is_in_recovery()" in src, (
            "database.py must wrap pg_is_wal_replay_paused() in "
            "CASE WHEN pg_is_in_recovery() ... ELSE NULL END"
        )

    def test_else_null_present_in_source(self):
        src = _src("coruscant/core/database.py")
        assert "ELSE NULL" in src

    def test_primary_server_returns_dict_no_exception(self):
        """is_in_recovery=False, wal_replay_paused=None (CASE returns NULL)."""
        row = (False, None, None, None, None, None, "16.2", None)
        db, _ = _make_db(fetchone=row)
        result = db.check_recovery_status()
        assert result["is_in_recovery"] is False
        assert result["wal_replay_paused"] is None

    def test_standby_server_returns_correct_fields(self):
        from datetime import datetime
        from datetime import datetime as _dt
        row = (
            True, "0/3000000", "0/2F00000", "2024-01-01T12:00:00",
            90, "2024-01-01T00:00:00", "15.4", False,
        )
        db, _ = _make_db(fetchone=row)
        result = db.check_recovery_status()
        assert result["is_in_recovery"] is True
        assert result["replication_delay_secs"] == 90
        assert result["pg_version"] == "15.4"

    def test_none_row_does_not_raise(self):
        db, _ = _make_db(fetchone=None)
        result = db.check_recovery_status()
        assert isinstance(result, dict)

    def test_method_exists(self):
        assert "check_recovery_status" in _fns(_tree("coruscant/core/database.py"))

    def test_promote_standby_exists(self):
        assert "promote_standby" in _fns(_tree("coruscant/core/database.py"))


# ===========================================================================
# 2. promote_standby() fallback logic
# ===========================================================================

class TestPromoteStandby:
    """pg_promote() -> ProgrammingError -> fallback to pg_wal_replay_resume()."""

    def test_calls_pg_promote_first(self):
        db, cur = _make_db()
        cur.fetchone.return_value = (True,)
        db.promote_standby()
        first_sql = cur.execute.call_args_list[0][0][0].strip()
        assert "pg_promote" in first_sql

    def test_falls_back_on_programming_error(self):
        n = count()

        def _exec(sql, *a, **kw):
            if next(n) == 0:
                raise _psycopg2.ProgrammingError("pg_promote() does not exist")

        db, cur = _make_db(exec_side_effect=_exec)
        cur.fetchone.return_value = (True,)
        db.promote_standby()   # must not raise

        all_sql = [c[0][0].strip() for c in cur.execute.call_args_list]
        assert any("pg_wal_replay_resume" in s for s in all_sql), (
            f"Expected pg_wal_replay_resume fallback, got: {all_sql}"
        )

    def test_source_contains_fallback_sql(self):
        assert "pg_wal_replay_resume" in _src("coruscant/core/database.py")

    def test_source_catches_programming_error(self):
        assert "ProgrammingError" in _src("coruscant/core/database.py")


# ===========================================================================
# 3. RecoveryDialog structure
# ===========================================================================

class TestRecoveryDialogStructure:

    def test_class_exists(self):
        assert "RecoveryDialog" in _cls(_tree("coruscant/ui/dialogs/recovery.py"))

    def test_status_worker_exists(self):
        assert "_StatusWorker" in _cls(_tree("coruscant/ui/dialogs/recovery.py"))

    def test_promote_worker_exists(self):
        assert "_PromoteWorker" in _cls(_tree("coruscant/ui/dialogs/recovery.py"))

    def test_on_status_defined(self):
        assert "_on_status" in _fns(_tree("coruscant/ui/dialogs/recovery.py"))

    def test_on_promote_defined(self):
        assert "_on_promote" in _fns(_tree("coruscant/ui/dialogs/recovery.py"))

    def test_refresh_defined(self):
        assert "_refresh" in _fns(_tree("coruscant/ui/dialogs/recovery.py"))

    def test_build_ui_defined(self):
        assert "_build_ui" in _fns(_tree("coruscant/ui/dialogs/recovery.py"))

    def test_promote_btn_present(self):
        assert "_promote_btn" in _src("coruscant/ui/dialogs/recovery.py")

    def test_strip_widget_present(self):
        assert "_strip" in _src("coruscant/ui/dialogs/recovery.py")

    def test_primary_happy_path_message_present(self):
        """Regression: dialog used to show an error on primary servers."""
        assert "Operating Normally" in _src("coruscant/ui/dialogs/recovery.py"), (
            "RecoveryDialog must show Operating Normally message for primary servers"
        )

    def test_green_color_for_primary_state(self):
        src = _src("coruscant/ui/dialogs/recovery.py").lower()
        assert "#2e7d32" in src, "Primary strip must use green #2e7d32"

    def test_promote_btn_setenabled_called(self):
        """Promote button must be conditionally disabled on primary servers."""
        assert "_promote_btn.setEnabled" in _src("coruscant/ui/dialogs/recovery.py")

    def test_window_title_is_server_mode(self):
        assert "Server Mode" in _src("coruscant/ui/dialogs/recovery.py")

    def test_minimum_height_set(self):
        assert "setMinimumHeight" in _src("coruscant/ui/dialogs/recovery.py")

    def test_scroll_area_uncapped(self):
        """Scroll area max height must be uncapped (QWIDGETSIZE_MAX or very large)."""
        src = _src("coruscant/ui/dialogs/recovery.py")
        assert "16777215" in src or "QWIDGETSIZE_MAX" in src, (
            "RecoveryDialog scroll area must be uncapped to match doctor window height"
        )


# ===========================================================================
# 4. MainWindow footer wiring
# ===========================================================================

class TestMainWindowRecoveryFooter:

    def test_sb_recovery_btn_defined(self):
        assert "_sb_recovery_btn" in _src("coruscant/ui/main_window.py")

    def test_sb_doctor_btn_defined(self):
        assert "_sb_doctor_btn" in _src("coruscant/ui/main_window.py")

    def test_check_recovery_on_connect_defined(self):
        assert "_check_recovery_on_connect" in _fns(_tree("coruscant/ui/main_window.py"))

    def test_sb_primary_style_defined(self):
        assert "_sb_primary_style" in _fns(_tree("coruscant/ui/main_window.py"))

    def test_sb_recovery_style_defined(self):
        assert "_sb_recovery_style" in _fns(_tree("coruscant/ui/main_window.py"))

    def test_primary_style_uses_green(self):
        assert "#2e7d32" in _src("coruscant/ui/main_window.py").lower()

    def test_recovery_style_uses_red(self):
        src = _src("coruscant/ui/main_window.py").lower()
        assert "#b71c1c" in src or "#c62828" in src

    def test_on_recovery_defined(self):
        assert "_on_recovery" in _fns(_tree("coruscant/ui/main_window.py"))

    def test_on_database_doctor_defined(self):
        assert "_on_database_doctor" in _fns(_tree("coruscant/ui/main_window.py"))

    def test_update_ui_state_references_both_footer_btns(self):
        src = _src("coruscant/ui/main_window.py")
        assert "_sb_doctor_btn" in src
        assert "_sb_recovery_btn" in src


# ===========================================================================
# 5. doctor.py structure
# ===========================================================================

class TestDoctorStructure:

    def test_dialog_class_exists(self):
        assert "DatabaseDoctorDialog" in _cls(_tree("coruscant/ui/dialogs/doctor.py"))

    def test_diagnosis_worker_exists(self):
        assert "_DiagnosisWorker" in _cls(_tree("coruscant/ui/dialogs/doctor.py"))

    def test_repair_worker_exists(self):
        assert "_RepairWorker" in _cls(_tree("coruscant/ui/dialogs/doctor.py"))

    def test_core_doctor_parses(self):
        ast.parse(_src("coruscant/core/doctor.py"))

    def test_severity_functions_present(self):
        fns = _fns(_tree("coruscant/core/doctor.py"))
        for fn in ("assess_locks", "assess_bloat", "assess_connections", "assess_wraparound"):
            assert fn in fns, f"core/doctor.py missing {fn}"

    def test_sql_constants_present(self):
        src = _src("coruscant/core/doctor.py")
        for c in ("LOCKS_SQL", "BLOAT_SQL", "CONN_SUMMARY_SQL", "WRAPAROUND_SQL"):
            assert c in src, f"core/doctor.py missing {c}"

    def test_bloat_sql_uses_real_pg_stat_user_tables_columns(self):
        """
        BLOAT_SQL must only reference columns that pg_stat_user_tables actually
        has.  It shipped selecting `tablename`, which belongs to pg_tables — the
        statistics view calls it `relname` — so the Table Bloat health check
        raised 'column "tablename" does not exist' on every run and the card
        always rendered as an error.  `test_sql_constants_present` did not catch
        it because the constant existed; only its contents were wrong.
        """
        import re
        from coruscant.core.doctor import BLOAT_SQL

        # Columns of pg_stat_user_tables, stable across supported PostgreSQL
        # versions (PG 12+).  Anything outside this set is a typo or a column
        # borrowed from a different catalog view.
        valid = {
            "relid", "schemaname", "relname",
            "seq_scan", "seq_tup_read", "idx_scan", "idx_tup_fetch",
            "n_tup_ins", "n_tup_upd", "n_tup_del", "n_tup_hot_upd",
            "n_live_tup", "n_dead_tup", "n_mod_since_analyze",
            "n_ins_since_vacuum",
            "last_vacuum", "last_autovacuum", "last_analyze", "last_autoanalyze",
            "vacuum_count", "autovacuum_count", "analyze_count", "autoanalyze_count",
        }
        # SQL keywords, functions, and output aliases that are not source columns.
        ignore = {
            "select", "from", "where", "order", "by", "limit", "case", "when",
            "then", "else", "end", "and", "or", "as", "desc", "asc", "round",
            "coalesce", "greatest", "text", "never", "null",
            "schema", "table", "dead_tuples", "live_tuples", "dead_pct",
            "last_vacuum", "pg_stat_user_tables",
        }
        assert "pg_stat_user_tables" in BLOAT_SQL
        idents = {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", BLOAT_SQL)}
        unknown = sorted(idents - valid - ignore)
        assert not unknown, (
            "BLOAT_SQL references identifiers that are not columns of "
            f"pg_stat_user_tables: {unknown}"
        )
        assert "tablename" not in BLOAT_SQL, (
            "pg_stat_user_tables has no 'tablename' column — use 'relname'"
        )


# ===========================================================================
# 6. DatabaseManager repair methods
# ===========================================================================

class TestDatabaseManagerRepairMethods:

    def test_kill_connection_defined(self):
        assert "kill_connection" in _fns(_tree("coruscant/core/database.py"))

    def test_vacuum_table_defined(self):
        assert "vacuum_table" in _fns(_tree("coruscant/core/database.py"))

    def test_terminate_connections_defined(self):
        assert "terminate_connections" in _fns(_tree("coruscant/core/database.py"))

    def test_vacuum_freeze_defined(self):
        assert "vacuum_freeze" in _fns(_tree("coruscant/core/database.py"))

    def test_vacuum_uses_autocommit_toggle(self):
        """VACUUM cannot run in a transaction; must toggle autocommit."""
        assert "autocommit" in _src("coruscant/core/database.py")

    def test_autocommit_restored_in_finally(self):
        assert "finally" in _src("coruscant/core/database.py")
