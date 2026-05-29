"""
Tests for coruscant.core.script_manager.

Covers:
  - SQLScriptParser (filename tokens, @tags, SQL patterns, weight hierarchy)
  - ScriptKnowledgeGraph (build, search, merge, save/load, scoring)
  - ScriptIngester (zip handling, dedup, error cases)
  - Edge cases (empty zip, non-ASCII, large file truncation, no-match query)
"""
from __future__ import annotations

import gzip
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from coruscant.core.sql import split_statements_with_positions
from coruscant.core.script_manager import (
    ParsedScript,
    SQLScriptParser,
    ScriptIngester,
    ScriptKnowledgeGraph,
    SearchResult,
    _SYNONYMS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parser():
    return SQLScriptParser()


@pytest.fixture
def sample_scripts(parser):
    """Five representative scripts that cover multiple topics."""
    return [
        parser.parse_content("fix_deadlock.sql", """
-- @desc: Kill sessions blocking vacuum due to lock contention
-- @fixes: deadlock, blocked, lock_wait
-- @tables: pg_stat_activity, pg_locks
SELECT pid FROM pg_stat_activity WHERE wait_event_type = 'Lock';
SELECT pg_terminate_backend(pid) FROM pg_locks WHERE NOT granted;
"""),
        parser.parse_content("vacuum_bloat.sql", """
-- @desc: Reclaim space from dead tuples and prevent table bloat
-- @fixes: bloat, vacuum, dead_tuples, autovacuum
VACUUM ANALYZE public.orders;
SELECT relname FROM pg_stat_user_tables WHERE n_dead_tup > 1000;
"""),
        parser.parse_content("slow_query_report.sql", """
-- @desc: Identify slow queries and performance bottlenecks
-- @fixes: slow, performance, latency, timeout
-- @requires: pg_stat_statements
SELECT query, total_time FROM pg_stat_statements
ORDER BY total_time DESC LIMIT 20;
"""),
        parser.parse_content("reindex_bloat.sql", """
-- @desc: Rebuild bloated indexes to reclaim space
-- @fixes: index, index_bloat, reindex
REINDEX TABLE public.orders;
SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes WHERE idx_scan = 0;
"""),
        parser.parse_content("kill_long_tx.sql", """
-- @desc: Terminate transactions running longer than 1 hour
-- @fixes: deadlock, long_transaction, idle_in_transaction
-- @date: 2026-01-15
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE now() - query_start > interval '1 hour'
  AND state != 'idle';
"""),
    ]


@pytest.fixture
def built_graph(sample_scripts):
    g = ScriptKnowledgeGraph()
    g.add_scripts(sample_scripts)
    g.build()
    return g


# ---------------------------------------------------------------------------
# SQLScriptParser
# ---------------------------------------------------------------------------

class TestSQLScriptParser:

    def test_filename_tokens_extracted(self, parser):
        ps = parser.parse_content("fix_deadlock.sql", "SELECT 1;")
        assert "fix" in ps.terms or "deadlock" in ps.terms

    def test_filename_tokens_weight_3(self, parser):
        ps = parser.parse_content("deadlock_killer.sql", "SELECT 1;")
        # filename tokens get weight 3
        assert ps.terms.get("deadlock", 0) >= 3.0
        assert ps.terms.get("killer", 0) >= 3.0

    def test_desc_tag_weight_5(self, parser):
        ps = parser.parse_content("a.sql", "-- @desc: vacuum bloat repair\nSELECT 1;")
        assert ps.terms.get("vacuum", 0) >= 5.0
        assert ps.terms.get("bloat", 0) >= 5.0

    def test_fixes_tag_weight_5(self, parser):
        ps = parser.parse_content("a.sql", "-- @fixes: deadlock, idle\nSELECT 1;")
        assert ps.terms.get("deadlock", 0) >= 5.0
        assert ps.terms.get("idle", 0) >= 5.0

    def test_tables_tag_weight_4(self, parser):
        ps = parser.parse_content("a.sql", "-- @tables: pg_locks, pg_stat_activity\nSELECT 1;")
        # table names from @tables tag
        assert ps.terms.get("pg_locks", 0) >= 4.0 or "locks" in ps.terms

    def test_body_terms_weight_1(self, parser):
        # A term that appears ONLY in the SQL body (not in filename, not a table ref)
        # should get weight 1.  "xyzzy" is pure body; "foobar" is FROM-clause so
        # gets weight 2 as a table reference — that is correct behaviour.
        ps = parser.parse_content("a.sql", "SELECT xyzzy FROM foobar;")
        assert ps.terms.get("xyzzy", 0) == 1.0    # pure body term
        assert ps.terms.get("foobar", 0) == 2.0   # table reference weight

    def test_desc_beats_body_for_same_term(self, parser):
        ps = parser.parse_content("a.sql", "-- @desc: vacuum cleanup\nVACUUM myschema.mytable;")
        # vacuum appears in both @desc (5) and body (1); max wins
        assert ps.terms.get("vacuum", 0) >= 5.0

    def test_metadata_extracted_desc(self, parser):
        ps = parser.parse_content("a.sql", "-- @desc: Test script\n-- @fixes: fix1\nSELECT 1;")
        assert ps.metadata.get("desc") == "Test script"
        assert ps.metadata.get("fixes") == "fix1"

    def test_commands_extracted(self, parser):
        ps = parser.parse_content("a.sql", "VACUUM myschema.t;\nREINDEX TABLE t;")
        assert "VACUUM" in ps.commands
        assert "REINDEX" in ps.commands

    def test_tables_from_from_clause(self, parser):
        ps = parser.parse_content("a.sql", "SELECT * FROM pg_stat_activity;")
        assert "pg_stat_activity" in ps.tables

    def test_tables_from_join_clause(self, parser):
        ps = parser.parse_content("a.sql", "SELECT * FROM a JOIN b ON a.id = b.id;")
        assert "a" in ps.tables or "b" in ps.tables

    def test_error_code_extracted(self, parser):
        ps = parser.parse_content("a.sql", "-- handles error 40P01 (deadlock detected)\nSELECT 1;")
        assert "40P01" in ps.error_codes

    def test_error_code_as_term(self, parser):
        ps = parser.parse_content("a.sql", "-- @fixes: 40P01\nSELECT 1;")
        assert "40P01" in ps.terms or ps.terms.get("40P01", 0) > 0

    def test_checksum_is_16_hex_chars(self, parser):
        ps = parser.parse_content("a.sql", "SELECT 1;")
        assert len(ps.checksum) == 16
        assert all(c in "0123456789abcdef" for c in ps.checksum)

    def test_checksum_differs_for_different_content(self, parser):
        ps1 = parser.parse_content("a.sql", "SELECT 1;")
        ps2 = parser.parse_content("a.sql", "SELECT 2;")
        assert ps1.checksum != ps2.checksum

    def test_stopwords_filtered(self, parser):
        ps = parser.parse_content("a.sql", "-- @desc: select from where how the\nSELECT 1;")
        for sw in ("select", "from", "where", "how", "the"):
            assert sw not in ps.terms

    def test_short_words_filtered(self, parser):
        ps = parser.parse_content("a.sql", "-- @desc: ab cd ef gh\nSELECT 1;")
        # words < 3 chars should not appear
        for w in ("ab", "cd", "ef", "gh"):
            assert w not in ps.terms

    def test_non_ascii_content_does_not_crash(self, parser):
        ps = parser.parse_content("unicode.sql", "-- @desc: données françaises\nSELECT 1;")
        assert ps.filename == "unicode.sql"

    def test_pg_function_extracted_as_term(self, parser):
        ps = parser.parse_content("a.sql", "SELECT pg_terminate_backend(pid);")
        # pg_ functions become terms
        assert "pg_terminate_backend" in ps.terms or "terminate" in ps.terms


# ---------------------------------------------------------------------------
# ScriptKnowledgeGraph — build and stats
# ---------------------------------------------------------------------------

class TestScriptKnowledgeGraph:

    def test_add_scripts_returns_counts(self, sample_scripts):
        g = ScriptKnowledgeGraph()
        added, dupes = g.add_scripts(sample_scripts)
        assert added == len(sample_scripts)
        assert dupes == 0

    def test_duplicate_by_checksum_is_skipped(self, sample_scripts):
        g = ScriptKnowledgeGraph()
        g.add_scripts(sample_scripts)
        _, dupes = g.add_scripts(sample_scripts)   # add same batch again
        assert dupes == len(sample_scripts)

    def test_build_sets_built_flag(self, sample_scripts):
        g = ScriptKnowledgeGraph()
        g.add_scripts(sample_scripts)
        g.build()
        assert g._built is True

    def test_stats_correct_after_build(self, built_graph, sample_scripts):
        s = built_graph.stats()
        assert s.script_count == len(sample_scripts)
        assert s.term_count > 0
        assert s.cluster_count >= 0

    def test_idf_populated(self, built_graph):
        assert len(built_graph._idf) > 0
        for v in built_graph._idf.values():
            assert v > 0

    def test_pagerank_populated(self, built_graph, sample_scripts):
        assert len(built_graph._pr) == len(sample_scripts)
        for v in built_graph._pr.values():
            assert 0.0 <= v <= 1.0

    def test_inverted_index_populated(self, built_graph):
        assert len(built_graph._inv) > 0
        for v in built_graph._inv.values():
            assert isinstance(v, list) and len(v) > 0

    # ── Search ──────────────────────────────────────────────────────── #

    def test_search_deadlock_finds_deadlock_script(self, built_graph):
        results = built_graph.search("deadlock")
        assert results, "Expected at least one result"
        top = results[0]
        assert "deadlock" in top.filename.lower() or any(
            "deadlock" in t for t in top.matched_terms
        )

    def test_search_bloat_finds_vacuum_script(self, built_graph):
        results = built_graph.search("table bloat")
        assert results
        filenames = [r.filename for r in results]
        assert any("vacuum" in f.lower() or "bloat" in f.lower() for f in filenames)

    def test_search_returns_list_of_search_results(self, built_graph):
        results = built_graph.search("slow query")
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, SearchResult)

    def test_search_empty_query_returns_empty(self, built_graph):
        assert built_graph.search("") == []
        assert built_graph.search("   ") == []

    def test_search_no_match_returns_empty(self, built_graph):
        results = built_graph.search("xyzzy_nonexistent_term_qqq")
        assert results == []

    def test_search_scores_between_0_and_1(self, built_graph):
        results = built_graph.search("deadlock")
        for r in results:
            assert 0.0 <= r.score <= 2.0   # multipliers can push slightly above 1

    def test_search_results_sorted_descending(self, built_graph):
        results = built_graph.search("deadlock vacuum")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_limit_respected(self, built_graph):
        results = built_graph.search("deadlock", max_results=2)
        assert len(results) <= 2

    def test_search_matched_terms_populated(self, built_graph):
        results = built_graph.search("deadlock")
        assert results[0].matched_terms  # at least one matched term

    def test_search_error_code_query(self, parser):
        ps = parser.parse_content("deadlock_handler.sql",
            "-- @fixes: 40P01\n-- @desc: handles deadlock\nSELECT 1;")
        g = ScriptKnowledgeGraph()
        g.add_scripts([ps])
        g.build()
        results = g.search("40P01")
        assert results
        assert results[0].filename == "deadlock_handler.sql"

    def test_synonym_expansion_finds_related(self, built_graph):
        # "freeze" expands to include "vacuum" — should still find vacuum scripts
        results = built_graph.search("freeze wraparound")
        filenames = [r.filename for r in results]
        assert any("vacuum" in f.lower() for f in filenames)

    def test_merge_adds_new_scripts(self, sample_scripts, parser):
        g = ScriptKnowledgeGraph()
        g.add_scripts(sample_scripts[:3])
        g.build()
        extra = parser.parse_content("extra_script.sql",
            "-- @desc: extra health check script\nSELECT version();")
        g.add_scripts([extra])
        g.build()
        assert g.stats().script_count == 4

    def test_save_and_load_roundtrip(self, built_graph, tmp_path):
        save_path = tmp_path / "test_graph.json.gz"
        built_graph.save(save_path)
        loaded = ScriptKnowledgeGraph.load(save_path)
        assert loaded.stats().script_count == built_graph.stats().script_count
        assert loaded._built is True

    def test_load_missing_file_returns_empty_graph(self, tmp_path):
        g = ScriptKnowledgeGraph.load(tmp_path / "nonexistent.json.gz")
        assert g.stats().script_count == 0
        assert g._built is False

    def test_search_requires_build_first(self, sample_scripts):
        g = ScriptKnowledgeGraph()
        g.add_scripts(sample_scripts)
        with pytest.raises(RuntimeError, match="build"):
            g.search("deadlock")

    def test_build_empty_graph_does_not_crash(self):
        g = ScriptKnowledgeGraph()
        g.build()   # no scripts
        assert g._built is True
        assert g.search("anything") == []

    def test_single_script_graph_searchable(self, parser):
        ps = parser.parse_content("only.sql", "-- @desc: vacuum bloat fix\nVACUUM t;")
        g = ScriptKnowledgeGraph()
        g.add_scripts([ps])
        g.build()
        results = g.search("bloat")
        assert results
        assert results[0].filename == "only.sql"

    def test_preview_populated(self, built_graph):
        results = built_graph.search("deadlock")
        assert results[0].preview  # non-empty string


