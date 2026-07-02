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
    ) -> None:
        """Open a connection.  Raises psycopg2.OperationalError on failure."""
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
                connect_timeout=10,
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
    ) -> None:
        """
        VACUUM (optionally FULL + ANALYZE) a single table.

        VACUUM cannot run inside a transaction, so this method temporarily
        switches the connection to autocommit mode regardless of the current
        setting and restores it afterward.

        Raises RuntimeError if not connected, psycopg2.Error on failure.
        """
        self._ensure_connected()
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
        finally:
            self._conn.autocommit = old_ac  # type: ignore[union-attr]

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

    def vacuum_freeze(self) -> None:
        """
        Issue VACUUM FREEZE on all tables in the current database.

        This is the standard remedy for approaching XID wraparound.
        Runs with autocommit=True (required for VACUUM).
        Can be slow on large databases; run off the UI thread.

        Raises RuntimeError if not connected, psycopg2.Error on failure.
        """
        self._ensure_connected()
        old_ac = self._conn.autocommit  # type: ignore[union-attr]
        self._conn.autocommit = True    # type: ignore[union-attr]
        try:
            with self._conn.cursor() as cur:  # type: ignore[union-attr]
                cur.execute("VACUUM FREEZE")
            log.info("VACUUM FREEZE complete")
        finally:
            self._conn.autocommit = old_ac  # type: ignore[union-attr]

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
        Build a nested schema/table/column/index/FK/function tree from
        information_schema and pg_* system catalogs.

        Returns a list of schema dicts — see schema_browser for the shape.
        Raises RuntimeError if not connected.
        """
        self._ensure_connected()

        with self._conn.cursor() as cur:  # type: ignore[union-attr]

            cur.execute("""
                SELECT table_schema, table_name, table_type
                FROM   information_schema.tables
                WHERE  table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER  BY table_schema, table_type, table_name
            """)
            table_rows = cur.fetchall()

            cur.execute("""
                SELECT table_schema, table_name, column_name, data_type, ordinal_position
                FROM   information_schema.columns
                WHERE  table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER  BY table_schema, table_name, ordinal_position
            """)
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

            cur.execute("""
                SELECT routine_schema, routine_name, routine_type, data_type
                FROM   information_schema.routines
                WHERE  routine_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER  BY routine_schema, routine_type, routine_name
            """)
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
        for schema, name, ftype, rtype in fn_rows:
            fn_lookup.setdefault(schema, []).append(
                {"name": name, "type": ftype, "return_type": rtype or ""}
            )

        tbl_lookup: dict[str, list] = {}
        for schema, table, ttype in table_rows:
            tbl_lookup.setdefault(schema, []).append({
                "name":         table,
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
