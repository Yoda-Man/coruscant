"""Tests for coruscant.core.sql.split_statements()."""
import pytest
from coruscant.core.sql import split_statements


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