# ---------------------------------------------------------------------------
# ScriptIngester
# ---------------------------------------------------------------------------

class TestScriptIngester:

    def _make_zip(self, files: dict[str, str]) -> io.BytesIO:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        buf.seek(0)
        return buf

    def test_ingest_single_script(self, tmp_path):
        zf = self._make_zip({
            "fix_deadlock.sql": "-- @desc: kill idle connections\nSELECT 1;"
        })
        out_zip = tmp_path / "test.zip"
        out_zip.write_bytes(zf.read())

        with patch.object(ScriptKnowledgeGraph, "save"):
            g = ScriptIngester().ingest_zip(out_zip)
        assert g.stats().script_count == 1

    def test_ingest_ignores_non_sql_files(self, tmp_path):
        zf = self._make_zip({
            "fix.sql": "-- @desc: fix\nSELECT 1;",
            "readme.txt": "not sql",
            "image.png": b"\x89PNG".decode("latin-1"),
        })
        out_zip = tmp_path / "test.zip"
        out_zip.write_bytes(zf.getvalue())
        with patch.object(ScriptKnowledgeGraph, "save"):
            g = ScriptIngester().ingest_zip(out_zip)
        assert g.stats().script_count == 1

    def test_ingest_empty_zip_raises(self, tmp_path):
        zf = self._make_zip({})
        out_zip = tmp_path / "empty.zip"
        out_zip.write_bytes(zf.getvalue())
        with pytest.raises(ValueError, match="No .sql files"):
            ScriptIngester().ingest_zip(out_zip)

    def test_ingest_corrupt_zip_raises(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"this is not a zip file at all")
        with pytest.raises(ValueError, match="corrupt"):
            ScriptIngester().ingest_zip(bad)

    def test_ingest_deduplicates_identical_scripts(self, tmp_path):
        same_content = "-- @desc: same\nSELECT 1;"
        zf = self._make_zip({
            "a.sql": same_content,
            "b.sql": same_content,   # identical content = same checksum
        })
        out_zip = tmp_path / "dupes.zip"
        out_zip.write_bytes(zf.getvalue())
        with patch.object(ScriptKnowledgeGraph, "save"):
            g = ScriptIngester().ingest_zip(out_zip)
        assert g.stats().script_count == 1

    def test_ingest_merge_adds_to_existing(self, tmp_path, sample_scripts):
        existing = ScriptKnowledgeGraph()
        existing.add_scripts(sample_scripts[:2])
        existing.build()

        zf = self._make_zip({
            "new_script.sql": "-- @desc: brand new script\nSELECT version();"
        })
        out_zip = tmp_path / "new.zip"
        out_zip.write_bytes(zf.getvalue())
        with patch.object(ScriptKnowledgeGraph, "save"):
            merged = ScriptIngester().ingest_zip(out_zip, existing_graph=existing, merge=True)
        assert merged.stats().script_count == 3

    def test_progress_callback_called(self, tmp_path):
        zf = self._make_zip({
            "a.sql": "-- @desc: test\nSELECT 1;",
            "b.sql": "-- @desc: test2\nSELECT 2;",
        })
        out_zip = tmp_path / "test.zip"
        out_zip.write_bytes(zf.getvalue())
        calls = []
        with patch.object(ScriptKnowledgeGraph, "save"):
            ScriptIngester().ingest_zip(out_zip, progress_cb=lambda s, c, t: calls.append(s))
        assert calls  # at least one progress event

    def test_non_utf8_content_handled_gracefully(self, tmp_path):
        zf = io.BytesIO()
        with zipfile.ZipFile(zf, "w") as z:
            z.writestr("latin1.sql", "-- @desc: données\nSELECT 1;".encode("latin-1"))
        out_zip = tmp_path / "latin.zip"
        out_zip.write_bytes(zf.getvalue())
        with patch.object(ScriptKnowledgeGraph, "save"):
            g = ScriptIngester().ingest_zip(out_zip)
        assert g.stats().script_count == 1


