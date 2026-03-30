"""
coruscant.utils.highlighter
~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQL syntax highlighter for QPlainTextEdit.

Colours (VS Code Dark+ inspired):
  Keywords   → blue   #569cd6
  Functions  → yellow #dcdcaa
  Strings    → orange #ce9178
  Numbers    → green  #b5cea8
  Comments   → grey   #6a9955  (italic)
  Operators  → white  #d4d4d4

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import re

from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont


_KEYWORDS = (
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "EXISTS",
    "LIKE", "ILIKE", "SIMILAR", "BETWEEN", "IS", "NULL", "TRUE", "FALSE",
    "DEFAULT", "ANY", "ALL", "SOME",
    "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE", "TRUNCATE",
    "CREATE", "TABLE", "VIEW", "INDEX", "SEQUENCE", "SCHEMA", "DATABASE",
    "DROP", "ALTER", "ADD", "COLUMN", "RENAME", "MODIFY",
    "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "CROSS",
    "NATURAL", "ON", "USING",
    "GROUP", "BY", "ORDER", "ASC", "DESC", "HAVING",
    "LIMIT", "OFFSET", "FETCH", "NEXT", "ROWS", "ONLY",
    "UNION", "INTERSECT", "EXCEPT", "DISTINCT", "AS", "WITH",
    "CASE", "WHEN", "THEN", "ELSE", "END",
    "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "UNIQUE", "CHECK",
    "CONSTRAINT", "NOT", "NULL", "DEFAULT",
    "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "TRANSACTION",
    "RETURNING", "OVER", "PARTITION", "WINDOW", "FILTER",
    "DO", "DECLARE", "RAISE", "IF", "ELSIF", "LOOP", "EXIT",
    "PERFORM", "RETURN", "LANGUAGE", "FUNCTION", "PROCEDURE",
    "TRIGGER", "RULE", "GRANT", "REVOKE", "TO", "PUBLIC",
    "SERIAL", "BIGSERIAL", "INTEGER", "BIGINT", "SMALLINT",
    "TEXT", "VARCHAR", "CHAR", "BOOLEAN", "BOOL",
    "NUMERIC", "DECIMAL", "REAL", "FLOAT", "DOUBLE", "PRECISION",
    "DATE", "TIME", "TIMESTAMP", "INTERVAL", "UUID", "JSON", "JSONB",
    "ARRAY", "ROW", "RECORD", "VOID", "SETOF",
)

_FUNCTIONS = (
    "COUNT", "SUM", "AVG", "MAX", "MIN", "STDDEV", "VARIANCE",
    "NOW", "CURRENT_DATE", "CURRENT_TIME", "CURRENT_TIMESTAMP",
    "EXTRACT", "DATE_PART", "DATE_TRUNC", "AGE", "MAKE_DATE",
    "TO_CHAR", "TO_DATE", "TO_TIMESTAMP", "TO_NUMBER",
    "UPPER", "LOWER", "INITCAP", "TRIM", "LTRIM", "RTRIM",
    "LENGTH", "CHAR_LENGTH", "SUBSTRING", "SUBSTR", "POSITION",
    "REPLACE", "REGEXP_REPLACE", "SPLIT_PART", "CONCAT", "FORMAT",
    "COALESCE", "NULLIF", "GREATEST", "LEAST",
    "CAST", "CONVERT",
    "ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE",
    "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE", "NTH_VALUE",
    "GENERATE_SERIES", "UNNEST", "ARRAY_AGG", "STRING_AGG",
    "JSON_AGG", "JSON_BUILD_OBJECT", "JSONB_AGG",
    "MD5", "ENCODE", "DECODE",
)


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class SQLHighlighter(QSyntaxHighlighter):
    """Single-pass regex-based SQL syntax highlighter."""

    def __init__(self, document) -> None:
        super().__init__(document)

        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = [
            # Keywords — whole-word, case-insensitive
            (re.compile(r'\b(?:' + '|'.join(_KEYWORDS) + r')\b', re.IGNORECASE),
             _fmt('#569cd6', bold=True)),

            # Built-in functions — word followed by optional space + '('
            (re.compile(r'\b(?:' + '|'.join(_FUNCTIONS) + r')\b(?=\s*\()',
                        re.IGNORECASE),
             _fmt('#dcdcaa')),

            # Operators
            (re.compile(r'(?:<>|!=|<=|>=|::|\|\||[=<>+\-*/%])'),
             _fmt('#d4d4d4')),

            # Single-quoted strings  (handles '' escapes, single-line)
            (re.compile(r"'(?:[^'\\]|\\.)*(?:''[^']*)*'"),
             _fmt('#ce9178')),

            # Dollar-quoted strings  $$…$$  (single-line only)
            (re.compile(r'\$\w*\$[^\$]*\$\w*\$'),
             _fmt('#ce9178')),

            # Numeric literals
            (re.compile(r'\b\d+(?:\.\d+)?\b'),
             _fmt('#b5cea8')),

            # Single-line comments  --…
            (re.compile(r'--[^\n]*'),
             _fmt('#6a9955', italic=True)),
        ]

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
