"""Tests for coruscant.core.sql — split_statements and split_statements_with_positions."""
import pytest
from coruscant.core.sql import split_statements, split_statements_with_positions


# ---------------------------------------------------------------------------
# Basic splitting
# ---------------------------------------------------------------------------

def test_empty_string():
    assert split_statements("") == []


def test_whitespace_only():
    assert split_statements("   \n\t  ") == []


def test_only_semicolons():
    assert split_statements(";;;") == []


def test_single_statement_no_semicolon():
    assert split_statements("SELECT 1") == ["SELECT 1"]


def test_single_statement_with_semicolon():
    assert split_statements("SELECT 1;") == ["SELECT 1"]


def test_two_statements():
    result = split_statements("SELECT 1; SELECT 2;")
    assert result == ["SELECT 1", "SELECT 2"]


def test_three_statements():
    result = split_statements("SELECT 1; SELECT 2; SELECT 3;")
    assert len(result) == 3
    assert result[2] == "SELECT 3"


def test_trailing_statement_without_semicolon():
    result = split_statements("SELECT 1; SELECT 2")
    assert result == ["SELECT 1", "SELECT 2"]


def test_leading_and_trailing_whitespace_stripped():
    result = split_statements("  SELECT 1  ;  SELECT 2  ;  ")
    assert result == ["SELECT 1", "SELECT 2"]


def test_multiline_statement():
    sql = """
SELECT
    id,
    name
FROM users
WHERE id = 1;
"""
    result = split_statements(sql)
    assert len(result) == 1
    assert "SELECT" in result[0]
    assert "users" in result[0]


# ---------------------------------------------------------------------------
# Single-quoted strings
# ---------------------------------------------------------------------------

def test_semicolon_inside_single_quoted_string():
    result = split_statements("SELECT 'hello;world';")
    assert result == ["SELECT 'hello;world'"]


def test_escaped_quote_inside_string():
    result = split_statements("SELECT 'it''s fine';")
    assert result == ["SELECT 'it''s fine'"]


def test_multiple_escaped_quotes():
    result = split_statements("SELECT 'a''b''c';")
    assert result == ["SELECT 'a''b''c'"]


def test_semicolons_and_quotes_together():
    result = split_statements("SELECT 'a;b'; SELECT 'c;d';")
    assert result == ["SELECT 'a;b'", "SELECT 'c;d'"]


# ---------------------------------------------------------------------------
# Double-quoted identifiers
# ---------------------------------------------------------------------------

def test_semicolon_inside_double_quoted_identifier():
    result = split_statements('SELECT "my;column" FROM t;')
    assert result == ['SELECT "my;column" FROM t']


def test_escaped_double_quote_in_identifier():
    result = split_statements('SELECT "col""name" FROM t;')
    assert result == ['SELECT "col""name" FROM t']


# ---------------------------------------------------------------------------
# Single-line comments  --
# ---------------------------------------------------------------------------

def test_semicolon_in_single_line_comment():
    sql = "SELECT 1 -- this; is a comment\n;"
    result = split_statements(sql)
    assert len(result) == 1
    assert result[0].startswith("SELECT 1")


def test_comment_at_end_no_newline():
    # Comment with no trailing newline — everything after -- is consumed
    result = split_statements("SELECT 1 -- trailing comment")
    assert len(result) == 1


def test_two_statements_with_inline_comments():
    # The parser's -- handler stops at the \n but does not consume it; the \n
    # character re-enters the main loop and is appended to the next buffer.
    # So "-- first\nSELECT 2" becomes one statement and "-- second" becomes
    # another — three items total.
    sql = "SELECT 1; -- first\nSELECT 2; -- second\n"
    result = split_statements(sql)
    assert len(result) == 3
    assert result[0] == "SELECT 1"
    assert "SELECT 2" in result[1]
    assert "-- second" in result[2]


# ---------------------------------------------------------------------------
# Block comments  /* … */
# ---------------------------------------------------------------------------

def test_semicolon_inside_block_comment():
    result = split_statements("SELECT 1 /* some; comment */;")
    assert result == ["SELECT 1 /* some; comment */"]


def test_block_comment_spanning_content():
    result = split_statements("/* preamble */ SELECT 1;")
    assert len(result) == 1
    assert "SELECT 1" in result[0]


def test_unterminated_block_comment_does_not_crash():
    # Unterminated comment — parser consumes to end of string
    result = split_statements("SELECT /* unclosed")
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Mixed / complex cases
# ---------------------------------------------------------------------------

def test_string_and_identifier_with_semicolons():
    sql = "SELECT 'v;1', \"col;x\" FROM t;"
    result = split_statements(sql)
    assert len(result) == 1


def test_realistic_migration_script():
    sql = """
-- Create table
CREATE TABLE users (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

-- Seed data
INSERT INTO users (name) VALUES ('Alice'), ('Bob');

-- Verify
SELECT * FROM users;
"""
    result = split_statements(sql)
    assert len(result) == 3


def test_update_and_select():
    sql = "UPDATE t SET x = 'a;b' WHERE id = 1; SELECT count(*) FROM t;"
    result = split_statements(sql)
    assert len(result) == 2
    assert result[0].startswith("UPDATE")
    assert result[1].startswith("SELECT")


def test_statement_with_both_comment_types():
    sql = """
/* block comment; here */
SELECT id -- inline; comment
FROM t;
"""
    result = split_statements(sql)
    assert len(result) == 1
    assert "SELECT" in result[0]


# ===========================================================================
# split_statements_with_positions
# ===========================================================================