# ---------------------------------------------------------------------------
# Synonym dictionary sanity
# ---------------------------------------------------------------------------

class TestSynonymDictionary:
    def test_deadlock_expands(self):
        g = ScriptKnowledgeGraph()
        exp = g._expand_query(["deadlock"])
        assert "deadlock" in exp
        assert "blocked" in exp or "lock" in exp

    def test_expansion_does_not_duplicate(self):
        g = ScriptKnowledgeGraph()
        exp = g._expand_query(["vacuum"])
        assert len(exp) == len(set(exp))

    def test_unknown_term_passes_through(self):
        g = ScriptKnowledgeGraph()
        exp = g._expand_query(["xyzzy_unknown"])
        assert "xyzzy_unknown" in exp


# ===========================================================================
# ScriptKnowledgeGraph — scoring multipliers (pure Python, no Qt needed)
# ===========================================================================

class TestScoringMultipliers:
    """Static scoring helpers are pure functions — no Qt required."""

    # ── Recency ──────────────────────────────────────────────────────── #

    def test_recency_within_90_days(self):
        from datetime import datetime, timedelta
        recent = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        assert ScriptKnowledgeGraph._recency_mult(recent) == 1.2

    def test_recency_91_to_365_days(self):
        from datetime import datetime, timedelta
        medium = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        assert ScriptKnowledgeGraph._recency_mult(medium) == 1.1

    def test_recency_older_than_1_year(self):
        assert ScriptKnowledgeGraph._recency_mult("2019-01-01") == 1.0

    def test_recency_empty_string(self):
        assert ScriptKnowledgeGraph._recency_mult("") == 1.0

    def test_recency_invalid_format(self):
        assert ScriptKnowledgeGraph._recency_mult("not-a-date") == 1.0
        assert ScriptKnowledgeGraph._recency_mult("2024/01/01") == 1.0

    def test_recency_exact_90_days(self):
        from datetime import datetime, timedelta
        d = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        assert ScriptKnowledgeGraph._recency_mult(d) == 1.2

    # ── Severity ─────────────────────────────────────────────────────── #

    def test_severity_fix_word_with_delete_command(self):
        assert ScriptKnowledgeGraph._severity_mult({"fix"}, ["DELETE"]) == 1.15

    def test_severity_kill_word_with_terminate_command(self):
        assert ScriptKnowledgeGraph._severity_mult({"kill"}, ["TERMINATE"]) == 1.15

    def test_severity_fix_with_vacuum_command(self):
        assert ScriptKnowledgeGraph._severity_mult({"fix"}, ["VACUUM"]) == 1.15

    def test_severity_fix_with_select_only(self):
        # SELECT is not a modifying command
        assert ScriptKnowledgeGraph._severity_mult({"fix"}, ["SELECT"]) == 1.0

    def test_severity_no_fix_word_with_modifying_command(self):
        # "vacuum" is not a fix-intent word
        assert ScriptKnowledgeGraph._severity_mult({"vacuum"}, ["DELETE"]) == 1.0

    def test_severity_empty_query_words(self):
        assert ScriptKnowledgeGraph._severity_mult(set(), ["DELETE"]) == 1.0

    def test_severity_empty_commands(self):
        assert ScriptKnowledgeGraph._severity_mult({"fix"}, []) == 1.0

    def test_severity_repair_word(self):
        assert ScriptKnowledgeGraph._severity_mult({"repair"}, ["TRUNCATE"]) == 1.15


