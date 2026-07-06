"""
tests/test_query_builder.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the Visual Query Builder (v1.0.9).

These mirror the AST/source style of test_dashboard.py and test_recovery.py:
structural checks run without importing PySide6 (not installed in CI), and
the pure-logic pieces (FK-definition parsing, JOIN_TYPES) are extracted from
the source and executed in isolation.
"""
from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_QB     = "coruscant/ui/dialogs/query_builder.py"
_SCHEMA = "coruscant/ui/panels/schema.py"
_GUIDE  = "coruscant/ui/dialogs/guide.py"


def _src(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def _tree(rel: str) -> ast.Module:
    return ast.parse(_src(rel))


def _fns(tree: ast.Module) -> set[str]:
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _cls(tree: ast.Module) -> set[str]:
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


# ---------------------------------------------------------------------------
# 1. query_builder.py structure
# ---------------------------------------------------------------------------

class TestQueryBuilderStructure:

    def test_dialog_class_exists(self):
        assert "QueryBuilderDialog" in _cls(_tree(_QB))

    def test_join_row_class_exists(self):
        assert "_JoinRow" in _cls(_tree(_QB))

    def test_required_methods_defined(self):
        fns = _fns(_tree(_QB))
        for method in [
            "build_sql", "_parse_fks", "find_fk_link", "tables_in_query",
            "columns_of", "table_names", "_add_join", "_remove_join",
            "_rebuild_fields", "_check_all", "_on_field_toggled",
            "_qualified_columns", "_refresh", "_regen_sql",
            "_copy_sql", "_emit_sql", "_build_ui", "_stylesheet",
        ]:
            assert method in fns, f"query_builder.py: {method}() missing"

    def test_join_row_methods_defined(self):
        fns = _fns(_tree(_QB))
        for method in ["set_tables", "set_left_columns",
                       "_on_table_changed", "_autolink", "value"]:
            assert method in fns, f"_JoinRow: {method}() missing"

    def test_insert_sql_signal_present(self):
        src = _src(_QB)
        assert "insert_sql" in src
        assert "Signal(str)" in src

    def test_uses_shared_design_tokens(self):
        """The futuristic skin must be built from coruscant.ui.style tokens."""
        src = _src(_QB)
        assert "from coruscant.ui.style import" in src

    def test_uses_sql_highlighter_for_preview(self):
        src = _src(_QB)
        assert "SQLHighlighter" in src

    def test_fields_tree_resizes_to_contents(self):
        """Regression guard for v1.0.9 fix: column names must not truncate."""
        src = _src(_QB)
        assert "ResizeToContents" in src, (
            "Select Fields tree must use ResizeToContents so column names "
            "are fully visible"
        )


# ---------------------------------------------------------------------------
# 2. JOIN_TYPES — all three join kinds offered
# ---------------------------------------------------------------------------

class TestJoinTypes:

    def _join_types(self) -> list[str]:
        for node in _tree(_QB).body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "JOIN_TYPES":
                        return ast.literal_eval(node.value)
        raise AssertionError("JOIN_TYPES constant not found")

    def test_inner_left_right_present(self):
        types = self._join_types()
        assert "INNER JOIN" in types
        assert "LEFT JOIN" in types
        assert "RIGHT JOIN" in types

    def test_exactly_three_types(self):
        assert len(self._join_types()) == 3


# ---------------------------------------------------------------------------
# 3. FK-definition parsing — pure logic, executed without Qt
# ---------------------------------------------------------------------------

class TestParseFks:
    """Extract _FK_RE and _parse_fks from the source and run them in
    isolation (same technique as the connection.py helper tests)."""

    def _parse_fks(self):
        src = _src(_QB)
        tree = ast.parse(src)

        fk_re_src = None
        parse_src = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "_FK_RE"
                            for t in node.targets)):
                fk_re_src = ast.get_source_segment(src, node)
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "_parse_fks"):
                parse_src = textwrap.dedent(ast.get_source_segment(src, node))

        assert fk_re_src, "_FK_RE regex not found in query_builder.py"
        assert parse_src, "_parse_fks() not found in query_builder.py"

        ns = {"re": re}
        exec(fk_re_src, ns)
        exec(parse_src, ns)
        return ns["_parse_fks"]

    @staticmethod
    def _tables(defn: str) -> list[dict]:
        return [{"name": "orders",
                 "foreign_keys": [{"name": "fk1", "definition": defn}]}]

    def test_single_column_fk(self):
        parse = self._parse_fks()
        links = parse(self._tables(
            "FOREIGN KEY orders(customer_id) REFERENCES customers(id)"))
        assert links == [("orders", "customer_id", "customers", "id")]

    def test_multi_column_fk_pairs_positionally(self):
        parse = self._parse_fks()
        links = parse(self._tables(
            "FOREIGN KEY orders(a, b) REFERENCES parents(x, y)"))
        assert ("orders", "a", "parents", "x") in links
        assert ("orders", "b", "parents", "y") in links
        assert len(links) == 2

    def test_quoted_identifiers_are_stripped(self):
        parse = self._parse_fks()
        links = parse(self._tables(
            'FOREIGN KEY "orders"("customer_id") REFERENCES "customers"("id")'))
        assert links == [("orders", "customer_id", "customers", "id")]

    def test_malformed_definition_ignored(self):
        parse = self._parse_fks()
        assert parse(self._tables("not a foreign key at all")) == []

    def test_no_fks_returns_empty(self):
        parse = self._parse_fks()
        assert parse([{"name": "loners", "foreign_keys": []}]) == []

    def test_multiple_tables_accumulate(self):
        parse = self._parse_fks()
        tables = [
            {"name": "a", "foreign_keys": [
                {"name": "f1",
                 "definition": "FOREIGN KEY a(b_id) REFERENCES b(id)"}]},
            {"name": "c", "foreign_keys": [
                {"name": "f2",
                 "definition": "FOREIGN KEY c(b_id) REFERENCES b(id)"}]},
        ]
        links = parse(tables)
        assert ("a", "b_id", "b", "id") in links
        assert ("c", "b_id", "b", "id") in links


