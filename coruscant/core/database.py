"""
coruscant.core.database
~~~~~~~~~~~~~~~~~~~~~~~
PostgreSQL connection management and query execution.

No GUI imports.  This module is the application's single point of contact
with the database driver.

Logging
-------
INFO  : connect (host/port/db/user/ssl — password never logged), disconnect,
        successful execution summary (statement count).
DEBUG : per-statement SQL preview (first 120 chars), row count, elapsed ms,
        command results with rows_affected.
WARNING : truncated result sets.
ERROR : connection failures and query errors (first line of the pg message).

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import logging
import time

import psycopg2
import psycopg2.extras
import psycopg2.extensions

from coruscant.core.sql import split_statements

log = logging.getLogger(__name__)

# SQLSTATE 57014 — sent by PostgreSQL when pg_cancel_backend() fires.
PGCODE_QUERY_CANCELED = "57014"

#: The driver's error type, re-exported.
#:
#: This module is the application's single point of contact with psycopg2,
#: so callers that need to catch a database error import it from here rather
#: than importing the driver themselves. Swapping drivers then touches this
#: module alone.
DatabaseError = psycopg2.Error

# Can the current role actually maintain this table?
#
# PostgreSQL refuses maintenance on a table you do not own by emitting a
# WARNING and reporting overall success, so the outcome has to be established
# some other way.  Reading the warning text does not work: those messages are
# translated according to the server's lc_messages, so matching on English
# words silently stops detecting skips on a non-English server — and fails
# open, back to reporting success for work that never happened.
#
# This asks the catalog instead, which is locale-independent:
#   pg_has_role(..., 'USAGE')  covers direct ownership and membership of the
#                              owning role
#   rolsuper                   superusers may vacuum anything
#   pg_maintain                PostgreSQL 16+ grants maintenance without
#                              ownership; absent on older servers, hence the
#                              to_regrole guard
CAN_MAINTAIN_SQL = """
SELECT pg_catalog.pg_has_role(current_user, c.relowner, 'USAGE')
    OR EXISTS (SELECT 1 FROM pg_catalog.pg_roles
                WHERE rolname = current_user AND rolsuper)
    OR (pg_catalog.to_regrole('pg_maintain') IS NOT NULL
        AND pg_catalog.pg_has_role(current_user,
                                   pg_catalog.to_regrole('pg_maintain'),
                                   'USAGE'))
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relname = %s
"""


# ── Schema-tree catalog queries ──────────────────────────────────────────
#
# These read pg_catalog rather than information_schema, for three reasons:
#
#   * information_schema.tables omits materialised views — they are not in
#     the SQL standard — so they were missing from the tree entirely.
#   * information_schema.routines identifies a routine by name, and a name is
#     not unique: PostgreSQL allows overloading.  calc(int) and calc(numeric)
#     arrived as two rows nothing could tell apart, let alone fetch the source
#     of.  pg_proc carries the OID, the one stable handle for that.
#   * The OID is also what the definition lookups below are keyed on.
#
# has_table_privilege() preserves the visibility rule information_schema
# applied for free: a relation the current role holds no privilege on stays
# out of the tree.  None of these queries take parameters, so a literal % in
# a pattern would be safe here — there is none, but keep it that way.

SCHEMA_RELATIONS_SQL = """
SELECT n.nspname,
       c.relname,
       c.oid,
       CASE c.relkind
           WHEN 'r' THEN 'BASE TABLE'
           WHEN 'p' THEN 'BASE TABLE'
           WHEN 'v' THEN 'VIEW'
           WHEN 'm' THEN 'MATERIALIZED VIEW'
           WHEN 'f' THEN 'FOREIGN'
       END AS relation_type
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND pg_catalog.has_table_privilege(
          c.oid, 'SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER')
ORDER BY n.nspname, relation_type, c.relname
"""

# format_type() renders the declared type the way the server would print it,
# so a varchar(50) reads as varchar(50) rather than information_schema's bare
# "character varying".  attnum > 0 skips system columns; attisdropped skips
# the tombstones a dropped column leaves behind.
SCHEMA_COLUMNS_SQL = """
SELECT n.nspname,
       c.relname,
       a.attname,
       pg_catalog.format_type(a.atttypid, a.atttypmod),
       a.attnum
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c     ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND a.attnum > 0
  AND NOT a.attisdropped
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND pg_catalog.has_table_privilege(
          c.oid, 'SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER')