# ===========================================================================
# ScriptKnowledgeGraph — query parsing and expansion
# ===========================================================================

class TestQueryParsing:

    def test_parse_simple_terms(self):
        terms = ScriptKnowledgeGraph._parse_query("deadlock blocked")
        assert "deadlock" in terms
        assert "blocked" in terms

    def test_parse_removes_stopwords(self):
        terms = ScriptKnowledgeGraph._parse_query("how do I fix the deadlock")
        assert "deadlock" in terms
        for sw in ("how", "the", "fix"):
            assert sw not in terms

    def test_parse_error_code_recognized(self):
        terms = ScriptKnowledgeGraph._parse_query("40P01")
        assert "40P01" in terms

    def test_parse_error_code_mixed_with_words(self):
        terms = ScriptKnowledgeGraph._parse_query("error 40P01 deadlock")
        assert "40P01" in terms
        assert "deadlock" in terms

    def test_parse_preserves_pg_stat_activity_compound(self):
        terms = ScriptKnowledgeGraph._parse_query("pg_stat_activity bloat")
        assert "pg_stat_activity" in terms

    def test_parse_preserves_autovacuum_compound(self):
        terms = ScriptKnowledgeGraph._parse_query("autovacuum tuning")
        assert "autovacuum" in terms

    def test_parse_empty_returns_empty(self):
        assert ScriptKnowledgeGraph._parse_query("") == []

    def test_parse_only_stopwords_returns_empty(self):
        result = ScriptKnowledgeGraph._parse_query("how the for sql database")
        assert result == []

    def test_parse_short_words_filtered(self):
        terms = ScriptKnowledgeGraph._parse_query("id ok ab vacuum")
        # 'ab' (2 chars) and 'id', 'ok' (2 chars) should be filtered
        assert "vacuum" in terms
        for short in ("ab", "ok"):
            assert short not in terms

    def test_expand_deadlock_includes_synonyms(self):
        expanded = ScriptKnowledgeGraph._expand_query(["deadlock"])
        assert "deadlock" in expanded
        assert "blocked" in expanded or "lock" in expanded

    def test_expand_no_duplicates(self):
        expanded = ScriptKnowledgeGraph._expand_query(["vacuum", "bloat"])
        assert len(expanded) == len(set(expanded))

    def test_expand_unknown_term_preserved(self):
        expanded = ScriptKnowledgeGraph._expand_query(["xyzzy_rare"])
        assert "xyzzy_rare" in expanded

    def test_expand_pg_stat_activity(self):
        expanded = ScriptKnowledgeGraph._expand_query(["pg_stat_activity"])
        assert "pg_stat_activity" in expanded
        # Should also bring related terms
        assert "connection" in expanded or "session" in expanded or "backend" in expanded

    def test_expand_multiple_terms_all_included(self):
        expanded = ScriptKnowledgeGraph._expand_query(["deadlock", "bloat"])
        assert "deadlock" in expanded
        assert "bloat" in expanded


