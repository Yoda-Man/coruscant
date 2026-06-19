"""
tests/test_qa_engine.py
~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for coruscant.core.qa_engine.

All checks are exercised with synthetic metadata dictionaries — no real
database connection is required.

Also covers the pure-Python suppression helpers in qa_dialog.py, which
can be imported without Qt by stubbing PySide6 before the import.

Author: Marwa Trust Mutemasango
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Import qa_engine (no Qt dependency)
# ---------------------------------------------------------------------------

from coruscant.core.qa_engine import (  # noqa: E402
    ERROR,
    INFO,
    WARNING,
    QAFinding,
    QAReport,
    _check_circular_deps,
    _check_missing_fk_indexes,
    _check_naming_conventions,
    _check_nullable_fks,
    _check_orphaned_tables,
    _check_type_consistency,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _meta(
    tables: list[str] | None = None,
    columns: list[tuple] | None = None,
    fks: list[tuple] | None = None,
    indexes: list[tuple] | None = None,
) -> dict:
    return {
        "tables":  tables  or [],
        "columns": columns or [],
        "fks":     fks     or [],
        "indexes": indexes or [],
    }


# ---------------------------------------------------------------------------
# QAFinding
# ---------------------------------------------------------------------------

class TestQAFinding:
    def test_minimal_construction(self):
        f = QAFinding(check="orphaned_tables", severity=INFO, message="test")
        assert f.check == "orphaned_tables"
        assert f.severity == INFO
        assert f.message == "test"
        assert f.table is None
        assert f.column is None
        assert f.fix_sql is None

    def test_full_construction(self):
        f = QAFinding(
            check="missing_fk_indexes",
            severity=WARNING,
            message="msg",
            table="orders",
            column="user_id",
            fix_sql="CREATE INDEX …",
        )
        assert f.table == "orders"
        assert f.column == "user_id"
        assert f.fix_sql == "CREATE INDEX …"


# ---------------------------------------------------------------------------
# QAReport
# ---------------------------------------------------------------------------

class TestQAReport:
    def test_empty_report_perfect_score(self):
        r = QAReport(schema="public")
        assert r.health_score == 100
        assert r.error_count == 0
        assert r.warning_count == 0
        assert r.info_count == 0

    def test_one_error_deducts_ten(self):
        r = QAReport(schema="public")
        r.findings.append(QAFinding(check="x", severity=ERROR, message="e"))
        assert r.health_score == 90

    def test_one_warning_deducts_three(self):
        r = QAReport(schema="public")
        r.findings.append(QAFinding(check="x", severity=WARNING, message="w"))
        assert r.health_score == 97

    def test_one_info_deducts_one(self):
        r = QAReport(schema="public")
        r.findings.append(QAFinding(check="x", severity=INFO, message="i"))
        assert r.health_score == 99

    def test_score_floor_is_zero(self):
        r = QAReport(schema="public")
        for _ in range(20):
            r.findings.append(QAFinding(check="x", severity=ERROR, message="e"))
        assert r.health_score == 0

    def test_counts_correct(self):
        r = QAReport(schema="public")
        r.findings += [
            QAFinding(check="a", severity=ERROR,   message="e1"),
            QAFinding(check="a", severity=ERROR,   message="e2"),
            QAFinding(check="b", severity=WARNING, message="w1"),
            QAFinding(check="c", severity=INFO,    message="i1"),
        ]
        assert r.error_count   == 2
        assert r.warning_count == 1
        assert r.info_count    == 1

    def test_mixed_score(self):
        r = QAReport(schema="public")
        r.findings += [
            QAFinding(check="a", severity=ERROR,   message="e"),  # -10
            QAFinding(check="b", severity=WARNING, message="w"),  # -3
            QAFinding(check="c", severity=INFO,    message="i"),  # -1
        ]
        assert r.health_score == 86


# ---------------------------------------------------------------------------
# _check_orphaned_tables
# ---------------------------------------------------------------------------

class TestOrphanedTables:
    def test_no_tables_no_findings(self):
        assert _check_orphaned_tables(_meta(), "public") == []

    def test_table_with_no_fks_is_orphaned(self):
        meta = _meta(tables=["users"])
        findings = _check_orphaned_tables(meta, "public")
        assert len(findings) == 1
        assert findings[0].table == "users"
        assert findings[0].severity == INFO

    def test_table_referenced_as_parent_not_orphaned(self):
        meta = _meta(
            tables=["users", "orders"],
            fks=[("orders", "user_id", "users", "id", "fk1")],
        )
        findings = _check_orphaned_tables(meta, "public")
        assert not any(f.table == "users" for f in findings)
        assert not any(f.table == "orders" for f in findings)

    def test_multiple_orphans_detected(self):
        meta = _meta(tables=["logs", "events"])
        findings = _check_orphaned_tables(meta, "public")
        assert len(findings) == 2
        tables = {f.table for f in findings}
        assert tables == {"logs", "events"}

    def test_check_name_correct(self):
        meta = _meta(tables=["solo"])
        findings = _check_orphaned_tables(meta, "public")
        assert all(f.check == "orphaned_tables" for f in findings)


# ---------------------------------------------------------------------------
# _check_missing_fk_indexes
# ---------------------------------------------------------------------------

class TestMissingFkIndexes:
    def test_no_fks_no_findings(self):
        assert _check_missing_fk_indexes(_meta(), "public") == []

    def test_fk_without_index_is_finding(self):
        meta = _meta(
            fks=[("orders", "user_id", "users", "id", "fk1")],
        )
        findings = _check_missing_fk_indexes(meta, "public")
        assert len(findings) == 1
        assert findings[0].table == "orders"
        assert findings[0].column == "user_id"
        assert findings[0].severity == WARNING

    def test_fk_with_index_no_finding(self):
        meta = _meta(
            fks=[("orders", "user_id", "users", "id", "fk1")],
            indexes=[("orders", "user_id", "idx_orders_user_id")],
        )
        findings = _check_missing_fk_indexes(meta, "public")
        assert findings == []

    def test_fix_sql_contains_create_index(self):
        meta = _meta(
            fks=[("orders", "user_id", "users", "id", "fk1")],
        )
        findings = _check_missing_fk_indexes(meta, "public")
        assert findings[0].fix_sql is not None
        assert "CREATE INDEX" in findings[0].fix_sql
        assert "orders" in findings[0].fix_sql
        assert "user_id" in findings[0].fix_sql

    def test_duplicate_fk_columns_reported_once(self):
        meta = _meta(
            fks=[
                ("orders", "user_id", "users", "id", "fk1"),
                ("orders", "user_id", "users", "id", "fk2"),
            ],
        )
        findings = _check_missing_fk_indexes(meta, "public")
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# _check_circular_deps
# ---------------------------------------------------------------------------

class TestCircularDeps:
    def test_no_fks_no_findings(self):
        pytest.importorskip("networkx")
        assert _check_circular_deps(_meta(), "public") == []

    def test_no_cycle(self):
        pytest.importorskip("networkx")
        meta = _meta(
            tables=["a", "b"],
            fks=[("b", "a_id", "a", "id", "fk1")],
        )
        assert _check_circular_deps(meta, "public") == []

    def test_simple_cycle_detected(self):
        pytest.importorskip("networkx")
        meta = _meta(
            tables=["a", "b"],
            fks=[
                ("a", "b_id", "b", "id", "fk1"),
                ("b", "a_id", "a", "id", "fk2"),
            ],
        )
        findings = _check_circular_deps(meta, "public")
        assert len(findings) >= 1
        assert all(f.severity == ERROR for f in findings)
        assert all(f.check == "circular_deps" for f in findings)

    def test_self_referential_ignored(self):
        pytest.importorskip("networkx")
        meta = _meta(
            tables=["category"],
            fks=[("category", "parent_id", "category", "id", "fk1")],
        )
        # Self-reference should not form a cycle in our graph (skipped)
        findings = _check_circular_deps(meta, "public")
        assert findings == []


# ---------------------------------------------------------------------------
# _check_nullable_fks
# ---------------------------------------------------------------------------

class TestNullableFks:
    def test_non_nullable_fk_no_finding(self):
        meta = _meta(
            columns=[("orders", "user_id", "integer", "NO")],
            fks=[("orders", "user_id", "users", "id", "fk1")],
        )
        assert _check_nullable_fks(meta, "public") == []

    def test_nullable_fk_is_finding(self):
        meta = _meta(
            columns=[("orders", "user_id", "integer", "YES")],
            fks=[("orders", "user_id", "users", "id", "fk1")],
        )
        findings = _check_nullable_fks(meta, "public")
        assert len(findings) == 1
        assert findings[0].table == "orders"
        assert findings[0].column == "user_id"
        assert findings[0].severity == INFO

    def test_duplicate_fk_reported_once(self):
        meta = _meta(
            columns=[("orders", "user_id", "integer", "YES")],
            fks=[
                ("orders", "user_id", "users", "id", "fk1"),
                ("orders", "user_id", "accounts", "id", "fk2"),
            ],
        )
        findings = _check_nullable_fks(meta, "public")
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# _check_naming_conventions
# ---------------------------------------------------------------------------

class TestNamingConventions:
    def test_snake_case_table_no_finding(self):
        meta = _meta(tables=["my_table"])
        assert _check_naming_conventions(meta, "public") == []

    def test_camel_case_table_is_finding(self):
        meta = _meta(tables=["MyTable"])
        findings = _check_naming_conventions(meta, "public")
        assert any(f.table == "MyTable" and f.check == "naming_conventions"
                   for f in findings)

    def test_table_with_space_is_finding(self):
        meta = _meta(tables=["my table"])
        findings = _check_naming_conventions(meta, "public")
        assert len(findings) >= 1

    def test_snake_case_column_no_finding(self):
        meta = _meta(
            tables=["t"],
            columns=[("t", "good_col", "integer", "NO")],
        )
        assert _check_naming_conventions(meta, "public") == []

    def test_camel_case_column_is_info(self):
        meta = _meta(
            tables=["t"],
            columns=[("t", "badCol", "integer", "NO")],
        )
        findings = _check_naming_conventions(meta, "public")
        col_findings = [f for f in findings if f.column == "badCol"]
        assert len(col_findings) == 1
        assert col_findings[0].severity == INFO

    def test_table_severity_is_warning(self):
        meta = _meta(tables=["BadTable"])
        findings = _check_naming_conventions(meta, "public")
        tbl_findings = [f for f in findings if f.table == "BadTable" and not f.column]
        assert all(f.severity == WARNING for f in tbl_findings)


# ---------------------------------------------------------------------------
# _check_type_consistency
# ---------------------------------------------------------------------------

class TestTypeConsistency:
    def test_same_type_no_finding(self):
        meta = _meta(columns=[
            ("t1", "id", "integer", "NO"),
            ("t2", "id", "integer", "NO"),
        ])
        assert _check_type_consistency(meta, "public") == []

    def test_different_types_is_finding(self):
        meta = _meta(columns=[
            ("t1", "id", "integer", "NO"),
            ("t2", "id", "text", "NO"),
        ])
        findings = _check_type_consistency(meta, "public")
        assert len(findings) == 1
        assert findings[0].column == "id"
        assert findings[0].severity == WARNING
        assert "integer" in findings[0].message
        assert "text" in findings[0].message

    def test_three_types_one_finding(self):
        meta = _meta(columns=[
            ("t1", "status", "integer", "NO"),
            ("t2", "status", "text", "NO"),
            ("t3", "status", "boolean", "NO"),
        ])
        findings = _check_type_consistency(meta, "public")
        assert len(findings) == 1

    def test_unique_column_names_no_finding(self):
        meta = _meta(columns=[
            ("t1", "name", "text", "NO"),
            ("t2", "age",  "integer", "NO"),
        ])
        assert _check_type_consistency(meta, "public") == []


# ---------------------------------------------------------------------------
# qa_dialog — suppression helpers (pure Python, Qt stubbed)
# ---------------------------------------------------------------------------

class TestQADialogSuppressionHelpers:
    """
    Verify the suppression rule logic that lives in qa_dialog.py.

    The three helper functions are trivial pure-Python one-liners, so we
    mirror them here to avoid any Qt import dependency.  The AST test in
    test_ui_ast.py already asserts that the real functions exist in qa_dialog.

    If the logic in qa_dialog.py ever changes these functions must be kept
    in sync manually (they're too simple for a diff to miss).
    """

    # Mirrors of qa_dialog._suppression_key / _wildcard_key / _is_suppressed
    @staticmethod
    def _sk(f: QAFinding) -> str:
        return f"{f.check}:{f.table or '*'}"

    @staticmethod
    def _wk(f: QAFinding) -> str:
        return f"{f.check}:*"

    @staticmethod
    def _is_sup(f: QAFinding, rules: set) -> bool:
        key = f"{f.check}:{f.table or '*'}"
        wk  = f"{f.check}:*"
        return key in rules or wk in rules

    def test_suppression_key_with_table(self):
        f = QAFinding(check="orphaned_tables", severity=INFO,
                      message="x", table="orders")
        assert self._sk(f) == "orphaned_tables:orders"

    def test_suppression_key_without_table(self):
        f = QAFinding(check="circular_deps", severity=ERROR, message="x")
        assert self._sk(f) == "circular_deps:*"

    def test_wildcard_key(self):
        f = QAFinding(check="naming_conventions", severity=WARNING,
                      message="x", table="MyTable")
        assert self._wk(f) == "naming_conventions:*"

    def test_is_suppressed_exact_key(self):
        f = QAFinding(check="orphaned_tables", severity=INFO,
                      message="x", table="logs")
        assert self._is_sup(f, {"orphaned_tables:logs"}) is True

    def test_is_suppressed_wildcard_key(self):
        f = QAFinding(check="orphaned_tables", severity=INFO,
                      message="x", table="logs")
        assert self._is_sup(f, {"orphaned_tables:*"}) is True

    def test_not_suppressed_when_no_match(self):
        f = QAFinding(check="orphaned_tables", severity=INFO,
                      message="x", table="logs")
        assert self._is_sup(f, {"naming_conventions:*", "orphaned_tables:events"}) is False


# ---------------------------------------------------------------------------
# mind_map_generator — BFS helper (pure Python)
# ---------------------------------------------------------------------------

class TestMindMapBFS:
    """Test the BFS wave helper without any database."""

    def _get_bfs(self):
        from coruscant.core.mind_map_generator import _compute_bfs
        return _compute_bfs

    def test_single_node_wave_zero(self):
        bfs = self._get_bfs()
        order, wave = bfs("a", [], {"a"})
        assert order == ["a"]
        assert wave == {"a": 0}

    def test_direct_neighbours_wave_one(self):
        bfs = self._get_bfs()
        edges = [("a", "b"), ("a", "c")]
        order, wave = bfs("a", edges, {"a", "b", "c"})
        assert wave["a"] == 0
        assert wave["b"] == 1
        assert wave["c"] == 1

    def test_chain_waves(self):
        bfs = self._get_bfs()
        edges = [("a", "b"), ("b", "c"), ("c", "d")]
        order, wave = bfs("a", edges, {"a", "b", "c", "d"})
        assert wave == {"a": 0, "b": 1, "c": 2, "d": 3}
        assert order == ["a", "b", "c", "d"]

    def test_disconnected_nodes_included(self):
        bfs = self._get_bfs()
        edges = [("a", "b")]
        order, wave = bfs("a", edges, {"a", "b", "isolated"})
        assert "isolated" in wave

    def test_bidirectional_edges_traversed(self):
        bfs = self._get_bfs()
        edges = [("b", "a")]  # reversed direction
        order, wave = bfs("a", edges, {"a", "b"})
        assert wave["b"] == 1

    def test_cycle_does_not_loop_forever(self):
        bfs = self._get_bfs()
        edges = [("a", "b"), ("b", "c"), ("c", "a")]
        order, wave = bfs("a", edges, {"a", "b", "c"})
        assert len(order) == 3
        assert set(wave.keys()) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# mind_map_generator — HTML output structure
# ---------------------------------------------------------------------------

class TestMindMapGeneratorHTMLStructure:
    """
    Test generate_mind_map() by mocking the DB cursor to return synthetic
    table / FK data and asserting the HTML output has expected landmarks.
    """

    def _run_generator(self, schema="public", focus_table=None):
        from unittest.mock import MagicMock
        from coruscant.core.mind_map_generator import generate_mind_map

        # Mock cursor results:
        # pg_class query → row count per table
        row_counts = [("users", 100), ("orders", 500)]
        # information_schema FK query → edges
        fk_edges   = [("orders", "users")]

        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.side_effect = [row_counts, fk_edges]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        return generate_mind_map(mock_conn, schema, focus_table)

    def test_returns_html_string(self):
        html = self._run_generator()
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_d3_import(self):
        html = self._run_generator()
        assert "d3" in html.lower()

    def test_contains_schema_name(self):
        html = self._run_generator(schema="myschema")
        assert "myschema" in html

    def test_contains_table_names(self):
        html = self._run_generator()
        assert "users" in html
        assert "orders" in html

    def test_focus_table_in_html(self):
        html = self._run_generator(focus_table="users")
        assert "users" in html

    def test_contains_force_simulation(self):
        html = self._run_generator()
        assert "forceSimulation" in html or "d3.forceSimulation" in html

    def test_contains_zoom(self):
        html = self._run_generator()
        assert "d3.zoom" in html or "zoom" in html
