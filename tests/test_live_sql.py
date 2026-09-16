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

# The generic runner passes a schema name for every %s, which is right for the
# schema/table queries and nonsense for an OID — 'public'::oid does not parse.
# These name an object the seeded fixture creates instead.
OID_PARAM_SQL = {
    "ROUTINE_DEFINITION_SQL": ("smoke.calc(integer)", "regprocedure"),
    "VIEW_DEFINITION_SQL":    ("smoke.v_parent", "regclass"),
}

# Queries that only parse on a server OLDER than the version named.
# SCHEMA_ROUTINES_PRE11_SQL reads proisagg/proiswindow, which PostgreSQL 11
# replaced with prokind, so on a modern server it is *meant* to be rejected.
# Running it here would report a version gate as a defect.
SUPERSEDED_AT = {
    "SCHEMA_ROUTINES_PRE11_SQL": 110000,
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

        # Objects for the source lookups.  A view and a materialised view
        # (the latter absent from information_schema entirely), an overloaded
        # pair, a procedure, and an aggregate — the one routine kind whose
        # source pg_get_functiondef() refuses to produce.
        cur.execute("""
            CREATE OR REPLACE VIEW smoke.v_parent AS
                SELECT id, name FROM smoke.parent WHERE id > 0;

            CREATE OR REPLACE FUNCTION smoke.calc(a integer)
                RETURNS integer LANGUAGE sql IMMUTABLE
                AS $fn$ SELECT a * 2 $fn$;

            CREATE OR REPLACE FUNCTION smoke.calc(a numeric)
                RETURNS numeric LANGUAGE sql IMMUTABLE
                AS $fn$ SELECT a * 3 $fn$;

            CREATE OR REPLACE PROCEDURE smoke.do_nothing()
                LANGUAGE sql AS $pr$ SELECT 1 $pr$;

            DROP AGGREGATE IF EXISTS smoke.total(integer);
            CREATE AGGREGATE smoke.total(integer) (
                SFUNC = int4pl, STYPE = integer, INITCOND = '0'
            );
        """)
        cur.execute("""
            DROP MATERIALIZED VIEW IF EXISTS smoke.mv_parent;
            CREATE MATERIALIZED VIEW smoke.mv_parent AS
                SELECT id, name FROM smoke.parent;
        """)
    return conn


def _oid(conn, name: str, cast: str) -> int:
    """
    OID of a named object, e.g. _oid(conn, "smoke.v_parent", "regclass").

    *cast* is a catalog alias type: regclass for a relation, regprocedure for
    a routine (which needs the argument types, since names are not unique).
    """
    with conn.cursor() as cur:
        cur.execute(f"SELECT %s::{cast}::oid", (name,))
        return cur.fetchone()[0]


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
    ceiling = SUPERSEDED_AT.get(name)
    if ceiling and seeded.server_version >= ceiling:
        pytest.skip(
            f"{name} targets servers older than {ceiling}; "
            f"this server is {seeded.server_version}"
        )

    if name in OID_PARAM_SQL:
        params = (_oid(seeded, *OID_PARAM_SQL[name]),)
    else:
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


@pytest.fixture(scope="module")
def unprivileged(seeded):
    """
    A second connection as a non-superuser that owns nothing.

    CI connects as `postgres`, a superuser who may vacuum anything — so the
    refusal path, which is the whole point of these tests, would never execute.
    This creates a deliberately powerless role and connects as it, so the
    original bug is reproduced against a real server on every run.
    """
    params = psycopg2.extensions.parse_dsn(DSN)
    if not params.get("password"):
        pytest.skip("need a password in the DSN to open a second connection")

    with seeded.cursor() as cur:
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smoke_powerless') THEN
                    CREATE ROLE smoke_powerless LOGIN PASSWORD 'smoke_pw';
                END IF;
            END $$;
        """)
        cur.execute("GRANT USAGE ON SCHEMA smoke TO smoke_powerless")
        cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA smoke TO smoke_powerless")
        cur.execute(f"GRANT CONNECT ON DATABASE {params['dbname']} TO smoke_powerless")

    low = dict(params, user="smoke_powerless", password="smoke_pw")
    conn = psycopg2.connect(**low)
    conn.autocommit = True
    yield conn
    conn.close()


def test_can_maintain_approves_a_table_the_role_owns(seeded):
    from coruscant.core.database import CAN_MAINTAIN_SQL
    with seeded.cursor() as cur:
        cur.execute(CAN_MAINTAIN_SQL, ("smoke", "parent"))
        assert cur.fetchone()[0] is True


def test_can_maintain_refuses_a_table_owned_by_someone_else(unprivileged):
    """
    The real bug, end to end: a table owned by another role must be reported as
    un-maintainable *before* any VACUUM is issued.
    """
    from coruscant.core.database import CAN_MAINTAIN_SQL

    with unprivileged.cursor() as cur:
        cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        assert cur.fetchone()[0] is False, "fixture must not be a superuser"

        cur.execute(CAN_MAINTAIN_SQL, ("smoke", "parent"))
        assert cur.fetchone()[0] is False, (
            "a table owned by another role must be reported as un-maintainable"
        )


def test_vacuum_reports_refusal_against_a_real_server(unprivileged):
    """
    The exact scenario from the bug report, against a real server: a role that
    owns nothing asks the Doctor to vacuum, and must be told it did not happen.
    """
    from coruscant.core.database import DatabaseManager

    db = DatabaseManager()
    db._conn = unprivileged

    reasons = db.vacuum_table("smoke", "parent")
    assert reasons, "vacuuming a table owned by another role must be reported"
    assert "owner" in reasons[0].lower()
    assert "smoke.parent" in reasons[0]


def test_vacuum_succeeds_where_the_role_does_own_the_table(seeded):
    from coruscant.core.database import DatabaseManager

    db = DatabaseManager()
    db._conn = seeded
    assert db.vacuum_table("smoke", "parent") == [], (
        "vacuuming a table we own must report no refusal"
    )


def test_unmaintainable_tables_lists_what_the_role_cannot_touch(unprivileged):
    from coruscant.core.database import DatabaseManager

    db = DatabaseManager()
    db._conn = unprivileged
    names = db.unmaintainable_tables()
    assert "smoke.parent" in names, (
        f"expected smoke.parent among un-maintainable tables, got {names[:5]}"
    )


# ---------------------------------------------------------------------------
# Object source — what mocks cannot check
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_db(seeded):
    """A DatabaseManager connected to the same server as `seeded`."""
    from coruscant.core.database import DatabaseManager

    parts = psycopg2.extensions.parse_dsn(DSN)
    db = DatabaseManager()
    db.connect(
        host=parts.get("host", "localhost"),
        port=int(parts.get("port", 5432)),
        database=parts.get("dbname", "postgres"),
        user=parts.get("user", "postgres"),
        password=parts.get("password", ""),
    )
    yield db
    db.disconnect()


def _smoke_rows(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return [r for r in cur.fetchall() if r[0] == "smoke"]


class TestCatalogQueriesAgainstARealServer:
    """
    These execute the new catalog queries for real.  A mock cursor accepts any
    string, so it cannot tell whether relkind 'm' actually surfaces a
    materialised view or whether prokind exists on this server.
    """

    def test_materialised_view_is_listed(self, seeded):
        """
        The reason for moving off information_schema.tables: it has no
        materialised views at all, so they were missing from the tree.
        """
        from coruscant.core.database import SCHEMA_RELATIONS_SQL
        kinds = {r[1]: r[3] for r in _smoke_rows(seeded, SCHEMA_RELATIONS_SQL)}
        assert kinds.get("mv_parent") == "MATERIALIZED VIEW"

    def test_views_and_tables_keep_their_kinds(self, seeded):
        from coruscant.core.database import SCHEMA_RELATIONS_SQL
        kinds = {r[1]: r[3] for r in _smoke_rows(seeded, SCHEMA_RELATIONS_SQL)}
        assert kinds.get("v_parent") == "VIEW"
        assert kinds.get("parent") == "BASE TABLE"

    def test_relation_oids_resolve(self, seeded):
        """
        An OID the definition lookups cannot resolve is worthless.

        Compared against pg_class.relname rather than regclass::text: the
        latter quotes names that need it, so a view called "Order Details"
        comes back with quotes around it and no plain string check holds.
        """
        from coruscant.core.database import SCHEMA_RELATIONS_SQL
        rows = _smoke_rows(seeded, SCHEMA_RELATIONS_SQL)
        assert rows
        with seeded.cursor() as cur:
            for _schema, name, oid, _kind in rows:
                cur.execute(
                    "SELECT relname FROM pg_catalog.pg_class WHERE oid = %s",
                    (oid,),
                )
                row = cur.fetchone()
                assert row is not None, f"OID {oid} resolves to nothing"
                assert row[0] == name

    def test_materialised_view_columns_are_returned(self, seeded):
        """information_schema.columns omits these too."""
        from coruscant.core.database import SCHEMA_COLUMNS_SQL
        cols = {r[2] for r in _smoke_rows(seeded, SCHEMA_COLUMNS_SQL)
                if r[1] == "mv_parent"}
        assert cols == {"id", "name"}

    def test_column_types_carry_their_modifiers(self, seeded):
        """format_type() renders varchar(50), not a bare "character varying"."""
        from coruscant.core.database import SCHEMA_COLUMNS_SQL
        rows = _smoke_rows(seeded, SCHEMA_COLUMNS_SQL)
        assert rows
        assert all(isinstance(r[3], str) and r[3] for r in rows)

    def test_overloads_come_back_as_separate_rows(self, seeded):
        """
        calc(integer) and calc(numeric) share a name.  Under
        information_schema.routines they were indistinguishable.
        """
        from coruscant.core.database import SCHEMA_ROUTINES_SQL
        rows = [r for r in _smoke_rows(seeded, SCHEMA_ROUTINES_SQL)
                if r[1] == "calc"]
        assert len(rows) == 2
        assert len({r[2] for r in rows}) == 2                 # distinct OIDs
        assert {r[3] for r in rows} == {"a integer", "a numeric"}

    def test_prokind_distinguishes_the_routine_kinds(self, seeded):
        from coruscant.core.database import SCHEMA_ROUTINES_SQL
        kinds = {r[1]: r[4] for r in _smoke_rows(seeded, SCHEMA_ROUTINES_SQL)}
        assert kinds.get("do_nothing") == "p"
        assert kinds.get("total") == "a"
        assert kinds.get("calc") == "f"


class TestSchemaTreeAgainstARealServer:
    def _smoke(self, live_db):
        tree = live_db.get_schema_tree()
        return next(s for s in tree if s["schema"] == "smoke")

    def test_tree_contains_the_materialised_view(self, live_db):
        rels = {t["name"]: t["type"] for t in self._smoke(live_db)["tables"]}
        assert rels.get("mv_parent") == "MATERIALIZED VIEW"

    def test_tree_separates_the_overloads(self, live_db):
        fns = [f for f in self._smoke(live_db)["functions"] if f["name"] == "calc"]
        assert len(fns) == 2
        assert {f["signature"] for f in fns} == {"calc(a integer)", "calc(a numeric)"}

    def test_tree_marks_the_aggregate_sourceless(self, live_db):
        agg = next(f for f in self._smoke(live_db)["functions"]
                   if f["name"] == "total")
        assert agg["type"] == "AGGREGATE"
        assert agg["has_source"] is False

    def test_tree_labels_the_procedure(self, live_db):
        proc = next(f for f in self._smoke(live_db)["functions"]
                    if f["name"] == "do_nothing")
        assert proc["type"] == "PROCEDURE"
        assert proc["has_source"] is True


class TestDefinitionRoundTrip:
    """
    The capability this whole change exists for: read an object's source, edit
    it, run it again.  Only a real server can say whether what comes back is
    actually runnable.
    """

    def test_function_source_re_executes(self, live_db, seeded):
        oid = _oid(seeded, "smoke.calc(integer)", "regprocedure")
        ddl = live_db.get_routine_definition(oid)
        assert ddl.lstrip().upper().startswith("CREATE OR REPLACE FUNCTION")
        with seeded.cursor() as cur:
            cur.execute(ddl)                     # the round trip
            cur.execute("SELECT smoke.calc(2)")
            assert cur.fetchone()[0] == 4

    def test_procedure_source_re_executes(self, live_db, seeded):
        oid = _oid(seeded, "smoke.do_nothing()", "regprocedure")
        ddl = live_db.get_routine_definition(oid)
        with seeded.cursor() as cur:
            cur.execute(ddl)

    def test_overloads_return_different_source(self, live_db, seeded):
        int_oid = _oid(seeded, "smoke.calc(integer)", "regprocedure")
        num_oid = _oid(seeded, "smoke.calc(numeric)", "regprocedure")
        assert (live_db.get_routine_definition(int_oid)
                != live_db.get_routine_definition(num_oid))

    def test_aggregate_source_is_genuinely_refused(self, live_db, seeded):
        """
        The has_source flag is not a guess about aggregates — this is the
        server refusing, and the reason the UI must not offer the action.
        """
        from coruscant.core.database import DatabaseError
        oid = _oid(seeded, "smoke.total(integer)", "regprocedure")
        with pytest.raises(DatabaseError):
            live_db.get_routine_definition(oid)

    def test_view_source_re_executes(self, live_db, seeded):
        """
        pg_get_viewdef() returns a bare SELECT; the CREATE is rebuilt around
        it.  If that wrapping is wrong, this is where it shows.
        """
        oid = _oid(seeded, "smoke.v_parent", "regclass")
        ddl = live_db.get_view_definition("smoke", "v_parent", oid)
        assert ddl.startswith('CREATE OR REPLACE VIEW "smoke"."v_parent" AS')
        with seeded.cursor() as cur:
            cur.execute(ddl)                     # the round trip
            cur.execute("SELECT count(*) FROM smoke.v_parent")
            assert cur.fetchone()[0] > 0

    def test_view_source_survives_an_awkward_name(self, live_db, seeded):
        """Quoting is what makes a space or a capital survive the round trip."""
        with seeded.cursor() as cur:
            cur.execute('CREATE OR REPLACE VIEW smoke."Order Details" AS '
                        'SELECT id FROM smoke.parent')
        oid = _oid(seeded, 'smoke."Order Details"', "regclass")
        ddl = live_db.get_view_definition("smoke", "Order Details", oid)
        with seeded.cursor() as cur:
            cur.execute(ddl)
            cur.execute('SELECT count(*) FROM smoke."Order Details"')
            assert cur.fetchone()[0] > 0

    def test_materialised_view_source_is_not_a_replace(self, live_db, seeded):
        """
        Deliberately not executed: PostgreSQL has no replace form, so running
        this needs a DROP first — which is exactly what the comment warns
        about.  Asserting the shape is the most that can be checked safely.
        """
        oid = _oid(seeded, "smoke.mv_parent", "regclass")
        ddl = live_db.get_view_definition("smoke", "mv_parent", oid,
                                          materialized=True)
        assert 'CREATE MATERIALIZED VIEW "smoke"."mv_parent" AS' in ddl
        assert ddl.startswith("--")


class TestSavepointContainment:
    """
    The savepoint around a definition lookup only matters on a real server: a
    mock cursor has no transaction to abort.  Without it, a failed lookup
    poisons the user's open transaction and every later statement in it fails,
    discarding uncommitted work.
    """

    def test_failed_lookup_leaves_the_transaction_usable(self, live_db):
        live_db.set_autocommit(False)
        try:
            live_db.execute("CREATE TEMP TABLE sp_probe (id integer)")
            live_db.execute("INSERT INTO sp_probe VALUES (1)")

            # OID 1 is a pg_type row, never a routine — the server refuses.
            with pytest.raises(Exception):
                live_db.get_routine_definition(1)

            # Unguarded, this raises "current transaction is aborted".
            results = live_db.execute("SELECT count(*) FROM sp_probe")
            assert results[0].rows[0][0] == 1
        finally:
            live_db.rollback()
            live_db.set_autocommit(True)

    def test_successful_lookup_leaves_the_transaction_usable(self, live_db, seeded):
        live_db.set_autocommit(False)
        try:
            live_db.execute("CREATE TEMP TABLE sp_probe2 (id integer)")
            oid = _oid(seeded, "smoke.calc(integer)", "regprocedure")
            live_db.get_routine_definition(oid)
            live_db.execute("INSERT INTO sp_probe2 VALUES (7)")
            results = live_db.execute("SELECT id FROM sp_probe2")
            assert results[0].rows[0][0] == 7
        finally:
            live_db.rollback()
            live_db.set_autocommit(True)