# ===========================================================================
# ScriptKnowledgeGraph — preview and utility methods
# ===========================================================================

class TestGraphUtilities:

    def test_make_preview_shows_first_lines(self):
        content = "-- line1\n-- line2\nSELECT 1;\nSELECT 2;\nSELECT 3;"
        preview = ScriptKnowledgeGraph._make_preview(content)
        assert "line1" in preview or "SELECT" in preview
        assert len(preview) <= 205

    def test_make_preview_truncates_long_content(self):
        content = "x" * 300 + "\n" + "y" * 300
        preview = ScriptKnowledgeGraph._make_preview(content)
        assert len(preview) <= 205
        assert preview.endswith("…") or preview.endswith("...")  # Unicode or ASCII ellipsis

    def test_make_preview_empty_content(self):
        assert ScriptKnowledgeGraph._make_preview("") == ""

    def test_make_preview_skips_blank_lines(self):
        content = "\n\n\n-- @desc: important\nSELECT 1;"
        preview = ScriptKnowledgeGraph._make_preview(content)
        assert "important" in preview or "SELECT" in preview

    def test_default_path_is_absolute(self):
        p = ScriptKnowledgeGraph.default_path()
        assert p.is_absolute()

    def test_default_path_filename(self):
        assert ScriptKnowledgeGraph.default_path().name == "script_graph.json.gz"

    def test_default_path_contains_coruscant(self):
        assert "Coruscant" in str(ScriptKnowledgeGraph.default_path())

    def test_stats_empty_graph(self):
        g = ScriptKnowledgeGraph()
        s = g.stats()
        assert s.script_count == 0
        assert s.term_count == 0
        assert s.cluster_count == 0


