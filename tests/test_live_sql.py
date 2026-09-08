"""
Smoke tests that execute Coruscant's SQL against a real PostgreSQL server.

Why this module exists
----------------------
Every other database test in this suite mocks psycopg2. A mock cursor accepts
any string, so a query can be syntactically valid Python, fully "tested", and
still be nonsense to PostgreSQL. That is not hypothetical here:

  * ``BLOAT_SQL`` selected ``tablename`` from ``pg_stat_user_tables``, which
    exposes that column as ``relname``. The Table Bloat health check had never
    once worked, and 600+ passing tests said nothing, because the only test
    covering it asserted that the *constant existed*.

These tests execute each query for real and fail if the server rejects it. They
catch wrong column names, bad casts, syntax errors and version incompatibility
— the entire class of defect that mocks are blind to.

Running them
------------
Skipped automatically when no server is configured, so local runs and any
environment without PostgreSQL are unaffected::

    CORUSCANT_TEST_DSN="postgresql://postgres:postgres@localhost:5432/postgres"

CI supplies this via a ``postgres`` service container (see
.github/workflows/release.yml).
"""
from __future__ import annotations

import os
import re

import pytest

DSN = os.environ.get("CORUSCANT_TEST_DSN", "").strip()

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="no live PostgreSQL: set CORUSCANT_TEST_DSN to enable live SQL smoke tests",
)

psycopg2 = pytest.importorskip("psycopg2")


# Queries needing an optional extension the bare server will not have. The
# application degrades gracefully when these fail, so a failure here is not a
# defect — but the SQL is still executed below to check it *parses*.
NEEDS_EXTENSION = {
    "STATEMENTS_SQL": "pg_stat_statements",
}


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(DSN, connect_timeout=15)
    c.autocommit = True
    yield c
    c.close()


@pytest.fixture(scope="module")
def seeded(conn):
    """A small schema so the queries have real relations to report on."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE SCHEMA IF NOT EXISTS smoke;
            CREATE TABLE IF NOT EXISTS smoke.parent (
                id serial PRIMARY KEY,
                name text NOT NULL
            );
            CREATE TABLE IF NOT EXISTS smoke.child (
                id serial PRIMARY KEY,
                parent_id integer REFERENCES smoke.parent(id),
                note text
            );
        """)
        cur.execute("SELECT count(*) FROM smoke.parent")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO smoke.parent (name) "
                        "SELECT 'row ' || g FROM generate_series(1, 200) g")
            cur.execute("INSERT INTO smoke.child (parent_id, note) "
                        "SELECT id, 'n' FROM smoke.parent")
        # Create dead tuples so the bloat query has something to find.
        cur.execute("UPDATE smoke.parent SET name = name")
        cur.execute("ANALYZE smoke.parent")
    return conn


def _sql_constants(module) -> dict[str, str]:
    """Every module-level ``*_SQL`` string constant."""
    return {
        name: value
        for name, value in vars(module).items()
        if name.endswith("_SQL") and isinstance(value, str) and value.strip()
    }


def _all_sql() -> list[tuple[str, str, str]]:
    """(module label, constant name, sql) for every query the app ships."""
    from coruscant.core import doctor, metrics, database

    out = []
    for label, mod in (("doctor", doctor), ("metrics", metrics), ("database", database)):
        for name, sql in sorted(_sql_constants(mod).items()):
            out.append((label, name, sql))
    return out


ALL_SQL = _all_sql()


def test_there_is_sql_to_check():
    """Guards the guard: an empty discovery would make every case below vacuous."""
    names = {n for _m, n, _s in ALL_SQL}
    assert "BLOAT_SQL" in names, f"discovery missed BLOAT_SQL; found {sorted(names)}"
    assert len(ALL_SQL) >= 15, f"expected the app's full query set, found {len(ALL_SQL)}"


@pytest.mark.parametrize(
    "module,name,sql",
    ALL_SQL,
    ids=[f"{m}.{n}" for m, n, _ in ALL_SQL],
)
def test_query_is_accepted_by_postgresql(seeded, module, name, sql):
    """
    Execute the query for real.

    This is what a mock cannot do: PostgreSQL resolves every column and
    function against its actual catalogs and rejects anything that does not
    exist.
    """
    params = tuple(["public"] * sql.count("%s"))
    with seeded.cursor() as cur:
        try:
            cur.execute(sql, params or None)
            cur.fetchall()
        except psycopg2.errors.UndefinedTable as exc:
            ext = NEEDS_EXTENSION.get(name)
            if ext and ext in str(exc):
                pytest.skip(f"{name} requires the {ext} extension")
            raise
        except psycopg2.Error as exc:
            pytest.fail(
                f"{module}.{name} was rejected by PostgreSQL "
                f"{seeded.server_version}:\n  {str(exc).strip()}"
            )


def test_bloat_query_returns_the_expected_shape(seeded):
    """
    The Doctor indexes this result positionally, so column order is part of the
    contract, not an implementation detail.
    """
    from coruscant.core.doctor import BLOAT_SQL

    with seeded.cursor() as cur:
        cur.execute(BLOAT_SQL)
        cols = [d.name for d in cur.description]
    assert cols[:2] == ["schema", "table"], (
        f"doctor.py reads schema from column 0 and table from column 1; got {cols}"
    )
    assert "dead_pct" in cols


def test_can_maintain_answers_for_a_table_we_own(seeded):
    """The ownership pre-check must approve a table the test role created."""
    from coruscant.core.database import CAN_MAINTAIN_SQL

    with seeded.cursor() as cur:
        cur.execute(CAN_MAINTAIN_SQL, ("smoke", "parent"))
        row = cur.fetchone()
    assert row is not None, "ownership check found no such table"
    assert row[0] is True, "expected the creating role to be allowed to vacuum"


def test_can_maintain_refuses_a_table_owned_by_someone_else(seeded):
    """
    The real bug, end to end: a table owned by another role must be reported as
    un-maintainable *before* a VACUUM is issued.
    """
    from coruscant.core.database import CAN_MAINTAIN_SQL

    with seeded.cursor() as cur:
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smoke_other') THEN
                    CREATE ROLE smoke_other NOLOGIN;
                END IF;
            END $$;
        """)
        cur.execute("CREATE TABLE IF NOT EXISTS smoke.foreign_owned (id int)")
        cur.execute("ALTER TABLE smoke.foreign_owned OWNER TO smoke_other")

        cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        if cur.fetchone()[0]:
            pytest.skip("connected as a superuser, which may vacuum anything")

        cur.execute(CAN_MAINTAIN_SQL, ("smoke", "foreign_owned"))
        assert cur.fetchone()[0] is False, (
            "a table owned by another role must be reported as un-maintainable"
        )


def test_vacuum_reports_refusal_against_a_real_server(seeded):
    """
    Full path through DatabaseManager: refuse where we must, succeed where we
    may. This is the assertion that would have caught the original bug.
    """
    from coruscant.core.database import DatabaseManager

    db = DatabaseManager()
    db._conn = seeded          # reuse the fixture's live connection

    with seeded.cursor() as cur:
        cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        is_super = cur.fetchone()[0]

    assert db.vacuum_table("smoke", "parent") == [], (
        "vacuuming a table we own must report no refusal"
    )

    if not is_super:
        reasons = db.vacuum_table("smoke", "foreign_owned")
        assert reasons, "vacuuming a table owned by another role must be reported"
        assert "owner" in reasons[0].lower()
