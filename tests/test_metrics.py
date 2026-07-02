"""
tests/test_metrics.py
~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the Live Database Monitor metrics layer added in v1.0.8.

`coruscant.core.metrics` has zero GUI/driver imports, so these are real
behavioural tests (not just AST checks): they exercise rate computation,
counter-reset handling, the DBSTATS column mapping, and the formatting
helpers directly.
"""
from __future__ import annotations

import ast
from pathlib import Path

import coruscant.core.metrics as m

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# SQL constants and query registry
# ---------------------------------------------------------------------------

class TestSQLConstants:

    def test_instant_gauge_sql_present(self):
        assert "current_database()" in m.GLOBAL_SQL
        assert "max_connections" in m.GLOBAL_SQL
        assert "pg_stat_database" in m.DBSTATS_SQL

    def test_detail_queries_expected_keys(self):
        expected = {
            "activity", "conn_state", "conn_user", "tables", "indexes",
            "table_cache", "databases", "locks", "replication", "settings",
        }
        assert expected == set(m.DETAIL_QUERIES)

    def test_all_detail_queries_are_nonempty_strings(self):
        for key, sql in m.DETAIL_QUERIES.items():
            assert isinstance(sql, str) and sql.strip(), f"{key} SQL is empty"

    def test_statements_sql_targets_pg_stat_statements(self):
        assert "pg_stat_statements" in m.STATEMENTS_SQL

    def test_activity_excludes_own_backend(self):
        assert "pg_backend_pid()" in m.ACTIVITY_SQL


# ---------------------------------------------------------------------------
# dbstats_to_dict
# ---------------------------------------------------------------------------

class TestDbstatsToDict:

    def _row(self):
        # Order must match DBSTATS_SQL SELECT list.
        return (
            7,          # numbackends
            1000,       # xact_commit
            5,          # xact_rollback
            200,        # blks_read
            9800,       # blks_hit
            50000,      # tup_returned
            40000,      # tup_fetched
            300,        # tup_inserted
            120,        # tup_updated
            30,         # tup_deleted
            0,          # conflicts
            1,          # deadlocks
            4,          # temp_files
            8192,       # temp_bytes
            0.0,        # blk_read_time
            0.0,        # blk_write_time
            98.0,       # cache_hit_pct
            "2026-07-01 00:00:00+00",  # stats_reset
        )

    def test_maps_named_fields(self):
        d = m.dbstats_to_dict(self._row())
        assert d["numbackends"] == 7
        assert d["xact_commit"] == 1000
        assert d["deadlocks"] == 1
        assert d["cache_hit_pct"] == 98.0
        assert d["stats_reset"].startswith("2026-07-01")


# ---------------------------------------------------------------------------
# compute_rates
# ---------------------------------------------------------------------------

def _stats(**over):
    base = dict(
        xact_commit=0, xact_rollback=0, blks_read=0, blks_hit=0,
        tup_returned=0, tup_fetched=0, tup_inserted=0, tup_updated=0,
        tup_deleted=0, deadlocks=0, temp_files=0,
    )
    base.update(over)
    return base


class TestComputeRates:

    def test_first_sample_is_invalid(self):
        r = m.compute_rates(None, _stats(xact_commit=10), 5.0)
        assert r.valid is False
        assert r.tps == 0.0

    def test_zero_interval_is_invalid(self):
        r = m.compute_rates(_stats(), _stats(xact_commit=10), 0.0)
        assert r.valid is False

    def test_tps_is_commits_plus_rollbacks_per_second(self):
        prev = _stats(xact_commit=100, xact_rollback=0)
        curr = _stats(xact_commit=140, xact_rollback=10)
        r = m.compute_rates(prev, curr, 2.0)
        assert r.valid is True
        assert r.tps == 25.0          # (40 + 10) / 2
        assert r.commits == 20.0      # 40 / 2
        assert r.rollbacks == 5.0     # 10 / 2

    def test_interval_cache_hit_ratio(self):
        prev = _stats(blks_hit=1000, blks_read=0)
        curr = _stats(blks_hit=1090, blks_read=10)   # +90 hit, +10 read
        r = m.compute_rates(prev, curr, 1.0)
        assert r.interval_cache_hit == 90.0

    def test_cache_hit_defaults_to_100_when_no_io(self):
        r = m.compute_rates(_stats(), _stats(), 1.0)
        assert r.interval_cache_hit == 100.0

    def test_counter_reset_yields_invalid(self):
        # Counters going backwards => stats were reset; do not emit a spike.
        prev = _stats(xact_commit=1000)
        curr = _stats(xact_commit=5)
        r = m.compute_rates(prev, curr, 1.0)
        assert r.valid is False

    def test_tuple_write_rates(self):
        prev = _stats(tup_inserted=0, tup_updated=0, tup_deleted=0)
        curr = _stats(tup_inserted=100, tup_updated=40, tup_deleted=10)
        r = m.compute_rates(prev, curr, 10.0)
        assert r.rows_inserted == 10.0
        assert r.rows_updated == 4.0
        assert r.rows_deleted == 1.0


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

class TestFormatters:

    def test_fmt_duration_seconds(self):
        assert m.fmt_duration(45) == "45s"

    def test_fmt_duration_minutes(self):
        assert m.fmt_duration(125) == "2m 05s"

    def test_fmt_duration_hours(self):
        assert m.fmt_duration(3725) == "1h 02m"

    def test_fmt_duration_days(self):
        assert m.fmt_duration(200000).startswith("2d")

    def test_fmt_duration_none(self):
        assert m.fmt_duration(None) == "—"

    def test_fmt_count_scales(self):
        assert m.fmt_count(999) == "999"
        assert m.fmt_count(1500) == "1.5K"
        assert m.fmt_count(1_500_000) == "1.5M"
        assert m.fmt_count(2_000_000_000) == "2.0B"

    def test_fmt_count_none(self):
        assert m.fmt_count(None) == "—"

    def test_fmt_rate_suffix(self):
        assert m.fmt_rate(1500) == "1.5K/s"
        assert m.fmt_rate(None) == "—"


# ---------------------------------------------------------------------------
# Source integrity (guards against Edit-tool truncation)
# ---------------------------------------------------------------------------

def test_metrics_source_not_truncated():
    src = (_ROOT / "coruscant/core/metrics.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = {n.name for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef)}
    for fn in ("compute_rates", "dbstats_to_dict", "fmt_duration",
               "fmt_count", "fmt_rate"):
        assert fn in fns, f"metrics.py missing {fn} — file may be truncated"


def test_core_metrics_has_no_gui_imports():
    """Architecture rule: core/ must never import PySide6/Qt."""
    src = (_ROOT / "coruscant/core/metrics.py").read_text(encoding="utf-8")
    assert "PySide6" not in src
    assert "QtWidgets" not in src