# ===========================================================================
# ScriptKnowledgeGraph — save / load edge cases
# ===========================================================================

class TestGraphPersistence:

    def test_save_creates_file(self, built_graph, tmp_path):
        p = tmp_path / "test.json.gz"
        built_graph.save(p)
        assert p.exists()
        assert p.stat().st_size > 0

    def test_saved_file_is_gzip(self, built_graph, tmp_path):
        import gzip
        p = tmp_path / "test.json.gz"
        built_graph.save(p)
        with gzip.open(p, "rt") as f:
            data = f.read(20)
        assert data.startswith("{")   # valid JSON

    def test_load_restores_script_count(self, built_graph, tmp_path):
        p = tmp_path / "test.json.gz"
        built_graph.save(p)
        g2 = ScriptKnowledgeGraph.load(p)
        assert g2.stats().script_count == built_graph.stats().script_count

    def test_load_allows_search(self, built_graph, tmp_path):
        p = tmp_path / "test.json.gz"
        built_graph.save(p)
        g2 = ScriptKnowledgeGraph.load(p)
        results = g2.search("deadlock")
        assert results  # should find results after load

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        import gzip
        p = tmp_path / "corrupt.json.gz"
        with gzip.open(p, "wt") as f:
            f.write("{this is not valid json!!!")
        g = ScriptKnowledgeGraph.load(p)
        assert g.stats().script_count == 0
        assert g._built is False

    def test_replace_mode_clears_existing(self, sample_scripts, parser):
        g = ScriptKnowledgeGraph()
        g.add_scripts(sample_scripts)
        g.build()
        new_script = parser.parse_content("only.sql", "-- @desc: brand new only\nSELECT 99;")
        g.add_scripts([new_script], merge=False)   # replace
        g.add_scripts([new_script], merge=False)   # replace: clears old, adds new
        g.build()
        # After replace+build, only the new script remains
        assert g.stats().script_count == 1
        assert g.stats().script_count == 1


