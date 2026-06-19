"""
coruscant.core.qa_engine
~~~~~~~~~~~~~~~~~~~~~~~~
Schema quality-analysis engine.

Runs a suite of read-only checks against the connected database and returns
a QAReport with individual QAFinding entries.  All queries use parameterised
SQL; no DDL or DML is executed.

Checks
------
- orphaned_tables      : tables with no FK relationships (inbound or outbound)
- missing_fk_indexes   : FK columns that have no covering index
- circular_deps        : FK cycles detected via networkx
- nullable_fks         : FK columns that allow NULL (informational)
- naming_conventions   : table/column names that don't follow snake_case
- type_consistency     : same logical column name used with different types

Author: Marwa Trust Mutemasango
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# Severity levels
ERROR   = "ERROR"
WARNING = "WARNING"
INFO    = "INFO"

_SEVERITY_WEIGHT: dict[str, int] = {ERROR: 10, WARNING: 3, INFO: 1}
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# ── Data classes ──────────────────────────────────────────────────────── #

@dataclass
class QAFinding:
    """A single QA finding."""
    check:    str
    severity: str             # ERROR | WARNING | INFO
    message:  str
    table:    Optional[str] = None
    column:   Optional[str] = None
    fix_sql:  Optional[str] = None


@dataclass
class QAReport:
    """Aggregated QA results for one schema."""
    schema:   str
    findings: list[QAFinding] = field(default_factory=list)

    @property
    def health_score(self) -> int:
        """0-100 score: 100 = perfect, deducted per finding severity."""
        penalty = sum(_SEVERITY_WEIGHT.get(f.severity, 0) for f in self.findings)
        return max(0, 100 - penalty)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == INFO)


# ── Public entry point ────────────────────────────────────────────────── #

def run_qa(conn, schema: str) -> QAReport:
    """Run all QA checks against *schema* and return a :class:`QAReport`.

    Parameters
    ----------
    conn:
        A live psycopg2 connection.  This function opens its own cursor and
        never commits or rolls back.
    schema:
        PostgreSQL schema name to analyse.
    """
    report = QAReport(schema=schema)

    with conn.cursor() as cur:
        meta = _fetch_metadata(cur, schema)

    checks = [
        _check_orphaned_tables,
        _check_missing_fk_indexes,
        _check_circular_deps,
        _check_nullable_fks,
        _check_naming_conventions,
        _check_type_consistency,
    ]
    for check_fn in checks:
        try:
            findings = check_fn(meta, schema)
            report.findings.extend(findings)
        except Exception as exc:  # noqa: BLE001
            log.error("QA check %s failed: %s", check_fn.__name__, exc)

    log.info(
        "QA report  schema=%s  health=%d  findings=%d",
        schema, report.health_score, len(report.findings),
    )
    return report


# ── Metadata fetch ─────────────────────────────────────────────────────── #

def _fetch_metadata(cur, schema: str) -> dict:
    """Fetch all schema metadata in a single block of queries.

    Returns a dict with keys: ``tables``, ``columns``, ``fks``, ``indexes``.
    """
    # Tables
    cur.execute(
        """
        SELECT table_name
        FROM   information_schema.tables
        WHERE  table_schema = %s
          AND  table_type IN ('BASE TABLE', 'FOREIGN')
        ORDER  BY table_name
        """,
        (schema,),
    )
    tables: list[str] = [r[0] for r in cur.fetchall()]

    # Columns: (table_name, column_name, data_type, is_nullable)
    cur.execute(
        """
        SELECT c.table_name, c.column_name, c.data_type, c.is_nullable
        FROM   information_schema.columns c
        WHERE  c.table_schema = %s
        ORDER  BY c.table_name, c.ordinal_position
        """,
        (schema,),
    )
    columns: list[tuple] = cur.fetchall()

    # Foreign keys: (child_table, child_col, parent_table, parent_col, constraint_name)
    cur.execute(
        """
        SELECT
            tc.table_name      AS child_table,
            kcu.column_name    AS child_col,
            ccu.table_name     AS parent_table,
            ccu.column_name    AS parent_col,
            tc.constraint_name
        FROM  information_schema.table_constraints AS tc
        JOIN  information_schema.key_column_usage AS kcu
              ON  tc.constraint_name = kcu.constraint_name
              AND tc.table_schema    = kcu.table_schema
        JOIN  information_schema.constraint_column_usage AS ccu
              ON  ccu.constraint_name = tc.constraint_name
              AND ccu.table_schema    = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema    = %s
        ORDER BY tc.table_name, kcu.column_name
        """,
        (schema,),
    )
    fks: list[tuple] = cur.fetchall()

    # Indexes: (table_name, column_name, index_name)
    cur.execute(
        """
        SELECT
            t.relname  AS table_name,
            a.attname  AS column_name,
            i.relname  AS index_name
        FROM  pg_class t
        JOIN  pg_namespace n  ON  n.oid = t.relnamespace
        JOIN  pg_index ix     ON  ix.indrelid = t.oid
        JOIN  pg_class i      ON  i.oid = ix.indexrelid
        JOIN  pg_attribute a  ON  a.attrelid = t.oid
                              AND a.attnum   = ANY(ix.indkey)
        WHERE n.nspname = %s
          AND t.relkind = 'r'
        ORDER BY t.relname, a.attname
        """,
        (schema,),
    )
    indexes: list[tuple] = cur.fetchall()

    return {
        "tables":  tables,
        "columns": columns,
        "fks":     fks,
        "indexes": indexes,
    }


# ── Individual checks ─────────────────────────────────────────────────── #

def _check_orphaned_tables(meta: dict, schema: str) -> list[QAFinding]:
    """Tables that have no FK relationships (neither source nor destination)."""
    tables = set(meta["tables"])
    referenced: set[str] = set()
    for child_table, _cc, parent_table, _pc, _cn in meta["fks"]:
        referenced.add(child_table)
        referenced.add(parent_table)
    orphans = tables - referenced
    return [
        QAFinding(
            check="orphaned_tables",
            severity=INFO,
            table=t,
            message=(
                f'"{t}" has no foreign-key relationships (inbound or outbound). '
                f"It may be a lookup, log, or genuinely isolated entity."
            ),
        )
        for t in sorted(orphans)
    ]


def _check_missing_fk_indexes(meta: dict, schema: str) -> list[QAFinding]:
    """FK columns that lack a covering index — can cause slow JOIN scans."""
    indexed: set[tuple[str, str]] = {(r[0], r[1]) for r in meta["indexes"]}
    findings: list[QAFinding] = []
    seen: set[tuple[str, str]] = set()
    for child_table, child_col, _pt, _pc, _cn in meta["fks"]:
        key = (child_table, child_col)
        if key not in seen and key not in indexed:
            seen.add(key)
            findings.append(
                QAFinding(
                    check="missing_fk_indexes",
                    severity=WARNING,
                    table=child_table,
                    column=child_col,
                    message=(
                        f'"{child_table}"."{child_col}" is a foreign-key column with no index. '
                        f"This may cause slow JOINs or DELETE cascades."
                    ),
                    fix_sql=(
                        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS\n"
                        f'    idx_{child_table}_{child_col}\n'
                        f'    ON "{schema}"."{child_table}" ("{child_col}");'
                    ),
                )
            )
    return findings


def _check_circular_deps(meta: dict, schema: str) -> list[QAFinding]:
    """FK cycles detected using networkx."""
    try:
        import networkx as nx  # noqa: PLC0415
    except ImportError:
        log.warning("networkx not available — skipping circular dependency check")
        return []

    G: nx.DiGraph = nx.DiGraph()
    for table in meta["tables"]:
        G.add_node(table)
    for child_table, _cc, parent_table, _pc, _cn in meta["fks"]:
        if child_table != parent_table:          # skip self-referential
            G.add_edge(child_table, parent_table)

    findings: list[QAFinding] = []
    try:
        cycles = list(nx.simple_cycles(G))
    except Exception as exc:  # noqa: BLE001
        log.error("Cycle detection failed: %s", exc)
        return []

    seen_cycles: set[frozenset] = set()
    for cycle in cycles:
        key = frozenset(cycle)
        if key in seen_cycles:
            continue
        seen_cycles.add(key)
        cycle_str = " → ".join(cycle) + f" → {cycle[0]}"
        findings.append(
            QAFinding(
                check="circular_deps",
                severity=ERROR,
                message=(
                    f"Circular FK dependency detected: {cycle_str}. "
                    f"This can prevent cascading deletes and complicate migrations."
                ),
            )
        )
    return findings


def _check_nullable_fks(meta: dict, schema: str) -> list[QAFinding]:
    """FK columns that are nullable — legitimate but worth reviewing."""
    nullable_map: dict[tuple[str, str], str] = {
        (r[0], r[1]): r[3] for r in meta["columns"]
    }
    findings: list[QAFinding] = []
    seen: set[tuple[str, str]] = set()
    for child_table, child_col, parent_table, _pc, _cn in meta["fks"]:
        key = (child_table, child_col)
        if key not in seen and nullable_map.get(key, "NO") == "YES":
            seen.add(key)
            findings.append(
                QAFinding(
                    check="nullable_fks",
                    severity=INFO,
                    table=child_table,
                    column=child_col,
                    message=(
                        f'"{child_table}"."{child_col}" is a nullable FK to '
                        f'"{parent_table}". Verify this optional relationship is intentional.'
                    ),
                )
            )
    return findings


def _check_naming_conventions(meta: dict, schema: str) -> list[QAFinding]:
    """Tables and columns that don't follow snake_case (a-z, 0-9, _)."""
    findings: list[QAFinding] = []

    for t in meta["tables"]:
        if not _SNAKE_RE.match(t):
            findings.append(
                QAFinding(
                    check="naming_conventions",
                    severity=WARNING,
                    table=t,
                    message=f'Table name "{t}" does not follow snake_case convention.',
                )
            )

    seen_cols: set[tuple[str, str]] = set()
    for table, col, _dtype, _nullable in meta["columns"]:
        key = (table, col)
        if key not in seen_cols and not _SNAKE_RE.match(col):
            seen_cols.add(key)
            findings.append(
                QAFinding(
                    check="naming_conventions",
                    severity=INFO,
                    table=table,
                    column=col,
                    message=f'Column "{col}" in "{table}" does not follow snake_case convention.',
                )
            )
    return findings


def _check_type_consistency(meta: dict, schema: str) -> list[QAFinding]:
    """Same column name used with different data types across tables."""
    col_types:  dict[str, set[str]] = {}
    col_tables: dict[str, set[str]] = {}
    for table, col, dtype, _nullable in meta["columns"]:
        col_types.setdefault(col, set()).add(dtype)
        col_tables.setdefault(col, set()).add(table)

    findings: list[QAFinding] = []
    for col, types in sorted(col_types.items()):
        if len(types) > 1:
            tables_list = sorted(col_tables.get(col, set()))
            type_list   = ", ".join(sorted(types))
            findings.append(
                QAFinding(
                    check="type_consistency",
                    severity=WARNING,
                    column=col,
                    message=(
                        f'Column "{col}" appears with different types ({type_list}) '
                        f'across: {", ".join(tables_list)}.'
                    ),
                )
            )
    return findings