class TestSplitStatementsWithPositions:
    """Tests for split_statements_with_positions(sql) -> list[(start, end, text)]."""

    # ── Basic structure ──────────────────────────────────────────────── #

    def test_empty_string_returns_empty(self):
        assert split_statements_with_positions("") == []

    def test_whitespace_only_returns_empty(self):
        assert split_statements_with_positions("   \n\t  ") == []

    def test_only_semicolons_returns_empty(self):
        assert split_statements_with_positions(";;;") == []

    def test_single_statement_no_semicolon(self):
        result = split_statements_with_positions("SELECT 1")
        assert len(result) == 1
        start, end, text = result[0]
        assert text == "SELECT 1"
        assert start == 0
        assert end == 8   # end of string (no semicolon)

    def test_single_statement_with_semicolon(self):
        result = split_statements_with_positions("SELECT 1;")
        assert len(result) == 1
        start, end, text = result[0]
        assert text.startswith("SELECT 1")
        assert start == 0
        assert end == 9   # past the semicolon

    def test_two_statements_count(self):
        result = split_statements_with_positions("SELECT 1; SELECT 2;")
        assert len(result) == 2

    def test_two_statements_text(self):
        result = split_statements_with_positions("SELECT 1; SELECT 2;")
        texts = [t for _, _, t in result]
        assert "SELECT 1" in texts[0]
        assert "SELECT 2" in texts[1]

    def test_three_statements_count(self):
        result = split_statements_with_positions("SELECT 1; SELECT 2; SELECT 3;")
        assert len(result) == 3

    # ── Position accuracy ────────────────────────────────────────────── #

    def test_positions_are_non_overlapping(self):
        sql = "SELECT 1;\nSELECT 2;\nSELECT 3;"
        result = split_statements_with_positions(sql)
        assert len(result) == 3
        for i in range(len(result) - 1):
            _, end_a, _ = result[i]
            start_b, _, _ = result[i + 1]
            assert end_a <= start_b, "Statement spans must not overlap"

    def test_positions_cover_non_whitespace_chars(self):
        """Every non-whitespace character in the SQL must fall inside some span."""
        sql = "SELECT 1; SELECT 2;"
        result = split_statements_with_positions(sql)
        covered = set()
        for start, end, _ in result:
            covered.update(range(start, end))
        for i, ch in enumerate(sql):
            if ch.strip():
                assert i in covered, f"char {ch!r} at pos {i} not covered by any span"

    def test_start_skips_leading_whitespace(self):
        sql = "  SELECT 1;"   # two leading spaces
        result = split_statements_with_positions(sql)
        assert len(result) == 1
        start, _, _ = result[0]
        assert start == 2   # first 'S', not the spaces

    def test_second_start_is_after_first_end(self):
        sql = "SELECT 1; SELECT 2;"
        result = split_statements_with_positions(sql)
        end_first    = result[0][1]
        start_second = result[1][0]
        assert start_second >= end_first

    # ── Cursor-finding contract ──────────────────────────────────────── #

    def test_cursor_at_pos_0_hits_first_statement(self):
        sql = "SELECT 1; SELECT 2;"
        stmts = split_statements_with_positions(sql)
        hit = [s for a, b, s in stmts if a <= 0 < b]
        assert len(hit) == 1 and "SELECT 1" in hit[0]

    def test_cursor_mid_second_statement(self):
        sql = "SELECT 1;\nSELECT 2;"
        stmts = split_statements_with_positions(sql)
        # 'SELECT 2' starts at pos 10; test cursor at pos 14 (mid-word)
        hit = [s for a, b, s in stmts if a <= 14 < b]
        assert len(hit) == 1 and "SELECT 2" in hit[0]

    def test_no_position_matches_two_statements(self):
        """No character position should map to more than one statement."""
        sql = "SELECT 1; SELECT 2; SELECT 3;"
        stmts = split_statements_with_positions(sql)
        for pos in range(len(sql)):
            matches = [s for a, b, s in stmts if a <= pos < b]
            assert len(matches) <= 1, f"pos {pos} matched {len(matches)} statements"

    # ── Quote / comment handling ─────────────────────────────────────── #

    def test_semicolon_inside_single_quoted_string_not_a_split(self):
        result = split_statements_with_positions("SELECT 'a;b';")
        assert len(result) == 1
        assert "'a;b'" in result[0][2]

    def test_semicolon_inside_double_quoted_identifier_not_a_split(self):
        result = split_statements_with_positions('SELECT "col;x" FROM t;')
        assert len(result) == 1

    def test_semicolon_in_single_line_comment_not_a_split(self):
        sql = "SELECT 1 -- comment; here\n;"
        result = split_statements_with_positions(sql)
        assert len(result) == 1

    def test_semicolon_in_block_comment_not_a_split(self):
        result = split_statements_with_positions("SELECT 1 /* a; b */;")
        assert len(result) == 1

    def test_realistic_multi_statement(self):
        sql = (
            "CREATE TABLE t (id SERIAL);\n"
            "INSERT INTO t VALUES (1);\n"
            "SELECT * FROM t;\n"
        )
        result = split_statements_with_positions(sql)
        assert len(result) == 3
        texts = [t for _, _, t in result]
        assert any("CREATE" in t for t in texts)
        assert any("INSERT" in t for t in texts)
        assert any("SELECT" in t for t in texts)

    # ── Consistency with split_statements ────────────────────────────── #

    def test_text_consistency_with_split_statements(self):
        """Stripped texts from both functions must agree."""
        sql = "SELECT 1; UPDATE t SET x=1 WHERE id=2; DELETE FROM t;"
        plain    = split_statements(sql)
        with_pos = split_statements_with_positions(sql)
        # with_pos includes the trailing semicolon; strip it for comparison
        pos_stripped   = [t.rstrip(";").strip() for _, _, t in with_pos]
        plain_stripped = [t.rstrip(";").strip() for t in plain]
        assert pos_stripped == plain_stripped