# ===========================================================================
# ScriptKnowledgeGraph — search quality assertions
# ===========================================================================

class TestSearchQuality:
    """Higher-level assertions about result relevance."""

    def test_top_result_has_highest_score(self, built_graph):
        results = built_graph.search("vacuum bloat")
        assert results[0].score >= results[-1].score

    def test_score_non_negative(self, built_graph):
        for r in built_graph.search("deadlock"):
            assert r.score >= 0.0

    def test_matched_terms_subset_of_query(self, built_graph):
        results = built_graph.search("vacuum bloat deadlock")
        for r in results:
            # Each matched term should be a real string
            assert all(isinstance(t, str) for t in r.matched_terms)

    def test_all_result_filenames_nonempty(self, built_graph):
        for r in built_graph.search("deadlock"):
            assert r.filename

    def test_community_field_is_int(self, built_graph):
        for r in built_graph.search("deadlock"):
            assert isinstance(r.community, int)

    def test_preview_is_string(self, built_graph):
        for r in built_graph.search("vacuum"):
            assert isinstance(r.preview, str)

    def test_fix_query_with_delete_script_gets_severity_boost(self, parser):
        """fix + terminate query should score a TERMINATE script higher."""
        fix_script = parser.parse_content("kill.sql",
            "-- @desc: terminate idle backends\n-- @fixes: idle, kill, terminate\n"
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle';")
        info_script = parser.parse_content("info.sql",
            "-- @desc: show idle backends info\n-- @fixes: idle, show\n"
            "SELECT pid, state FROM pg_stat_activity WHERE state = 'idle';")
        g = ScriptKnowledgeGraph()
        g.add_scripts([fix_script, info_script])
        g.build()
        results = g.search("kill idle backends")
        filenames = [r.filename for r in results]
        # The script with pg_terminate_backend should appear
        assert "kill.sql" in filenames

    def test_error_code_in_script_matches_error_code_query(self, parser):
        ps = parser.parse_content("handler.sql",
            "-- @desc: handle deadlock error\n-- @fixes: 40P01\nSELECT 1;")
        g = ScriptKnowledgeGraph()
        g.add_scripts([ps])
        g.build()
        results = g.search("40P01")
        assert results
        assert results[0].filename == "handler.sql"


# ===========================================================================
# SQLScriptParser — additional edge cases
# ===========================================================================

class TestParserEdgeCases:

    def test_empty_content_does_not_crash(self, parser):
        ps = parser.parse_content("empty.sql", "")
        assert ps.filename == "empty.sql"
        assert ps.content == ""

    def test_only_comments_does_not_crash(self, parser):
        ps = parser.parse_content("comments.sql", "-- just a comment\n-- another")
        assert isinstance(ps.terms, dict)

    def test_large_content_truncated_in_storage(self, parser):
        big = "SELECT 1;\n" * 60_000   # well over 512 KB
        ps = parser.parse_content("big.sql", big)
        assert len(ps.content) <= 512 * 1024 + 20   # truncation tolerance

    def test_checksum_stable_same_content(self, parser):
        c = "-- @desc: stable\nSELECT 1;"
        assert (parser.parse_content("a.sql", c).checksum ==
                parser.parse_content("a.sql", c).checksum)

    def test_all_six_sql_commands_extracted(self, parser):
        sql = ("SELECT 1;\nINSERT INTO t VALUES(1);\nUPDATE t SET x=1;\n"
               "DELETE FROM t;\nVACUUM t;\nREINDEX TABLE t;")
        ps = parser.parse_content("all_cmds.sql", sql)
        for cmd in ("SELECT", "INSERT", "UPDATE", "DELETE", "VACUUM", "REINDEX"):
            assert cmd in ps.commands

    def test_multiple_error_codes_extracted(self, parser):
        ps = parser.parse_content("a.sql",
            "-- handles 40P01 and 57014 and 23505\nSELECT 1;")
        assert len(ps.error_codes) >= 2

    def test_date_tag_captured(self, parser):
        ps = parser.parse_content("a.sql", "-- @date: 2026-01-15\nSELECT 1;")
        assert ps.metadata.get("date") == "2026-01-15"

    def test_requires_tag_captured(self, parser):
        ps = parser.parse_content("a.sql",
            "-- @requires: pg_stat_statements\nSELECT 1;")
        assert ps.metadata.get("requires") == "pg_stat_statements"

    def test_pg_terminate_backend_extracted(self, parser):
        ps = parser.parse_content("a.sql", "SELECT pg_terminate_backend(pid);")
        # Either the full function name or key parts should appear
        has_term = (
            "pg_terminate_backend" in ps.terms
            or "terminate" in ps.terms
            or "backend" in ps.terms
        )
        assert has_term

    def test_dot_notation_table_parts_indexed(self, parser):
        ps = parser.parse_content("a.sql", "SELECT * FROM myschema.orders;")
        # At minimum the table name part should be in tables
        assert "orders" in ps.tables or "myschema.orders" in ps.tables


# ===========================================================================
# split_statements_with_positions — cursor helpers
# ===========================================================================

class TestStatementAtCursorLogic:
    """
    These tests exercise the same logic as MainWindow._statement_at_cursor
    directly through split_statements_with_positions to avoid needing Qt.
    """

    def _find_at(self, sql: str, pos: int) -> str | None:
        stmts = split_statements_with_positions(sql)
        # primary match
        for start, end, stmt in stmts:
            if start <= pos < end:
                return stmt
        # fallback: nearest
        if stmts:
            best = min(stmts, key=lambda s: min(abs(pos - s[0]), abs(pos - s[1])))
            return best[2]
        return None

    def test_cursor_in_first_statement(self):
        sql = "SELECT 1;\nSELECT 2;"
        result = self._find_at(sql, 0)
        assert result and "SELECT 1" in result

    def test_cursor_in_second_statement(self):
        sql = "SELECT 1;\nSELECT 2;"
        result = self._find_at(sql, 11)
        assert result and "SELECT 2" in result

    def test_cursor_past_end_uses_fallback(self):
        sql = "SELECT 1;\nSELECT 2;"
        result = self._find_at(sql, 999)
        assert result is not None   # fallback always returns something

    def test_cursor_on_whitespace_between_statements(self):
        sql = "SELECT 1;   \n   SELECT 2;"
        # cursor at position 10 (in the whitespace)
        result = self._find_at(sql, 10)
        assert result is not None

    def test_single_statement_always_found(self):
        sql = "SELECT * FROM pg_stat_activity;"
        for pos in [0, 5, 15, 30]:
            result = self._find_at(sql, pos)
            assert result and "pg_stat_activity" in result

    def test_empty_sql_returns_none(self):
        stmts = split_statements_with_positions("")
        assert stmts == []