# ---------------------------------------------------------------------------
# 4. build_sql — source-shape checks
# ---------------------------------------------------------------------------

class TestBuildSqlSource:

    def _build_sql_src(self) -> str:
        src = _src(_QB)
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == "build_sql":
                return ast.get_source_segment(src, node)
        raise AssertionError("build_sql() not found")

    def test_generates_all_clauses(self):
        body = self._build_sql_src()
        for fragment in ["SELECT", "FROM", "ON", "WHERE", "ORDER BY", "LIMIT"]:
            assert fragment in body, f"build_sql() missing {fragment} clause"

    def test_select_star_fallback(self):
        assert "SELECT *" in self._build_sql_src()

    def test_statement_terminated_with_semicolon(self):
        assert '";"' in self._build_sql_src()

    def test_identifiers_are_quoted(self):
        body = self._build_sql_src()
        assert '"{s}"."{base}"' in body or "\\\"" in body, (
            "build_sql() must double-quote schema/table identifiers"
        )


# ---------------------------------------------------------------------------
# 5. schema.py wiring — context menu and signal forwarding
# ---------------------------------------------------------------------------

class TestSchemaBrowserWiring:

    def test_open_query_builder_defined(self):
        assert "_open_query_builder" in _fns(_tree(_SCHEMA))

    def test_context_menu_has_query_builder_action(self):
        assert "Query Builder" in _src(_SCHEMA)

    def test_tree_data_cached_for_builder(self):
        """_populate_tree must store the raw tree so the builder can read
        table/column/FK metadata without re-querying the database."""
        assert "_tree_data" in _src(_SCHEMA)

    def test_dialog_signal_forwarded_to_insert_sql(self):
        src = _src(_SCHEMA)
        assert "dlg.insert_sql.connect(self.insert_sql.emit)" in src

    def test_builder_imported_lazily(self):
        """Dialog import must stay inside the handler (startup cost)."""
        src = _src(_SCHEMA)
        assert "from coruscant.ui.dialogs.query_builder import" in src


# ---------------------------------------------------------------------------
# 6. documentation — in-app guide mentions the feature
# ---------------------------------------------------------------------------

class TestGuideMentionsQueryBuilder:

    def test_guide_documents_query_builder(self):
        assert "Query Builder" in _src(_GUIDE)

    def test_guide_documents_join_kinds(self):
        assert "INNER / LEFT / RIGHT" in _src(_GUIDE)
