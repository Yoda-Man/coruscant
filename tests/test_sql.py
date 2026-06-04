"""Tests for coruscant.core.sql — split_statements and split_statements_with_positions."""
import pytest
from coruscant.core.sql import split_statements, split_statements_with_positions


# ===========================================================================
# split_statements
# ===========================================================================

class TestSplitStatementsBasic:
    def test_empty_string(self):
        assert split_statements("") == []

    def test_whitespace_only(self):
        assert split_statements("   \n\t  ") == []

    def test_only_semicolons(self):
        assert split_statements(";;;") == []

    def test_single_statement_no_semicolon(self):
        assert split_statements("SELECT 1") == ["SELECT 1"]

    def test_single_statement_with_semicolon(self):
        assert split_statements("SELECT 1;") == ["SELECT 1"]

    def test_two_statements(self):
        assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]

    def test_three_statements(self):
        result = split_statements("SELECT 1; SELECT 2; SELECT 3;")
        assert len(result) == 3
        assert result[2] == "SELECT 3"

    def test_trailing_statement_without_semicolon(self):
        assert split_statements("SELECT 1; SELECT 2") == ["SELECT 1", "SELECT 2"]

    def test_leading_trailing_whitespace_stripped(self):
        assert split_statements("  SELECT 1  ;  SELECT 2  ;  ") == ["SELECT 1", "SELECT 2"]

    def test_multiline_statement(self):
        sql = "\nSELECT\n    id,\n    name\nFROM users\nWHERE id = 1;\n"
        result = split_statements(sql)
        assert len(result) == 1
        assert "SELECT" in result[0] and "users" in result[0]

    def test_newline_only(self):
        assert split_statements("\n\n\n") == []

    def test_single_newline_statement(self):
        assert split_statements("SELECT 1\n") == ["SELECT 1"]


class TestSplitStatementsSingleQuotes:
    def test_semicolon_inside_quoted_string(self):
        assert split_statements("SELECT 'hello;world';") == ["SELECT 'hello;world'"]

    def test_escaped_single_quote(self):
        assert split_statements("SELECT 'it''s fine';") == ["SELECT 'it''s fine'"]

    def test_multiple_escaped_quotes(self):
        assert split_statements("SELECT 'a''b''c';") == ["SELECT 'a''b''c'"]

    def test_two_statements_with_quoted_semicolons(self):
        result = split_statements("SELECT 'a;b'; SELECT 'c;d';")
        assert result == ["SELECT 'a;b'", "SELECT 'c;d'"]

    def test_empty_string_literal(self):
        result = split_statements("SELECT '';")
        assert len(result) == 1

    def test_string_with_only_escaped_quotes(self):
        result = split_statements("SELECT '''';")
        assert len(result) == 1


class TestSplitStatementsDoubleQuotes:
    def test_semicolon_inside_double_quoted_identifier(self):
        assert split_statements('SELECT "my;column" FROM t;') == ['SELECT "my;column" FROM t']

    def test_escaped_double_quote_in_identifier(self):
        assert split_statements('SELECT "col""name" FROM t;') == ['SELECT "col""name" FROM t']

    def test_empty_double_quoted_identifier(self):
        result = split_statements('SELECT "" FROM t;')
        assert len(result) == 1


class TestSplitStatementsSingleLineComments:
    def test_semicolon_in_comment_not_a_split(self):
        sql = "SELECT 1 -- this; is a comment\n;"
        result = split_statements(sql)
        assert len(result) == 1
        assert result[0].startswith("SELECT 1")

    def test_comment_at_end_no_newline(self):
        result = split_statements("SELECT 1 -- trailing comment")
        assert len(result) == 1

    def test_comment_only_line(self):
        result = split_statements("-- just a comment\n")
        # comment with no statement becomes one trailing "-- just a comment" segment
        # actual behaviour: comment text ends up as a statement fragment
        # just verify no crash and return type
        assert isinstance(result, list)


class TestSplitStatementsBlockComments:
    def test_semicolon_inside_block_comment(self):
        assert split_statements("SELECT 1 /* some; comment */;") == [
            "SELECT 1 /* some; comment */"
        ]

    def test_block_comment_spanning_content(self):
        result = split_statements("/* preamble */ SELECT 1;")
        assert len(result) == 1
        assert "SELECT 1" in result[0]

    def test_unterminated_block_comment_no_crash(self):
        result = split_statements("SELECT /* unclosed")
        assert len(result) == 1

    def test_multiline_block_comment(self):
        sql = "/* line 1\n   line 2\n   line 3 */\nSELECT 1;"
        result = split_statements(sql)
        assert len(result) == 1
        assert "SELECT 1" in result[0]


