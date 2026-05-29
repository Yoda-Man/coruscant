"""
coruscant.core.sql
~~~~~~~~~~~~~~~~~~
SQL statement splitter — the only SQL parsing logic in the application.

No GUI imports.  No database imports.  Pure string processing.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations


def split_statements(sql: str) -> list[str]:
    """
    Split a SQL script into individual statements at top-level semicolons.

    Correctly handles:
      • Single-quoted strings   'it''s fine'
      • Double-quoted identifiers  "my;column"
      • Single-line comments    -- comment
      • Block comments          /* comment */

    Returns a list of non-empty statement strings (semicolons stripped).
    """
    statements: list[str] = []
    current: list[str] = []
    i, n = 0, len(sql)

    while i < n:
        ch = sql[i]

        # Single-line comment  --…\n
        if ch == '-' and i + 1 < n and sql[i + 1] == '-':
            end = sql.find('\n', i)
            end = n if end == -1 else end
            current.append(sql[i:end])
            i = end
            continue

        # Block comment  /* … */
        if ch == '/' and i + 1 < n and sql[i + 1] == '*':
            end = sql.find('*/', i + 2)
            end = n if end == -1 else end + 2
            current.append(sql[i:end])
            i = end
            continue

        # Single-quoted string  '…''…'
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            current.append(sql[i:j + 1])
            i = j + 1
            continue

        # Double-quoted identifier  "…""…"
        if ch == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"' and j + 1 < n and sql[j + 1] == '"':
                    j += 2
                    continue
                if sql[j] == '"':
                    break
                j += 1
            current.append(sql[i:j + 1])
            i = j + 1
            continue

        # Semicolon — end of statement
        if ch == ';':
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    # Trailing statement without a final semicolon
    stmt = ''.join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


def split_statements_with_positions(sql: str) -> list[tuple[int, int, str]]:
    """
    Like ``split_statements`` but also returns the character-level span
    of each statement in the original *sql* string.

    Returns a list of ``(start, end, text)`` triples where:
      start — index of the first non-whitespace character of the statement
      end   — index just past the terminating semicolon (or end of *sql*)
      text  — the statement string (whitespace-stripped, semicolon excluded)

    Handles the same quoting / comment rules as ``split_statements``.
    """
    results: list[tuple[int, int, str]] = []
    seg_start = 0   # position in sql just after the last semicolon
    i, n = 0, len(sql)

    def _flush(end_i: int) -> None:
        segment = sql[seg_start:end_i]
        # Strip the trailing semicolon before the emptiness check so that a
        # segment consisting solely of ";" (e.g. from ";;;") is treated as
        # empty -- matching split_statements() which never adds ";" to its buffer.
        stmt = segment.rstrip(";").strip()
        if stmt:
            lead = len(segment) - len(segment.lstrip())
            results.append((seg_start + lead, end_i, stmt))

    while i < n:
        ch = sql[i]

        if ch == '-' and i + 1 < n and sql[i + 1] == '-':
            end = sql.find('\n', i)
            i = n if end == -1 else end
            continue

        if ch == '/' and i + 1 < n and sql[i + 1] == '*':
            end = sql.find('*/', i + 2)
            i = n if end == -1 else end + 2
            continue

        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            i = j + 1
            continue

        if ch == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"' and j + 1 < n and sql[j + 1] == '"':
                    j += 2
                    continue
                if sql[j] == '"':
                    break
                j += 1
            i = j + 1
            continue

        if ch == ';':
            _flush(i + 1)   # end_i includes the semicolon
            seg_start = i + 1
            i += 1
            continue

        i += 1

    _flush(n)
    return results