ORDER BY n.nspname, c.relname, a.attnum
"""

# pg_proc.prokind arrived in PostgreSQL 11, replacing the proisagg and
# proiswindow booleans.  Referencing a column the server does not have is a
# parse error, not an empty result, so the pre-11 variant is a separate
# statement chosen by server version rather than one clever portable query.
SCHEMA_ROUTINES_SQL = """
SELECT n.nspname,
       p.proname,
       p.oid,
       pg_catalog.pg_get_function_identity_arguments(p.oid),
       p.prokind,
       pg_catalog.pg_get_function_result(p.oid)
FROM pg_catalog.pg_proc p
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n.nspname, p.proname
"""

SCHEMA_ROUTINES_PRE11_SQL = """
SELECT n.nspname,
       p.proname,
       p.oid,
       pg_catalog.pg_get_function_identity_arguments(p.oid),
       CASE WHEN p.proisagg    THEN 'a'
            WHEN p.proiswindow THEN 'w'
            ELSE 'f'
       END,
       pg_catalog.pg_get_function_result(p.oid)
FROM pg_catalog.pg_proc p
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n.nspname, p.proname
"""

#: Server version at which pg_proc.prokind replaced proisagg/proiswindow.
PROKIND_MIN_SERVER_VERSION = 110000

#: pg_proc.prokind → the label shown in the tree.
PROKIND_LABELS = {
    "f": "FUNCTION",
    "p": "PROCEDURE",
    "a": "AGGREGATE",
    "w": "WINDOW",
}

#: prokind values pg_get_functiondef() refuses.  Asking for an aggregate's
#: definition raises "is an aggregate function" rather than returning text,
#: so the tree marks these unavailable instead of surfacing a driver error.
PROKIND_WITHOUT_SOURCE = frozenset({"a"})

# pg_get_functiondef() returns a complete CREATE OR REPLACE statement, ready
# to run.  pg_get_viewdef() does not: it returns the SELECT body alone, which
# get_view_definition() wraps.
ROUTINE_DEFINITION_SQL = "SELECT pg_catalog.pg_get_functiondef(%s::oid)"

VIEW_DEFINITION_SQL = "SELECT pg_catalog.pg_get_viewdef(%s::oid, true)"


def quote_ident(name: str) -> str:
    """
    Double-quote an identifier so it survives a round trip.

    A view called "Order Details", or one holding a quote of its own, has
    to come back as something the server will parse when the edited
    definition is run again.
    """
    return '"' + name.replace('"', '""') + '"'


class QueryResult:
    """Value object returned for each executed statement."""

    __slots__ = ("label", "columns", "rows", "elapsed_ms", "truncated")

    def __init__(
        self,
        label: str,
        columns: list[str],
        rows: list[tuple],
        elapsed_ms: float,
        truncated: bool = False,
    ) -> None:
        self.label      = label
        self.columns    = columns
        self.rows       = rows
        self.elapsed_ms = elapsed_ms
        self.truncated  = truncated


class CommandResult:
    """Value object returned for non-SELECT statements (DML / DDL)."""

    __slots__ = ("label", "message", "elapsed_ms")

    def __init__(self, label: str, message: str, elapsed_ms: float) -> None:
        self.label      = label
        self.message    = message
        self.elapsed_ms = elapsed_ms


# Union type for a single statement's outcome
StatementResult = QueryResult | CommandResult


class DatabaseManager:
    """
    Wraps a single psycopg2 connection.

    Public interface
    ----------------
    connect()        – open a connection
    disconnect()     – close it
    cancel()         – interrupt a running query (thread-safe)
    execute()        – run SQL and return a list of StatementResult
    set_autocommit() – toggle auto-commit on/off
    commit()         – explicit COMMIT
    rollback()       – explicit ROLLBACK
    is_connected     – property: True when the connection is open
    """

    def __init__(self) -> None:
        self._conn: psycopg2.extensions.connection | None = None
        self._last_params: dict | None = None
        self._last_query_time: float = 0.0

    # ------------------------------------------------------------------ #
    #  Connection lifecycle                                                #
    # ------------------------------------------------------------------ #

    def connect(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        ssl_mode: str = "prefer",
        timeout: int = 10,
    ) -> None:
        """Open a connection.  Raises psycopg2.OperationalError on failure.

        `timeout` is the libpq connect timeout in seconds; callers probing a
        connection interactively pass something shorter than the default.
        """
        if self._conn and not self._conn.closed:
            self._conn.close()

        log.info("Connecting  host=%s  port=%s  db=%s  user=%s  ssl=%s",
                 host, port, database, user, ssl_mode)
        try:
            self._conn = psycopg2.connect(
                host=host,
                port=int(port),
                dbname=database,
                user=user,
                password=password,
                connect_timeout=int(timeout),
                sslmode=ssl_mode,
            )
            self._conn.autocommit = True
            # Store successful connection parameters for auto-reconnect
            self._last_params = {
                "host": host,
                "port": port,
                "database": database,
                "user": user,
                "password": password,
                "ssl_mode": ssl_mode,
            }
        except psycopg2.OperationalError:
            log.exception("Connection failed  host=%s  port=%s  db=%s", host, port, database)
            raise
        log.info("Connected  host=%s  port=%s  db=%s", host, port, database)

    def disconnect(self) -> None:
        """Close the connection if open."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            log.info("Disconnected")
        self._conn = None

    def cancel(self) -> None:
        """
        Ask the server to interrupt the currently running query.
        Safe to call from any thread.  No-op when not connected.
        """
        if self._conn and not self._conn.closed:
            try:
                self._conn.cancel()
            except Exception:
                pass  # Already finished or connection lost — ignore

    @property
    def is_connected(self) -> bool:
        """True when a connection exists and is not closed or broken."""
        return self._conn is not None and self._conn.closed == 0

    @property
    def has_last_params(self) -> bool:
        """True if we have parameters to attempt an auto-reconnect."""
        return self._last_params is not None

    def _ensure_connected(self) -> None:
        """
        Internal helper to check connection and attempt auto-reconnect if possible.
        Raises RuntimeError if not connected and no parameters are available.
        """
        # If we have a connection, check if it's actually alive (zombie detection).
        # We perform a lightweight ping to detect server-side closure (e.g. idle timeout).
        if self._conn is not None and self._conn.closed == 0:
            if time.monotonic() - self._last_query_time >= 30.0:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute("SELECT 1")
                except (psycopg2.OperationalError, psycopg2.InterfaceError):
                    log.info("Existing connection found to be dead (zombie); resetting.")
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                    self._conn = None

        if self.is_connected:
            return

        if self._last_params:
            log.info("Connection lost or idle; attempting auto-reconnect.")
            try:
                self.connect(**self._last_params)
            except Exception as exc:
                log.error("Auto-reconnect failed: %s", exc)
                raise
        else:
            raise RuntimeError("Not connected to any database.")

    # ------------------------------------------------------------------ #
    #  Transaction control                                                 #
    # ------------------------------------------------------------------ #

    def set_autocommit(self, enabled: bool) -> None:
        """
        Toggle the connection's autocommit flag.

        When *enabled* is False the caller is responsible for calling
        commit() or rollback() to close each transaction.

        Raises RuntimeError when not connected.
        """
        self._ensure_connected()
        self._conn.autocommit = enabled  # type: ignore[union-attr]

    @property
    def server_version(self) -> int:
        """
        The server version as an integer — 160002 for PostgreSQL 16.2.

        Returns 0 when not connected, or when the driver reports nothing, so
        callers must read 0 as "unknown" rather than "ancient".
        """
        if not self.is_connected:
            return 0
        try:
            return int(self._conn.server_version)  # type: ignore[union-attr]
        except (AttributeError, TypeError, ValueError):
            return 0

    @property
    def in_transaction(self) -> bool:
        """True when autocommit is off and a transaction is open."""
        if not self.is_connected:
            return False
        return (
            not self._conn.autocommit  # type: ignore[union-attr]
            and self._conn.status  # type: ignore[union-attr]
            == psycopg2.extensions.STATUS_IN_TRANSACTION
        )

    def commit(self) -> None:
        """Commit the current transaction.  Raises RuntimeError if not connected."""
        self._ensure_connected()
        self._conn.commit()  # type: ignore[union-attr]

    def rollback(self) -> None:
        """Roll back the current transaction.  Raises RuntimeError if not connected."""
        self._ensure_connected()
        self._conn.rollback()  # type: ignore[union-attr]

    # ------------------------------------------------------------------ #
    #  Query execution                                                     #
    # ------------------------------------------------------------------ #

    def execute(
        self,
        sql: str,
        row_limit: int = 0,
        params: dict | None = None,
    ) -> list[StatementResult]:
        """
        Split *sql* into statements and execute each one sequentially.

        Parameters
        ----------
        sql       : Full SQL text to execute.
        row_limit : Max rows to fetch per SELECT (0 = unlimited).
        params    : Optional ``%(name)s`` substitution dict.

        Returns
        -------
        A list of StatementResult objects (QueryResult or CommandResult).

        Raises
        ------
        RuntimeError    – not connected
        ValueError      – blank SQL
        psycopg2.Error  – database error; has a ``.statement`` attribute
                          with the offending SQL attached.
        """
        self._ensure_connected()

        stmts = split_statements(sql)
        if not stmts:
            raise ValueError("No SQL statements found.")

        log.debug("Executing %d statement(s)  row_limit=%s", len(stmts), row_limit or "unlimited")
        results: list[StatementResult] = []

        try:
            with self._conn.cursor() as cur:  # type: ignore[union-attr]
                for idx, stmt in enumerate(stmts, start=1):
                    label   = f"Query {idx}"
                    preview = stmt.strip().replace("\n", " ")[:120]
                    log.debug("[%d/%d] %s", idx, len(stmts), preview)
                    t_start = time.perf_counter()

                    try:
                        if params:
                            substituted = cur.mogrify(stmt, params).decode(
                                self._conn.encoding or "utf-8"  # type: ignore[union-attr]
                            )
                            cur.execute(substituted)
                        else:
                            cur.execute(stmt)
                    except psycopg2.Error as exc:
                        exc.statement = stmt  # type: ignore[attr-defined]
                        raise

                    elapsed_ms = (time.perf_counter() - t_start) * 1000.0

                    if cur.description:
                        columns   = [d.name for d in cur.description]
                        truncated = False

                        if row_limit > 0:
                            rows  = cur.fetchmany(row_limit)
                            extra = cur.fetchone()
                            if extra is not None:
                                truncated = True
                                cur.fetchall()   # drain cursor
                        else:
                            rows = cur.fetchall()

                        if truncated:
                            log.warning("[%d/%d] Result truncated at %d rows  (%.1f ms)",
                                        idx, len(stmts), len(rows), elapsed_ms)
                        else:
                            log.debug("[%d/%d] %d row(s) returned  (%.1f ms)",
                                      idx, len(stmts), len(rows), elapsed_ms)

                        results.append(
                            QueryResult(label, columns, rows, elapsed_ms, truncated)
                        )
                    else:
                        affected = cur.rowcount if cur.rowcount >= 0 else "N/A"
                        log.debug("[%d/%d] Command OK  rows_affected=%s  (%.1f ms)",
                                  idx, len(stmts), affected, elapsed_ms)
                        results.append(
                            CommandResult(
                                label,
                                f"Statement executed successfully.\nRows affected: {affected}",
                                elapsed_ms,
                            )
                        )

        except psycopg2.Error as exc:
            log.error("Query failed: %s", str(exc).strip().splitlines()[0])
            # If the error closed the connection, null it so is_connected → False
            if self._conn and self._conn.closed:
                self._conn = None
            raise

        log.info("Executed %d statement(s) successfully", len(results))
        self._last_query_time = time.monotonic()
        return results

    # ------------------------------------------------------------------ #
    #  Database Doctor repairs                                             #
    # ------------------------------------------------------------------ #

    def kill_connection(self, pid: int) -> bool:
        """
        Terminate a backend by PID via pg_terminate_backend().
        Returns True if the signal was delivered, False if the process
        had already finished.  Raises RuntimeError if not connected.
        """
        self._ensure_connected()
        with self._conn.cursor() as cur:  # type: ignore[union-attr]
            cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
            result = cur.fetchone()
            ok = bool(result[0]) if result else False
        log.info("kill_connection pid=%s  result=%s", pid, ok)
        return ok

    def vacuum_table(
        self,
        schema: str,
        table: str,
        full: bool = False,
        analyze: bool = True,
    ) -> list[str]:
        """
        VACUUM (optionally FULL + ANALYZE) a single table.

        VACUUM cannot run inside a transaction, so this method temporarily
        switches the connection to autocommit mode regardless of the current
        setting and restores it afterward.

        Returns a list of reasons the table was *not* vacuumed — empty means
        the work was done.  PostgreSQL does not raise an error when you VACUUM
        a table you do not own; it warns and reports success, so ownership is
        checked against the catalog first (see CAN_MAINTAIN_SQL) rather than
        inferred from the warning text, which is translated per lc_messages.

        `full=True` issues VACUUM FULL, which takes an ACCESS EXCLUSIVE lock
        and rewrites the table — callers must warn the user before using it.

        Raises RuntimeError if not connected, psycopg2.Error on failure.
        """
        self._ensure_connected()

        if not self.can_maintain(schema, table):
            reason = (f'{schema}.{table}: not the owner — only the table or '
                      f'database owner can vacuum a table')
            log.warning("VACUUM skipped  %s", reason)
            return [reason]

        old_ac = self._conn.autocommit  # type: ignore[union-attr]
        self._conn.autocommit = True    # type: ignore[union-attr]
        try:
            qual = f'"{schema}"."{table}"'
            opts: list[str] = []
            if full:
                opts.append("FULL")
            if analyze:
                opts.append("ANALYZE")
            cmd = f"VACUUM ({', '.join(opts)}) {qual}" if opts else f"VACUUM {qual}"
            with self._conn.cursor() as cur:  # type: ignore[union-attr]
                cur.execute(cmd)
            log.info("VACUUM complete  schema=%s  table=%s  full=%s  analyze=%s",
                     schema, table, full, analyze)
            return []
        finally:
            self._conn.autocommit = old_ac  # type: ignore[union-attr]

    def can_maintain(self, schema: str, table: str) -> bool:
        """
        True when the current role may VACUUM/ANALYZE this table.

        Locale-independent: asks the catalog rather than reading a translated
        warning.  Unknown tables return True so the caller still issues the
        statement and gets PostgreSQL's own error rather than a made-up one.
        """
        self._ensure_connected()
        with self._conn.cursor() as cur:  # type: ignore[union-attr]
            cur.execute(CAN_MAINTAIN_SQL, (schema, table))
            row = cur.fetchone()
        return True if row is None else bool(row[0])

    def terminate_connections(
        self,
        state: str = "idle",
        min_idle_mins: int = 0,
    ) -> int:
        """
        Terminate backends matching *state* (e.g. 'idle', 'idle in transaction').
        If *min_idle_mins* > 0, only terminate connections idle for at least
        that many minutes.  Never touches the current session.

        Returns the number of backends actually terminated.
        Raises RuntimeError if not connected.
        """
        self._ensure_connected()
        conditions = ["pid != pg_backend_pid()", "state = %s"]
        params: list = [state]
        if min_idle_mins > 0:
            conditions.append(
                f"state_change < now() - interval '{int(min_idle_mins)} minutes'"
            )
        where = " AND ".join(conditions)
        with self._conn.cursor() as cur:  # type: ignore[union-attr]
            cur.execute(
                f"SELECT count(pg_terminate_backend(pid)) "
                f"FROM pg_stat_activity WHERE {where}",
                params,
            )
            result = cur.fetchone()
            n = int(result[0]) if result else 0
        log.info("terminate_connections state=%r  min_idle_mins=%s  terminated=%s",
                 state, min_idle_mins, n)
        return n

    def vacuum_freeze(self) -> list[str]:
        """
        Issue VACUUM FREEZE on all tables in the current database.

        This is the standard remedy for approaching XID wraparound.
        Runs with autocommit=True (required for VACUUM).
        Can be slow on large databases; run off the UI thread.

        Returns the names of tables the current role may not maintain, which a
        database-wide VACUUM silently passes over.  Empty means every table was
        processed.  Determined from the catalog before running, for the same
        locale reason described on vacuum_table().

        Raises RuntimeError if not connected, psycopg2.Error on failure.
        """
        self._ensure_connected()
        unowned = self.unmaintainable_tables()

        old_ac = self._conn.autocommit  # type: ignore[union-attr]
        self._conn.autocommit = True    # type: ignore[union-attr]
        try:
            with self._conn.cursor() as cur:  # type: ignore[union-attr]
                cur.execute("VACUUM FREEZE")
            if unowned:
                log.warning("VACUUM FREEZE skipped %d table(s) not owned by the "
                            "current role", len(unowned))
            else:
                log.info("VACUUM FREEZE complete")
            return unowned
        finally:
            self._conn.autocommit = old_ac  # type: ignore[union-attr]

    def unmaintainable_tables(self) -> list[str]:
        """
        Return "schema.table" for every user table this role may not vacuum.

        Used to report honestly on database-wide VACUUM, which skips such
        tables with a warning and still reports success.
        """
        self._ensure_connected()
        sql = """
            SELECT n.nspname || '.' || c.relname
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'm', 'p')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg_toast%'
              AND NOT (
                    pg_catalog.pg_has_role(current_user, c.relowner, 'USAGE')
                 OR EXISTS (SELECT 1 FROM pg_catalog.pg_roles
                             WHERE rolname = current_user AND rolsuper)
                 OR (pg_catalog.to_regrole('pg_maintain') IS NOT NULL
                     AND pg_catalog.pg_has_role(current_user,
                                                pg_catalog.to_regrole('pg_maintain'),
                                                'USAGE'))
              )
            ORDER BY 1
        """
        with self._conn.cursor() as cur:  # type: ignore[union-attr]
            cur.execute(sql)
            return [r[0] for r in cur.fetchall()]

    # ------------------------------------------------------------------ #
    #  Recovery mode                                                       #
    # ------------------------------------------------------------------ #

    def check_recovery_status(self) -> dict:
        """
        Return a snapshot of the server's recovery/standby state.

        Keys returned
        -------------
        is_in_recovery          : bool
        last_wal_receive_lsn    : str | None
        last_wal_replay_lsn     : str | None
        last_xact_replay_ts     : str | None   (UTC timestamp)
        replication_delay_secs  : int | None
        server_start_time       : str
        pg_version              : str
        wal_replay_paused       : bool | None  (None on primary)

        Raises RuntimeError when not connected.
        """
        self._ensure_connected()
        with self._conn.cursor() as cur:  # type: ignore[union-attr]
            cur.execute("""
                SELECT
                    pg_is_in_recovery()                                              AS is_in_recovery,
                    pg_last_wal_receive_lsn()::text                                  AS last_wal_receive_lsn,
                    pg_last_wal_replay_lsn()::text                                   AS last_wal_replay_lsn,
                    pg_last_xact_replay_timestamp()::text                            AS last_xact_replay_ts,
                    EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))::int
                                                                                     AS replication_delay_secs,
                    pg_postmaster_start_time()::text                                 AS server_start_time,
                    version()                                                         AS pg_version,
                    CASE WHEN pg_is_in_recovery()
                         THEN pg_is_wal_replay_paused()
                         ELSE NULL
                    END                                                              AS wal_replay_paused
            """)
            row = cur.fetchone()
            if row is None:
                return {"is_in_recovery": False, "wal_replay_paused": None}
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))

    def promote_standby(self) -> str:
        """
        Promote a standby server to primary.

        Tries ``pg_promote()`` (PostgreSQL 12+) first; falls back to
        ``pg_wal_replay_resume()`` on older versions.

        Returns a human-readable status string.
        Raises psycopg2.Error or RuntimeError on failure.
        """
        self._ensure_connected()
        with self._conn.cursor() as cur:  # type: ignore[union-attr]
            try:
                cur.execute("SELECT pg_promote()")
                row = cur.fetchone()
                promoted = row[0] if row else True
                if promoted:
                    log.info("pg_promote() succeeded — server promoted to primary")
                    return "pg_promote() succeeded. The server is now being promoted to primary."
                else:
                    return (
                        "pg_promote() returned false — the server may already be primary "
                        "or promotion is not allowed from this connection."
                    )
            except psycopg2.ProgrammingError:
                # pg_promote() not available (< PG 12) — try the older approach
                log.info("pg_promote() unavailable, falling back to pg_wal_replay_resume()")
                try:
                    self._conn.rollback()  # type: ignore[union-attr]
                except Exception:
                    pass
            cur.execute("SELECT pg_wal_replay_resume()")
            log.info("pg_wal_replay_resume() called — standby promoted")
            return (
                "pg_wal_replay_resume() called. WAL replay has been resumed/unpaused. "
                "If the server was in pause mode it is now continuing recovery."
            )

    # ------------------------------------------------------------------ #
    #  Schema introspection                                                #
    # ------------------------------------------------------------------ #

    def get_schema_tree(self) -> list[dict]:
        """
        Build a nested schema/relation/column/index/FK/routine tree from
        the pg_* system catalogs.

        Relations cover tables, views, materialised views and foreign tables;
        routines cover functions, procedures, aggregates and window functions.
        Both carry an "oid", which get_view_definition() and
        get_routine_definition() take to fetch source.

        Returns a list of schema dicts — see schema_browser for the shape.
        Raises RuntimeError if not connected.
        """
        self._ensure_connected()

        with self._conn.cursor() as cur:  # type: ignore[union-attr]

            cur.execute(SCHEMA_RELATIONS_SQL)
            relation_rows = cur.fetchall()

            cur.execute(SCHEMA_COLUMNS_SQL)
            column_rows = cur.fetchall()

            cur.execute("""
                SELECT schemaname, tablename, indexname, indexdef
                FROM   pg_indexes
                WHERE  schemaname NOT IN ('pg_catalog', 'information_schema')
                ORDER  BY schemaname, tablename, indexname
            """)
            index_rows = cur.fetchall()

            try:
                cur.execute("""
                    SELECT
                        tc.constraint_schema,
                        tc.table_name,
                        tc.constraint_name,
                        'FOREIGN KEY ' || tc.table_name || '(' ||
                            string_agg(kcu.column_name, ', '
                                       ORDER BY kcu.ordinal_position) ||
                        ') REFERENCES ' || ccu.table_name || '(' ||
                            string_agg(ccu.column_name, ', ') || ')' AS definition
                    FROM  information_schema.table_constraints       AS tc
                    JOIN  information_schema.key_column_usage        AS kcu
                          ON  tc.constraint_name   = kcu.constraint_name
                          AND tc.constraint_schema = kcu.constraint_schema
                    JOIN  information_schema.constraint_column_usage AS ccu
                          ON  ccu.constraint_name   = tc.constraint_name
                          AND ccu.constraint_schema = tc.constraint_schema
                    WHERE tc.constraint_type   = 'FOREIGN KEY'
                      AND tc.constraint_schema NOT IN ('pg_catalog', 'information_schema')
                    GROUP BY tc.constraint_schema, tc.table_name,
                             tc.constraint_name, ccu.table_name
                    ORDER BY tc.constraint_schema, tc.table_name, tc.constraint_name
                """)
                fk_rows = cur.fetchall()
            except psycopg2.Error:
                fk_rows = []

            cur.execute(self._routines_sql())
            fn_rows = cur.fetchall()

        # ── build lookup dicts ──────────────────────────────────────── #
        col_lookup: dict[tuple, list] = {}
        for schema, table, col, dtype, _ in column_rows:
            col_lookup.setdefault((schema, table), []).append(
                {"name": col, "type": dtype}
            )

        idx_lookup: dict[tuple, list] = {}
        for schema, table, name, defn in index_rows:
            idx_lookup.setdefault((schema, table), []).append(
                {"name": name, "definition": defn}
            )

        fk_lookup: dict[tuple, list] = {}
        for schema, table, name, defn in fk_rows:
            fk_lookup.setdefault((schema, table), []).append(
                {"name": name, "definition": defn}
            )

        fn_lookup: dict[str, list] = {}
        for schema, name, oid, args, prokind, rtype in fn_rows:
            arguments = args or ""
            fn_lookup.setdefault(schema, []).append({
                "name":        name,
                "oid":         oid,
                "type":        PROKIND_LABELS.get(prokind, "FUNCTION"),
                "arguments":   arguments,
                # The tree shows the signature, not the name: overloads share
                # a name and are otherwise indistinguishable on screen.
                "signature":   f"{name}({arguments})",
                "return_type": rtype or "",
                "has_source":  prokind not in PROKIND_WITHOUT_SOURCE,
            })

        tbl_lookup: dict[str, list] = {}
        for schema, table, oid, ttype in relation_rows:
            tbl_lookup.setdefault(schema, []).append({
                "name":         table,
                "oid":          oid,
                "type":         ttype,
                "columns":      col_lookup.get((schema, table), []),
                "indexes":      idx_lookup.get((schema, table), []),
                "foreign_keys": fk_lookup.get((schema, table), []),
            })

        all_schemas = sorted(
            set(list(tbl_lookup.keys()) + list(fn_lookup.keys()))
        )

        return [
            {
                "schema":    s,
                "tables":    tbl_lookup.get(s, []),
                "functions": fn_lookup.get(s, []),
            }
            for s in all_schemas
        ]

    # ------------------------------------------------------------------ #
    #  Object source                                                       #
    # ------------------------------------------------------------------ #

    #: Savepoint name for the definition lookups below.  Fixed rather than
    #: generated: only one lookup runs at a time on a given connection.
    _DEFINITION_SAVEPOINT = "coruscant_definition"

    def _routines_sql(self) -> str:
        """
        The pg_proc query this server can actually parse.

        prokind replaced proisagg/proiswindow in PostgreSQL 11, and naming a
        column the server does not have is a parse error, not an empty
        result.  An unknown version takes the modern query: everything that
        predates prokind has been out of support for years, and guessing the
        other way would break every current server to accommodate a rare old
        one.
        """
        version = self.server_version
        if 0 < version < PROKIND_MIN_SERVER_VERSION:
            return SCHEMA_ROUTINES_PRE11_SQL
        return SCHEMA_ROUTINES_SQL

    def _scalar_guarded(self, sql: str, params: tuple):
        """
        Run a one-value catalog query without wrecking an open transaction.

        These lookups share the connection the user runs queries on.  With
        autocommit off, a failed statement aborts the entire surrounding
        transaction and every later statement in it fails too — so asking for
        the source of a routine somebody has just dropped would silently
        throw away uncommitted work.  A savepoint confines the failure to the
        lookup.

        The guard keys on autocommit rather than in_transaction: with
        autocommit off this statement *starts* the transaction when none is
        open yet, and a failure would leave that aborted transaction behind.

        Returns the single value, or None when the query returns no row.
        Raises RuntimeError if not connected, DatabaseError if the query
        fails.
        """
        self._ensure_connected()
        guarded = not self._conn.autocommit      # type: ignore[union-attr]
        savepoint = self._DEFINITION_SAVEPOINT

        with self._conn.cursor() as cur:         # type: ignore[union-attr]
            if guarded:
                cur.execute(f"SAVEPOINT {savepoint}")
            try:
                cur.execute(sql, params)
                row = cur.fetchone()
            except psycopg2.Error as exc:
                first_line = str(exc).splitlines()[0] if str(exc) else exc
                log.error("Definition lookup failed: %s", first_line)
                if guarded:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    cur.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            if guarded:
                cur.execute(f"RELEASE SAVEPOINT {savepoint}")

        return row[0] if row else None

    def get_routine_definition(self, oid: int) -> str:
        """
        Return the CREATE OR REPLACE statement for the routine with this OID.

        pg_get_functiondef() emits a complete, directly re-runnable
        statement, which is the whole point: read it, edit it, execute it.
        Aggregates have no such form — the server raises rather than
        returning text — so callers check the "has_source" flag that
        get_schema_tree() sets instead of calling here and catching.

        Raises RuntimeError if not connected, LookupError if the OID has no
        routine source, DatabaseError if the server refuses.
        """
        definition = self._scalar_guarded(ROUTINE_DEFINITION_SQL, (oid,))
        if not definition:
            raise LookupError(f"no routine source for OID {oid}")
        log.debug("Routine definition fetched  oid=%s  chars=%d",
                  oid, len(definition))
        return definition

    def get_view_definition(self, schema: str, name: str, oid: int,
                            materialized: bool = False) -> str:
        """
        Return a runnable CREATE statement for the view with this OID.

        pg_get_viewdef() returns the SELECT body alone, so the CREATE has to
        be rebuilt around it — unlike routines, where the server hands back a
        complete statement.

        A materialised view gets CREATE, not CREATE OR REPLACE, because
        PostgreSQL has no replace form for one.  Editing it really means DROP
        then CREATE, which throws away the stored rows along with every index
        and grant, so the statement comes back under a comment saying so
        rather than posing as a safe in-place edit.

        Raises RuntimeError if not connected, LookupError if the OID has no
        view source, DatabaseError if the server refuses.
        """
        body = self._scalar_guarded(VIEW_DEFINITION_SQL, (oid,))
        if not body:
            raise LookupError(f"no view source for OID {oid}")

        body = body.rstrip().rstrip(";")
        target = f"{quote_ident(schema)}.{quote_ident(name)}"
        log.debug("View definition fetched  %s  materialized=%s  chars=%d",
                  target, materialized, len(body))

        if materialized:
            return (
                f"-- {target} is a materialised view.\n"
                "-- PostgreSQL has no CREATE OR REPLACE MATERIALIZED VIEW.\n"
                "-- Changing it means DROP then CREATE, which discards the\n"
                "-- stored rows and every index, grant and policy on it.\n"
                f"CREATE MATERIALIZED VIEW {target} AS\n{body};\n"
            )
        return f"CREATE OR REPLACE VIEW {target} AS\n{body};\n"
