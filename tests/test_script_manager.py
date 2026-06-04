"""
Tests for coruscant.core.script_manager.

All tests that call ScriptKnowledgeGraph.build() mock out networkx so
they work without the package being installed.  The mock is minimal:
  - nx.Graph() returns a real networkx-like stub or a MagicMock
  - pagerank returns a safe dict
  - community detection returns an empty list

Tests that do NOT call build() (parser, add_scripts, persistence basics)
need no mock.
"""
from __future__ import annotations

import gzip
import io
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import math

import pytest

from coruscant.core.script_manager import (
    ParsedScript,
    SQLScriptParser,
    ScriptIngester,
    ScriptKnowledgeGraph,
    SearchResult,
    GraphStats,
    _SYNONYMS,
    _STOPWORDS,
    _MIN_TERM_LEN,
    _GRAPH_FILENAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parser() -> SQLScriptParser:
    return SQLScriptParser()


def _simple_script(parser, name="test.sql", content="SELECT 1;") -> ParsedScript:
    return parser.parse_content(name, content)


def _make_nx_mock():
    """Return a minimal networkx mock that lets build() complete."""
    nx = MagicMock()
    # Graph() returns a mock graph that supports add_node / add_edge / nodes
    G = MagicMock()
    G.nodes = {}
    nx.Graph.return_value = G
    # pagerank returns empty dict (no nodes)
    nx.pagerank.return_value = {}
    # community module
    nx.community = MagicMock()
    nx.community.louvain_communities.return_value = []
    nx.community.greedy_modularity_communities.return_value = []
    return nx


def _build_graph_with_mock(scripts):
    """Add *scripts* to a graph and call build() with a mocked networkx."""
    g = ScriptKnowledgeGraph()
    g.add_scripts(scripts)
    nx_mock = _make_nx_mock()
    with patch.dict(sys.modules, {"networkx": nx_mock}):
        import coruscant.core.script_manager as sm_mod
        orig_nx = sm_mod.nx
        orig_avail = sm_mod._NX_AVAILABLE
        sm_mod.nx = nx_mock
        sm_mod._NX_AVAILABLE = True
        try:
            g.build()
        finally:
            sm_mod.nx = orig_nx
            sm_mod._NX_AVAILABLE = orig_avail
    return g


def _make_zip(files: dict[str, str]) -> io.BytesIO:
    """Create an in-memory zip with {filename: content} entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text.encode("utf-8"))
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# SQLScriptParser — parse_content
# ---------------------------------------------------------------------------

class TestSQLScriptParserBasic:

    def test_returns_parsed_script_type(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "SELECT 1;")
        assert isinstance(ps, ParsedScript)

    def test_filename_stored(self):
        p = _make_parser()
        ps = p.parse_content("my_script.sql", "SELECT 1;")
        assert ps.filename == "my_script.sql"

    def test_path_stored(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "SELECT 1;", path="folder/a.sql")
        assert ps.path == "folder/a.sql"

    def test_path_defaults_to_empty(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "SELECT 1;")
        assert ps.path == ""

    def test_checksum_is_16_hex_chars(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "SELECT 1;")
        assert len(ps.checksum) == 16
        assert all(c in "0123456789abcdef" for c in ps.checksum)

    def test_checksum_differs_for_different_content(self):
        p = _make_parser()
        ps1 = p.parse_content("a.sql", "SELECT 1;")
        ps2 = p.parse_content("a.sql", "SELECT 2;")
        assert ps1.checksum != ps2.checksum

    def test_same_content_same_checksum(self):
        p = _make_parser()
        content = "SELECT id FROM users;"
        ps1 = p.parse_content("a.sql", content)
        ps2 = p.parse_content("b.sql", content)
        assert ps1.checksum == ps2.checksum

    def test_content_truncated_to_512kb(self):
        p = _make_parser()
        big = "SELECT 1; " * 100_000   # ~1 MB
        ps = p.parse_content("big.sql", big)
        assert len(ps.content) <= 512 * 1024

    def test_empty_content(self):
        p = _make_parser()
        # "a.sql" stem "a" is too short (< 3 chars) and gets filtered from terms
        ps = p.parse_content("a.sql", "")
        assert ps.filename == "a.sql"
        assert ps.commands == []
        assert ps.tables == []

    def test_non_ascii_content_does_not_crash(self):
        p = _make_parser()
        ps = p.parse_content("unicode.sql", "-- données françaises\nSELECT 1;")
        assert ps.filename == "unicode.sql"


class TestSQLScriptParserTermWeights:

    def test_filename_tokens_weight_3(self):
        p = _make_parser()
        ps = p.parse_content("deadlock_killer.sql", "SELECT 1;")
        assert ps.terms.get("deadlock", 0) >= 3.0
        assert ps.terms.get("killer", 0) >= 3.0

    def test_desc_tag_weight_5(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @desc: vacuum bloat repair\nSELECT 1;")
        assert ps.terms.get("vacuum", 0) >= 5.0
        assert ps.terms.get("bloat", 0) >= 5.0

    def test_fixes_tag_weight_5(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @fixes: deadlock, idle\nSELECT 1;")
        assert ps.terms.get("deadlock", 0) >= 5.0
        assert ps.terms.get("idle", 0) >= 5.0

    def test_tables_tag_weight_4(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @tables: pg_locks\nSELECT 1;")
        # pg_locks or sub-parts should exist at >= 4.0
        found = (
            ps.terms.get("pg_locks", 0) >= 4.0
            or ps.terms.get("locks", 0) >= 4.0
        )
        assert found

    def test_body_terms_weight_1(self):
        p = _make_parser()
        # xyzzy is pure body term (not in filename, not in tag, not table ref)
        ps = p.parse_content("a.sql", "SELECT xyzzy FROM foobar;")
        assert ps.terms.get("xyzzy", 0) == 1.0
        assert ps.terms.get("foobar", 0) == 2.0   # table ref → weight 2

    def test_table_ref_weight_2(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "SELECT * FROM pg_stat_activity;")
        assert ps.terms.get("pg_stat_activity", 0) >= 2.0

    def test_desc_beats_body_for_same_term(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @desc: vacuum cleanup\nVACUUM t;")
        assert ps.terms.get("vacuum", 0) >= 5.0

    def test_pg_function_weight_3(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "SELECT pg_terminate_backend(pid);")
        assert (
            ps.terms.get("pg_terminate_backend", 0) >= 3.0
            or ps.terms.get("terminate", 0) >= 2.0
        )

    def test_stopwords_not_in_terms(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @desc: select from where the how\nSELECT 1;")
        for sw in ("select", "from", "where", "the", "how"):
            assert sw not in ps.terms

    def test_short_words_filtered(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @desc: ab cd ef\nSELECT 1;")
        for w in ("ab", "cd", "ef"):
            assert w not in ps.terms

    def test_numeric_only_tokens_filtered(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @desc: 123 456\nSELECT 1;")
        assert "123" not in ps.terms
        assert "456" not in ps.terms


class TestSQLScriptParserMetadata:

    def test_desc_tag_extracted(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @desc: Test script\nSELECT 1;")
        assert ps.metadata.get("desc") == "Test script"

    def test_fixes_tag_extracted(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @fixes: deadlock, lock_wait\nSELECT 1;")
        assert ps.metadata.get("fixes") == "deadlock, lock_wait"

    def test_tables_tag_extracted(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @tables: pg_locks, pg_stat_activity\nSELECT 1;")
        assert "pg_locks" in ps.metadata.get("tables", "")

    def test_date_tag_extracted(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @date: 2025-03-01\nSELECT 1;")
        assert ps.metadata.get("date") == "2025-03-01"

    def test_multiple_tags_extracted(self):
        p = _make_parser()
        ps = p.parse_content("a.sql",
            "-- @desc: Test\n-- @fixes: bloat\n-- @date: 2025-01-01\nSELECT 1;")
        assert "desc" in ps.metadata
        assert "fixes" in ps.metadata
        assert "date" in ps.metadata

    def test_tags_case_insensitive(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @DESC: My description\nSELECT 1;")
        assert "desc" in ps.metadata


class TestSQLScriptParserSQLPatterns:

    def test_select_command_extracted(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "SELECT * FROM t;")
        assert "SELECT" in ps.commands

    def test_vacuum_command_extracted(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "VACUUM ANALYZE t;")
        assert "VACUUM" in ps.commands

    def test_reindex_command_extracted(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "REINDEX TABLE t;")
        assert "REINDEX" in ps.commands

    def test_tables_from_from_clause(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "SELECT * FROM pg_stat_activity;")
        assert "pg_stat_activity" in ps.tables

    def test_tables_from_join_clause(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "SELECT * FROM a JOIN b ON a.id = b.id;")
        assert "a" in ps.tables or "b" in ps.tables

    def test_tables_from_update_clause(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "UPDATE orders SET status = 'done';")
        assert "orders" in ps.tables

    def test_error_code_extracted(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- handles error 40P01 (deadlock)\nSELECT 1;")
        assert "40P01" in ps.error_codes

    def test_error_code_as_term_with_weight_4(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- 57014 cancel\nSELECT 1;")
        assert ps.terms.get("57014", 0) >= 4.0

    def test_tables_capped_at_30(self):
        p = _make_parser()
        # Generate 40 distinct table references
        froms = " ".join(f"FROM tbl_{i:03d}" for i in range(40))
        ps = p.parse_content("a.sql", f"SELECT 1 {froms};")
        assert len(ps.tables) <= 30


# ---------------------------------------------------------------------------
# ScriptKnowledgeGraph — add_scripts / dedup
# ---------------------------------------------------------------------------

class TestScriptKnowledgeGraphAddScripts:

    def test_add_returns_added_count(self):
        p = _make_parser()
        scripts = [_simple_script(p, f"t{i}.sql", f"SELECT {i};") for i in range(3)]
        g = ScriptKnowledgeGraph()
        added, dupes = g.add_scripts(scripts)
        assert added == 3
        assert dupes == 0

    def test_add_duplicate_by_checksum_counted(self):
        p = _make_parser()
        scripts = [_simple_script(p, "a.sql", "SELECT 1;")]
        g = ScriptKnowledgeGraph()
        g.add_scripts(scripts)
        _, dupes = g.add_scripts(scripts)
        assert dupes == 1

    def test_add_merge_false_replaces(self):
        p = _make_parser()
        s1 = _simple_script(p, "a.sql", "SELECT 1;")
        s2 = _simple_script(p, "b.sql", "SELECT 2;")
        g = ScriptKnowledgeGraph()
        g.add_scripts([s1])
        added, _ = g.add_scripts([s2], merge=False)
        assert added == 1
        assert len(g._scripts) == 1   # old script replaced

    def test_add_sets_built_false(self):
        p = _make_parser()
        g = _build_graph_with_mock([_simple_script(p, "a.sql", "SELECT 1;")])
        assert g._built is True
        g.add_scripts([_simple_script(p, "b.sql", "SELECT 2;")])
        assert g._built is False

    def test_add_clears_cache(self):
        p = _make_parser()
        g = ScriptKnowledgeGraph()
        g._cache["k"] = []
        g.add_scripts([_simple_script(p)])
        assert g._cache == {}


# ---------------------------------------------------------------------------
# ScriptKnowledgeGraph — build (with mocked networkx)
# ---------------------------------------------------------------------------

class TestScriptKnowledgeGraphBuild:

    def test_build_sets_built_flag(self):
        p = _make_parser()
        g = _build_graph_with_mock([_simple_script(p, "a.sql", "SELECT 1;")])
        assert g._built is True

    def test_build_empty_graph_ok(self):
        g = ScriptKnowledgeGraph()
        import coruscant.core.script_manager as sm_mod
        orig_avail = sm_mod._NX_AVAILABLE
        sm_mod._NX_AVAILABLE = True
        try:
            g.build()   # no scripts — must not raise
        finally:
            sm_mod._NX_AVAILABLE = orig_avail
        assert g._built is True

    def test_build_raises_without_networkx(self):
        import coruscant.core.script_manager as sm_mod
        g = ScriptKnowledgeGraph()
        orig = sm_mod._NX_AVAILABLE
        sm_mod._NX_AVAILABLE = False
        try:
            with pytest.raises(RuntimeError, match="networkx"):
                g.build()
        finally:
            sm_mod._NX_AVAILABLE = orig

    def test_build_populates_idf(self):
        p = _make_parser()
        g = _build_graph_with_mock([
            p.parse_content("a.sql", "-- @desc: vacuum bloat\nVACUUM t;"),
            p.parse_content("b.sql", "-- @desc: deadlock lock\nSELECT 1;"),
        ])
        assert len(g._idf) > 0
        for v in g._idf.values():
            assert v > 0

    def test_build_populates_inverted_index(self):
        p = _make_parser()
        g = _build_graph_with_mock([_simple_script(p, "a.sql", "-- @desc: vacuum\nVACUUM t;")])
        assert len(g._inv) > 0

    def test_build_clears_cache(self):
        p = _make_parser()
        g = ScriptKnowledgeGraph()
        g.add_scripts([_simple_script(p)])
        g._cache["stale"] = []
        nx_mock = _make_nx_mock()
        import coruscant.core.script_manager as sm_mod
        sm_mod.nx = nx_mock
        sm_mod._NX_AVAILABLE = True
        try:
            g.build()
        finally:
            sm_mod._NX_AVAILABLE = False
        assert "stale" not in g._cache

    def test_progress_callback_called(self):
        p = _make_parser()
        calls = []
        cb = lambda stage, cur, tot: calls.append(stage)
        g = ScriptKnowledgeGraph()
        g.add_scripts([_simple_script(p)])
        nx_mock = _make_nx_mock()
        import coruscant.core.script_manager as sm_mod
        orig_avail = sm_mod._NX_AVAILABLE
        orig_nx = sm_mod.nx
        sm_mod.nx = nx_mock
        sm_mod._NX_AVAILABLE = True
        try:
            g.build(progress_cb=cb)
        finally:
            sm_mod.nx = orig_nx
            sm_mod._NX_AVAILABLE = orig_avail
        assert len(calls) > 0


# ---------------------------------------------------------------------------
# ScriptKnowledgeGraph — search (without real build)
# ---------------------------------------------------------------------------

class TestScriptKnowledgeGraphSearch:

    def _graph_with_inverted_index(self, inv, scripts=None, idf=None, pr=None):
        """Directly inject internal state to test search without build."""
        g = ScriptKnowledgeGraph()
        g._inv = inv
        g._idf = idf or {t: 1.5 for term_list in inv.values() for t in [term_list[0]]}
        g._pr = pr or {}
        g._comm = {}
        if scripts:
            g._scripts = scripts
        g._built = True
        return g

    def test_search_not_built_raises(self):
        g = ScriptKnowledgeGraph()
        with pytest.raises(RuntimeError, match="build"):
            g.search("anything")

    def test_search_empty_query_returns_empty(self):
        g = ScriptKnowledgeGraph()
        g._built = True
        assert g.search("") == []
        assert g.search("   ") == []

    def test_search_stopword_only_returns_empty(self):
        g = ScriptKnowledgeGraph()
        g._built = True
        g._inv = {}
        g._idf = {}
        g._pr = {}
        g._comm = {}
        # "select from" are all stopwords
        assert g.search("select from") == []

    def test_search_no_candidates_returns_empty(self):
        g = ScriptKnowledgeGraph()
        g._built = True
        g._inv = {"vacuum": ["abc123"]}
        g._idf = {"vacuum": 1.0}
        g._pr = {}
        g._comm = {}
        g._scripts = {}  # no scripts in store
        results = g.search("vacuum")
        assert results == []

    def test_search_results_are_search_result_type(self):
        p = _make_parser()
        g = _build_graph_with_mock([
            p.parse_content("vac.sql", "-- @desc: vacuum bloat\nVACUUM t;"),
        ])
        results = g.search("vacuum")
        for r in results:
            assert isinstance(r, SearchResult)

    def test_search_returns_at_most_max_results(self):
        p = _make_parser()
        scripts = [p.parse_content(f"s{i}.sql", f"-- @desc: deadlock\nSELECT {i};")
                   for i in range(5)]
        g = _build_graph_with_mock(scripts)
        results = g.search("deadlock", max_results=2)
        assert len(results) <= 2

    def test_search_scores_sorted_descending(self):
        p = _make_parser()
        scripts = [
            p.parse_content("a.sql", "-- @desc: vacuum bloat\nVACUUM t;"),
            p.parse_content("b.sql", "-- @desc: deadlock blocked\nSELECT 1;"),
            p.parse_content("c.sql", "-- @desc: vacuum autovacuum\nVACUUM c;"),
        ]
        g = _build_graph_with_mock(scripts)
        results = g.search("vacuum")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_caches_result(self):
        p = _make_parser()
        g = _build_graph_with_mock([p.parse_content("a.sql", "-- @desc: vacuum\nVACUUM t;")])
        g.search("vacuum")
        assert any("vacuum" in k for k in g._cache)

    def test_search_cache_hit_returns_same_result(self):
        p = _make_parser()
        g = _build_graph_with_mock([p.parse_content("a.sql", "-- @desc: vacuum\nVACUUM t;")])
        r1 = g.search("vacuum")
        r2 = g.search("vacuum")
        assert r1 is r2   # exact same list object from cache


# ---------------------------------------------------------------------------
# ScriptKnowledgeGraph — _parse_query / _expand_query
# ---------------------------------------------------------------------------

class TestQueryProcessing:

    def test_parse_query_strips_stopwords(self):
        terms = ScriptKnowledgeGraph._parse_query("how to fix the deadlock")
        assert "how" not in terms
        assert "the" not in terms
        assert "deadlock" in terms

    def test_parse_query_preserves_pg_compound(self):
        terms = ScriptKnowledgeGraph._parse_query("pg_stat_activity sessions")
        assert "pg_stat_activity" in terms

    def test_parse_query_extracts_error_code(self):
        terms = ScriptKnowledgeGraph._parse_query("error 40P01")
        assert "40P01" in terms

    def test_parse_query_short_words_excluded(self):
        terms = ScriptKnowledgeGraph._parse_query("ab cd deadlock")
        assert "ab" not in terms
        assert "cd" not in terms
        assert "deadlock" in terms

    def test_expand_query_includes_synonyms(self):
        expanded = ScriptKnowledgeGraph._expand_query(["deadlock"])
        assert "blocked" in expanded or "lock" in expanded

    def test_expand_query_no_duplicates(self):
        expanded = ScriptKnowledgeGraph._expand_query(["vacuum", "vacuum"])
        assert len(expanded) == len(set(expanded))

    def test_expand_query_unknown_term_passthrough(self):
        expanded = ScriptKnowledgeGraph._expand_query(["xyzzy_unique"])
        assert "xyzzy_unique" in expanded


# ---------------------------------------------------------------------------
# ScriptKnowledgeGraph — _recency_mult / _severity_mult
# ---------------------------------------------------------------------------

class TestScoringHelpers:

    def test_recency_no_date_returns_1(self):
        assert ScriptKnowledgeGraph._recency_mult("") == 1.0

    def test_recency_invalid_date_returns_1(self):
        assert ScriptKnowledgeGraph._recency_mult("not-a-date") == 1.0

    def test_recency_old_date_returns_1(self):
        assert ScriptKnowledgeGraph._recency_mult("2000-01-01") == 1.0

    def test_recency_recent_within_90_days(self):
        from datetime import datetime, timedelta
        recent = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        assert ScriptKnowledgeGraph._recency_mult(recent) == 1.2

    def test_recency_within_year(self):
        from datetime import datetime, timedelta
        mid = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        assert ScriptKnowledgeGraph._recency_mult(mid) == 1.1

    def test_severity_no_fix_words_returns_1(self):
        result = ScriptKnowledgeGraph._severity_mult({"vacuum", "bloat"}, ["SELECT"])
        assert result == 1.0

    def test_severity_fix_word_with_delete_returns_boost(self):
        result = ScriptKnowledgeGraph._severity_mult({"kill"}, ["DELETE"])
        assert result == 1.15

    def test_severity_fix_word_without_mod_cmd_returns_1(self):
        result = ScriptKnowledgeGraph._severity_mult({"kill"}, ["SELECT"])
        assert result == 1.0

    def test_severity_terminate_is_fix_word(self):
        result = ScriptKnowledgeGraph._severity_mult({"terminate"}, ["DELETE"])
        assert result == 1.15


# ---------------------------------------------------------------------------
# ScriptKnowledgeGraph — _make_preview
# ---------------------------------------------------------------------------

class TestMakePreview:

    def test_preview_short_content_no_ellipsis(self):
        preview = ScriptKnowledgeGraph._make_preview("SELECT 1;")
        assert "…" not in preview

    def test_preview_long_content_truncated(self):
        long_content = ("SELECT very_long_column_name FROM very_long_table_name; " * 20)
        preview = ScriptKnowledgeGraph._make_preview(long_content)
        assert len(preview) <= 202   # 200 + "…"

    def test_preview_skips_blank_lines(self):
        content = "\n\n\nSELECT 1;\n\n\n"
        preview = ScriptKnowledgeGraph._make_preview(content)
        assert "SELECT" in preview

    def test_preview_max_5_lines(self):
        content = "\n".join(f"LINE {i}" for i in range(20))
        preview = ScriptKnowledgeGraph._make_preview(content)
        # At most 5 lines joined by " | "
        assert preview.count("|") <= 4


# ---------------------------------------------------------------------------
# ScriptKnowledgeGraph — stats
# ---------------------------------------------------------------------------

class TestGraphStats:

    def test_stats_empty_graph(self):
        g = ScriptKnowledgeGraph()
        s = g.stats()
        assert isinstance(s, GraphStats)
        assert s.script_count == 0
        assert s.term_count == 0

    def test_stats_after_add_scripts(self):
        p = _make_parser()
        g = ScriptKnowledgeGraph()
        g.add_scripts([_simple_script(p)])
        s = g.stats()
        assert s.script_count == 1

    def test_stats_after_build(self):
        p = _make_parser()
        g = _build_graph_with_mock([_simple_script(p, "a.sql", "-- @desc: vacuum\nVACUUM t;")])
        s = g.stats()
        assert s.term_count > 0

    def test_stats_last_indexed_from_date_tag(self):
        p = _make_parser()
        ps = p.parse_content("a.sql", "-- @date: 2025-06-01\nSELECT 1;")
        g = _build_graph_with_mock([ps])
        s = g.stats()
        assert s.last_indexed == "2025-06-01"


# ---------------------------------------------------------------------------
# ScriptKnowledgeGraph — persistence (save / load)
# ---------------------------------------------------------------------------

class TestGraphPersistence:

    def test_save_creates_gzip_json_file(self, tmp_path):
        p = _make_parser()
        g = _build_graph_with_mock([_simple_script(p, "a.sql", "-- @desc: vacuum\nVACUUM t;")])
        out = tmp_path / "graph.json.gz"
        g.save(out)
        assert out.exists()
        # Verify it's valid gzip+json
        with gzip.open(out, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        assert "scripts" in data
        assert "idf" in data

    def test_save_returns_path(self, tmp_path):
        p = _make_parser()
        g = _build_graph_with_mock([_simple_script(p)])
        out = tmp_path / "g.json.gz"
        result = g.save(out)
        assert result == out

    def test_load_returns_empty_graph_if_file_missing(self, tmp_path):
        g = ScriptKnowledgeGraph.load(tmp_path / "nonexistent.json.gz")
        assert len(g._scripts) == 0
        assert g._built is False

    def test_load_restores_script_count(self, tmp_path):
        p = _make_parser()
        g = _build_graph_with_mock([
            _simple_script(p, "a.sql", "-- @desc: vacuum\nVACUUM t;"),
            _simple_script(p, "b.sql", "-- @desc: deadlock\nSELECT 1;"),
        ])
        out = tmp_path / "g.json.gz"
        g.save(out)
        g2 = ScriptKnowledgeGraph.load(out)
        assert len(g2._scripts) == 2

    def test_load_restores_idf(self, tmp_path):
        p = _make_parser()
        g = _build_graph_with_mock([_simple_script(p, "a.sql", "-- @desc: vacuum\nVACUUM t;")])
        out = tmp_path / "g.json.gz"
        g.save(out)
        g2 = ScriptKnowledgeGraph.load(out)
        assert len(g2._idf) > 0

    def test_load_sets_built_true_when_idf_present(self, tmp_path):
        p = _make_parser()
        g = _build_graph_with_mock([_simple_script(p, "a.sql", "-- @desc: vacuum\nVACUUM t;")])
        out = tmp_path / "g.json.gz"
        g.save(out)
        g2 = ScriptKnowledgeGraph.load(out)
        assert g2._built is True

    def test_load_corrupted_file_returns_empty(self, tmp_path):
        bad = tmp_path / "bad.json.gz"
        bad.write_bytes(b"not gzip at all")
        g = ScriptKnowledgeGraph.load(bad)
        assert len(g._scripts) == 0

    def test_load_search_works_after_load(self, tmp_path):
        p = _make_parser()
        g = _build_graph_with_mock([
            p.parse_content("vac.sql", "-- @desc: vacuum bloat dead_tuples\nVACUUM t;"),
        ])
        out = tmp_path / "g.json.gz"
        g.save(out)
        g2 = ScriptKnowledgeGraph.load(out)
        results = g2.search("vacuum")
        assert len(results) > 0

    def test_default_path_returns_path_object(self):
        p = ScriptKnowledgeGraph.default_path()
        assert isinstance(p, Path)
        assert p.name == _GRAPH_FILENAME


# ---------------------------------------------------------------------------
# ScriptIngester — zip handling
# ---------------------------------------------------------------------------

class TestScriptIngester:

    def _ingest_buf(self, buf, **kwargs):
        """Run ingester on an in-memory BytesIO zip using tmp_path trick."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(buf.getvalue())
            fpath = f.name
        try:
            ingester = ScriptIngester()
            nx_mock = _make_nx_mock()
            import coruscant.core.script_manager as sm_mod
            orig_avail = sm_mod._NX_AVAILABLE
            orig_nx = sm_mod.nx
            sm_mod.nx = nx_mock
            sm_mod._NX_AVAILABLE = True
            orig_save = ScriptKnowledgeGraph.save
            ScriptKnowledgeGraph.save = lambda self, path=None: path or Path("/tmp/x")
            try:
                result = ingester.ingest_zip(fpath, **kwargs)
            finally:
                sm_mod.nx = orig_nx
                sm_mod._NX_AVAILABLE = orig_avail
                ScriptKnowledgeGraph.save = orig_save
        finally:
            os.unlink(fpath)
        return result

    def test_ingest_single_sql_file(self):
        buf = _make_zip({"fix.sql": "-- @desc: vacuum\nVACUUM t;"})
        g = self._ingest_buf(buf)
        assert len(g._scripts) == 1

    def test_ingest_multiple_files(self):
        buf = _make_zip({
            "a.sql": "-- @desc: vacuum\nVACUUM t;",
            "b.sql": "-- @desc: deadlock\nSELECT 1;",
        })
        g = self._ingest_buf(buf)
        assert len(g._scripts) == 2

    def test_ingest_ignores_non_sql_files(self):
        buf = _make_zip({"a.sql": "SELECT 1;", "readme.txt": "ignore me"})
        g = self._ingest_buf(buf)
        assert len(g._scripts) == 1

    def test_empty_zip_raises_value_error(self):
        buf = _make_zip({})  # no .sql files
        with pytest.raises(ValueError, match="No .sql files"):
            self._ingest_buf(buf)

    def test_bad_zip_raises_value_error(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(b"not a zip file at all")
            fpath = f.name
        try:
            ingester = ScriptIngester()
            with pytest.raises(ValueError, match="corrupted"):
                ingester.ingest_zip(fpath)
        finally:
            os.unlink(fpath)

    def test_ingest_deduplicates_identical_content(self):
        buf = _make_zip({
            "a.sql": "SELECT 1;",
            "b.sql": "SELECT 1;",   # identical content → same checksum
        })
        g = self._ingest_buf(buf)
        assert len(g._scripts) == 1

    def test_ingest_merge_adds_to_existing(self):
        buf1 = _make_zip({"a.sql": "-- @desc: vacuum\nVACUUM t;"})
        buf2 = _make_zip({"b.sql": "-- @desc: deadlock\nSELECT 1;"})
        g1 = self._ingest_buf(buf1)
        g2 = self._ingest_buf(buf2, existing_graph=g1, merge=True)
        assert len(g2._scripts) == 2

    def test_ingest_no_merge_replaces(self):
        buf1 = _make_zip({"a.sql": "-- @desc: vacuum\nVACUUM t;"})
        buf2 = _make_zip({"b.sql": "-- @desc: deadlock\nSELECT 1;"})
        g1 = self._ingest_buf(buf1)
        g2 = self._ingest_buf(buf2, existing_graph=g1, merge=False)
        assert len(g2._scripts) == 1

    def test_progress_callback_is_called(self):
        buf = _make_zip({"a.sql": "SELECT 1;"})
        stages = []
        cb = lambda stage, cur, tot: stages.append(stage)
        self._ingest_buf(buf, progress_cb=cb)
        assert len(stages) > 0

    def test_latin1_content_handled(self):
        """Files with latin-1 encoding should not crash the ingester."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            content = "-- données\nSELECT 1;".encode("latin-1")
            zf.writestr("latin.sql", content)
        buf.seek(0)
        g = self._ingest_buf(buf)
        assert len(g._scripts) == 1


# ---------------------------------------------------------------------------
# _SYNONYMS dictionary structure
# ---------------------------------------------------------------------------

class TestSynonymsDictionary:

    def test_synonyms_is_dict(self):
        assert isinstance(_SYNONYMS, dict)

    def test_all_values_are_lists(self):
        for k, v in _SYNONYMS.items():
            assert isinstance(v, list), f"_SYNONYMS[{k!r}] is not a list"

    def test_key_appears_in_own_expansion(self):
        """Each key should expand to itself (among others)."""
        for k, v in _SYNONYMS.items():
            assert k in v, f"_SYNONYMS[{k!r}] does not include itself"

    def test_deadlock_expands_to_blocked(self):
        assert "blocked" in _SYNONYMS["deadlock"]

    def test_vacuum_expands_to_bloat(self):
        assert "bloat" in _SYNONYMS["vacuum"]


# ---------------------------------------------------------------------------
# Edge / regression cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_graph_starts_not_built(self):
        g = ScriptKnowledgeGraph()
        assert g._built is False

    def test_graph_cache_lru_evicts_at_50(self):
        g = ScriptKnowledgeGraph()
        g._built = True
        g._inv = {}
        g._idf = {}
        g._pr = {}
        g._comm = {}
        g._scripts = {}
        # Fill cache to 50 with empty results
        for i in range(50):
            key = f"query{i}:20"
            g._cache[key] = []
            g._cache_q.append(key)
        # One more search should evict the oldest entry
        g.search("anythingxyz")
        assert len(g._cache_q) <= 50

    def test_parser_handles_no_tags(self):
        p = _make_parser()
        ps = p.parse_content("plain.sql", "SELECT id FROM users;")
        assert ps.metadata == {}

    def test_parser_filename_without_extension(self):
        p = _make_parser()
        # Should not crash
        ps = p.parse_content("no_extension", "SELECT 1;")
        assert ps.filename == "no_extension"

    def test_search_result_fields_populated(self):
        p = _make_parser()
        g = _build_graph_with_mock([
            p.parse_content("vac.sql", "-- @desc: vacuum bloat\nVACUUM t;"),
        ])
        results = g.search("vacuum")
        if results:
            r = results[0]
            assert isinstance(r.script_id, str)
            assert isinstance(r.filename, str) and r.filename
            assert isinstance(r.score, float)
            assert isinstance(r.matched_terms, list)
            assert isinstance(r.preview, str)
            assert isinstance(r.community, int)
            assert isinstance(r.path, str)