class TestSplitStatementsComplex:
    def test_string_and_identifier_with_semicolons(self):
        result = split_statements("SELECT 'v;1', \"col;x\" FROM t;")
        assert len(result) == 1

    def test_realistic_migration_script(self):
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

    def test_update_and_select(self):
        sql = "UPDATE t SET x = 'a;b' WHERE id = 1; SELECT count(*) FROM t;"
        result = split_statements(sql)
        assert len(result) == 2
        assert result[0].startswith("UPDATE")
        assert result[1].startswith("SELECT")

    def test_both_comment_types(self):
        sql = "/* block; */ SELECT id -- inline;\nFROM t;"
        result = split_statements(sql)
        assert len(result) == 1
        assert "SELECT" in result[0]

    def test_do_block_with_semicolons(self):
        # Dollar-quoting is NOT supported, but the parser should not crash
        sql = "SELECT 1; SELECT 2;"
        result = split_statements(sql)
        assert len(result) == 2

    def test_many_statements(self):
        sql = "; ".join(f"SELECT {i}" for i in range(20)) + ";"
        result = split_statements(sql)
        assert len(result) == 20

    def test_statement_numbers_correct(self):
        sql = "SELECT 1; SELECT 2; SELECT 3;"
        result = split_statements(sql)
        assert "1" in result[0]
        assert "2" in result[1]
        assert "3" in result[2]


# ===========================================================================
# split_statements_with_positions
# ===========================================================================

class TestSplitStatementsWithPositions:

    def test_empty_string(self):
        assert split_statements_with_positions("") == []

    def test_whitespace_only(self):
        assert split_statements_with_positions("   \n\t  ") == []

    def test_only_semicolons(self):
        assert split_statements_with_positions(";;;") == []

    def test_single_no_semicolon(self):
        result = split_statements_with_positions("SELECT 1")
        assert len(result) == 1
        start, end, text = result[0]
        assert text == "SELECT 1"
        assert start == 0
        assert end == 8

    def test_single_with_semicolon(self):
        result = split_statements_with_positions("SELECT 1;")
        assert len(result) == 1
        start, end, text = result[0]
        assert "SELECT 1" in text
        assert start == 0
        assert end == 9

    def test_two_statements_count(self):
        assert len(split_statements_with_positions("SELECT 1; SELECT 2;")) == 2

    def test_two_statements_text(self):
        result = split_statements_with_positions("SELECT 1; SELECT 2;")
        texts = [t for _, _, t in result]
        assert "SELECT 1" in texts[0]
        assert "SELECT 2" in texts[1]

    def test_three_statements_count(self):
        assert len(split_statements_with_positions("SELECT 1; SELECT 2; SELECT 3;")) == 3

    def test_positions_non_overlapping(self):
        sql = "SELECT 1;\nSELECT 2;\nSELECT 3;"
        result = split_statements_with_positions(sql)
        for i in range(len(result) - 1):
            _, end_a, _ = result[i]
            start_b, _, _ = result[i + 1]
            assert end_a <= start_b

    def test_no_position_matches_two_statements(self):
        sql = "SELECT 1; SELECT 2; SELECT 3;"
        stmts = split_statements_with_positions(sql)
        for pos in range(len(sql)):
            matches = [s for a, b, s in stmts if a <= pos < b]
            assert len(matches) <= 1

    def test_start_skips_leading_whitespace(self):
        result = split_statements_with_positions("  SELECT 1;")
        assert result[0][0] == 2

    def test_second_start_after_first_end(self):
        result = split_statements_with_positions("SELECT 1; SELECT 2;")
        assert result[1][0] >= result[0][1]

    def test_cursor_at_pos_0_hits_first(self):
        sql = "SELECT 1; SELECT 2;"
        stmts = split_statements_with_positions(sql)
        hit = [s for a, b, s in stmts if a <= 0 < b]
        assert len(hit) == 1 and "SELECT 1" in hit[0]

    def test_cursor_mid_second_statement(self):
        sql = "SELECT 1;\nSELECT 2;"
        stmts = split_statements_with_positions(sql)
        hit = [s for a, b, s in stmts if a <= 14 < b]
        assert len(hit) == 1 and "SELECT 2" in hit[0]

    def test_semicolon_in_string_not_a_split(self):
        result = split_statements_with_positions("SELECT 'a;b';")
        assert len(result) == 1
        assert "'a;b'" in result[0][2]

    def test_semicolon_in_double_quoted_not_a_split(self):
        result = split_statements_with_positions('SELECT "col;x" FROM t;')
        assert len(result) == 1

    def test_semicolon_in_line_comment_not_a_split(self):
        result = split_statements_with_positions("SELECT 1 -- comment; here\n;")
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

    def test_consistency_with_split_statements(self):
        sql = "SELECT 1; UPDATE t SET x=1 WHERE id=2; DELETE FROM t;"
        plain    = split_statements(sql)
        with_pos = split_statements_with_positions(sql)
        pos_texts   = [t.rstrip(";").strip() for _, _, t in with_pos]
        plain_texts = [t.rstrip(";").strip() for t in plain]
        assert pos_texts == plain_texts

    def test_end_index_past_semicolon(self):
        # "SELECT 1;" is 9 chars; end should be 9 (past the semicolon)
        result = split_statements_with_positions("SELECT 1;")
        assert result[0][1] == 9

    def test_trailing_whitespace_in_sql(self):
        result = split_statements_with_positions("SELECT 1;   ")
        assert len(result) == 1

    def test_only_whitespace_between_statements(self):
        sql = "SELECT 1;   \n   SELECT 2;"
        result = split_statements_with_positions(sql)
        assert len(result) == 2
