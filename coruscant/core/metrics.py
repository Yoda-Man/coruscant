"""
coruscant.core.metrics
~~~~~~~~~~~~~~~~~~~~~~~
SQL queries and helpers for the live Database Monitoring Dashboard.

No GUI imports.  This module only defines the SQL used to sample the
server's real-time statistics and the small pure-Python helpers that turn
two consecutive samples into human-readable rates (transactions/sec,
cache-hit %, tuples/sec, …).

The dashboard groups metrics into three layers:

  1. INSTANT       — single-row gauges sampled every refresh
                     (`GLOBAL_SQL`, `DBSTATS_SQL`).
  2. RATES         — deltas between two consecutive `DBSTATS_SQL` samples,
                     computed by :func:`compute_rates`.
  3. DETAIL TABLES — richer breakdowns shown in the tabbed lower area
                     (activity, connections, tables, indexes, databases,
                     locks, replication, bgwriter, settings, statements).

Every detail query is intentionally defensive: it only touches catalogs
and columns available on modern PostgreSQL (10+).  Queries that depend on
an optional extension (`pg_stat_statements`) are separated so the caller
can degrade gracefully when the extension is not installed.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ==================================================================== #
#  1. Instant gauges (single row each)                                   #
# ==================================================================== #

#: High-level server + connection snapshot — one row.
GLOBAL_SQL = """
SELECT
    current_database()                                              AS database,
    pg_database_size(current_database())                           AS db_size_bytes,
    pg_size_pretty(pg_database_size(current_database()))           AS db_size,
    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')
                                                                    AS max_conn,
    (SELECT count(*) FROM pg_stat_activity)                         AS total_conn,
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'active')  AS active_conn,
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'idle')    AS idle_conn,
    (SELECT count(*) FROM pg_stat_activity
        WHERE state = 'idle in transaction')                        AS idle_txn_conn,
    (SELECT count(*) FROM pg_stat_activity
        WHERE wait_event_type = 'Lock')                             AS waiting_conn,
    (SELECT coalesce(max(EXTRACT(EPOCH FROM (now() - query_start)))::bigint, 0)
        FROM pg_stat_activity
        WHERE state = 'active' AND pid != pg_backend_pid())         AS longest_query_secs,
    EXTRACT(EPOCH FROM (now() - pg_postmaster_start_time()))::bigint AS uptime_secs,
    pg_postmaster_start_time()::text                                AS start_time,
    now()::text                                                     AS server_time,
    pg_is_in_recovery()                                             AS in_recovery,
    (SELECT count(*) FROM pg_stat_activity AS b
        WHERE cardinality(pg_blocking_pids(b.pid)) > 0)             AS blocked_conn,
    version()                                                       AS version
"""

#: Cumulative counters for the current database — one row.
#: Used both as instant gauges and as the basis for rate computation.
DBSTATS_SQL = """
SELECT
    numbackends,
    xact_commit,
    xact_rollback,
    blks_read,
    blks_hit,
    tup_returned,
    tup_fetched,
    tup_inserted,
    tup_updated,
    tup_deleted,
    conflicts,
    deadlocks,
    temp_files,
    temp_bytes,
    coalesce(blk_read_time, 0)                                      AS blk_read_time,
    coalesce(blk_write_time, 0)                                     AS blk_write_time,
    CASE WHEN blks_hit + blks_read > 0
         THEN round(100.0 * blks_hit / (blks_hit + blks_read), 2)
         ELSE 100
    END                                                            AS cache_hit_pct,
    stats_reset::text                                              AS stats_reset
FROM pg_stat_database
WHERE datname = current_database()
"""

# ==================================================================== #
#  2. Detail tables (multi-row)                                          #
# ==================================================================== #

#: Live, non-idle backends — what the server is doing right now.
ACTIVITY_SQL = """
SELECT
    pid,
    usename                                                         AS "user",
    application_name                                                AS app,
    coalesce(client_addr::text, 'local')                           AS client,
    state,
    coalesce(wait_event_type || ':' || wait_event, '')             AS wait,
    EXTRACT(EPOCH FROM (now() - query_start))::int                 AS secs,
    left(regexp_replace(query, '\\s+', ' ', 'g'), 120)             AS query
FROM pg_stat_activity
WHERE state IS NOT NULL
  AND state <> 'idle'
  AND pid != pg_backend_pid()
ORDER BY (state = 'active') DESC, secs DESC NULLS LAST
LIMIT 40
"""

#: Connection counts grouped by state.
CONN_BY_STATE_SQL = """
SELECT
    coalesce(state, 'unknown')                                      AS state,
    count(*)                                                        AS connections,
    round(100.0 * count(*) / NULLIF(sum(count(*)) OVER (), 0), 1)   AS pct
FROM pg_stat_activity
GROUP BY state
ORDER BY connections DESC
"""

#: Connection counts grouped by user / application / client host.
CONN_BY_USER_SQL = """
SELECT
    coalesce(usename, '—')                                          AS "user",
    coalesce(application_name, '—')                                 AS application,
    coalesce(client_addr::text, 'local')                           AS client,
    count(*)                                                        AS connections,
    count(*) FILTER (WHERE state = 'active')                        AS active,
    count(*) FILTER (WHERE state = 'idle')                          AS idle
FROM pg_stat_activity
GROUP BY usename, application_name, client_addr
ORDER BY connections DESC
LIMIT 30
"""

#: Biggest tables with access + maintenance stats.
TABLE_STATS_SQL = """
SELECT
    schemaname                                                      AS schema,
    relname                                                         AS "table",
    pg_size_pretty(pg_total_relation_size(relid))                  AS total_size,
    n_live_tup                                                      AS live_rows,
    n_dead_tup                                                      AS dead_rows,
    CASE WHEN n_live_tup + n_dead_tup > 0
         THEN round(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 1)
         ELSE 0 END                                                 AS dead_pct,
    seq_scan,
    idx_scan,
    CASE WHEN coalesce(seq_scan, 0) + coalesce(idx_scan, 0) > 0
         THEN round(100.0 * coalesce(idx_scan, 0)
                    / (coalesce(seq_scan, 0) + coalesce(idx_scan, 0)), 1)
         ELSE 0 END                                                 AS idx_pct,
    coalesce(greatest(last_vacuum, last_autovacuum)::text, 'never') AS last_vacuum,
    coalesce(greatest(last_analyze, last_autoanalyze)::text, 'never') AS last_analyze
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 40
"""

#: Index usage — surfaces unused / low-use indexes wasting write throughput.
INDEX_USAGE_SQL = """
SELECT
    schemaname                                                      AS schema,
    relname                                                         AS "table",
    indexrelname                                                    AS index,
    pg_size_pretty(pg_relation_size(indexrelid))                   AS size,
    idx_scan                                                        AS scans,
    idx_tup_read                                                    AS tuples_read,
    idx_tup_fetch                                                   AS tuples_fetched
FROM pg_stat_user_indexes
ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC
LIMIT 40
"""

#: Cache hit ratio per table (heap blocks) — where reads miss the buffer cache.
TABLE_CACHE_SQL = """
SELECT
    schemaname                                                      AS schema,
    relname                                                         AS "table",
    heap_blks_read                                                  AS disk_reads,
    heap_blks_hit                                                   AS cache_hits,
    CASE WHEN heap_blks_hit + heap_blks_read > 0
         THEN round(100.0 * heap_blks_hit
                    / (heap_blks_hit + heap_blks_read), 2)
         ELSE 100 END                                               AS hit_pct
FROM pg_statio_user_tables
WHERE heap_blks_hit + heap_blks_read > 0
ORDER BY (heap_blks_hit + heap_blks_read) DESC
LIMIT 40
"""

#: All databases on the cluster with size + activity.
DATABASES_SQL = """
SELECT
    datname                                                         AS database,
    pg_size_pretty(pg_database_size(datname))                      AS size,
    numbackends                                                     AS connections,
    xact_commit                                                     AS commits,
    xact_rollback                                                   AS rollbacks,
    CASE WHEN blks_hit + blks_read > 0
         THEN round(100.0 * blks_hit / (blks_hit + blks_read), 2)
         ELSE 100 END                                               AS cache_hit_pct,
    deadlocks,
    temp_files
FROM pg_stat_database
WHERE datname NOT IN ('template0', 'template1')
  AND datname IS NOT NULL
ORDER BY pg_database_size(datname) DESC NULLS LAST
"""

#: Blocked / blocking sessions (lock contention).
LOCKS_SQL = """
SELECT
    blocked.pid                                                     AS blocked_pid,
    blocked.usename                                                 AS blocked_user,
    EXTRACT(EPOCH FROM (now() - blocked.query_start))::int          AS wait_secs,
    left(regexp_replace(blocked.query, '\\s+', ' ', 'g'), 60)      AS blocked_query,
    blocking.pid                                                    AS blocking_pid,
    blocking.usename                                                AS blocking_user,
    left(regexp_replace(blocking.query, '\\s+', ' ', 'g'), 60)     AS blocking_query
FROM pg_stat_activity AS blocked
JOIN pg_stat_activity AS blocking
     ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
ORDER BY wait_secs DESC
LIMIT 30
"""

#: Streaming replication status (empty on servers with no standbys).
REPLICATION_SQL = """
SELECT
    application_name                                                AS standby,
    coalesce(client_addr::text, 'local')                           AS client,
    state,
    sync_state,
    coalesce(pg_size_pretty(
        pg_wal_lsn_diff(sent_lsn, replay_lsn)), '0 bytes')          AS replay_lag,
    coalesce(pg_size_pretty(
        pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)), '0 bytes') AS send_lag
FROM pg_stat_replication
ORDER BY application_name
"""

#: Key tunables that most affect performance.
SETTINGS_SQL = """
SELECT
    name                                                            AS setting,
    setting || coalesce(' ' || unit, '')                           AS value,
    coalesce(short_desc, '')                                        AS description
FROM pg_settings
WHERE name IN (
    'max_connections', 'shared_buffers', 'effective_cache_size',
    'work_mem', 'maintenance_work_mem', 'wal_buffers',
    'checkpoint_timeout', 'max_wal_size', 'min_wal_size',
    'random_page_cost', 'effective_io_concurrency',
    'autovacuum', 'max_worker_processes', 'max_parallel_workers',
    'server_version', 'data_directory'
)
ORDER BY name
"""

#: Top statements by total execution time — requires pg_stat_statements.
STATEMENTS_SQL = """
SELECT
    calls,
    round(total_exec_time::numeric, 1)                             AS total_ms,
    round(mean_exec_time::numeric, 2)                              AS mean_ms,
    round(100.0 * total_exec_time
          / NULLIF(sum(total_exec_time) OVER (), 0), 1)            AS pct,
    rows,
    left(regexp_replace(query, '\\s+', ' ', 'g'), 120)            AS query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 30
"""

# ==================================================================== #
#  Query registry — the dashboard worker iterates over these.            #
# ==================================================================== #

#: name -> SQL for the multi-row detail tables. Each is fetched
#: independently so one failing query never blanks the whole dashboard.
DETAIL_QUERIES: dict[str, str] = {
    "activity":      ACTIVITY_SQL,
    "conn_state":    CONN_BY_STATE_SQL,
    "conn_user":     CONN_BY_USER_SQL,
    "tables":        TABLE_STATS_SQL,
    "indexes":       INDEX_USAGE_SQL,
    "table_cache":   TABLE_CACHE_SQL,
    "databases":     DATABASES_SQL,
    "locks":         LOCKS_SQL,
    "replication":   REPLICATION_SQL,
    "settings":      SETTINGS_SQL,
}

# ==================================================================== #
#  Rate computation                                                      #
# ==================================================================== #

# Cumulative counter columns from DBSTATS_SQL that we turn into per-second
# rates.  (column name -> index in the row.)
_DBSTATS_COLS = [
    "numbackends", "xact_commit", "xact_rollback", "blks_read", "blks_hit",
    "tup_returned", "tup_fetched", "tup_inserted", "tup_updated", "tup_deleted",
    "conflicts", "deadlocks", "temp_files", "temp_bytes",
    "blk_read_time", "blk_write_time", "cache_hit_pct", "stats_reset",
]


def dbstats_to_dict(row: tuple) -> dict[str, Any]:
    """Map a DBSTATS_SQL row tuple to a named dict."""
    return dict(zip(_DBSTATS_COLS, row))


@dataclass
class Rates:
    """Per-second rates derived from two consecutive DBSTATS samples."""
    tps:            float = 0.0   # commits + rollbacks per second
    commits:        float = 0.0
    rollbacks:      float = 0.0
    rows_returned:  float = 0.0
    rows_fetched:   float = 0.0
    rows_inserted:  float = 0.0
    rows_updated:   float = 0.0
    rows_deleted:   float = 0.0
    blocks_read:    float = 0.0
    blocks_hit:     float = 0.0
    interval_cache_hit: float = 100.0   # cache-hit % over the interval only
    deadlocks:      float = 0.0
    temp_files:     float = 0.0
    valid:          bool  = False       # False for the very first sample


def compute_rates(prev: dict[str, Any] | None,
                  curr: dict[str, Any],
                  dt_secs: float) -> Rates:
    """
    Compute per-second rates between two DBSTATS dicts.

    The first call (``prev is None``) returns an all-zero ``Rates`` with
    ``valid=False`` — there is no interval to divide by yet.
    A stats reset between samples (counters going backwards) also yields an
    invalid result so the UI can skip that data point.
    """
    if prev is None or dt_secs <= 0:
        return Rates()

    def d(key: str) -> float:
        delta = float(curr.get(key, 0) or 0) - float(prev.get(key, 0) or 0)
        return delta

    commits   = d("xact_commit")
    rollbacks = d("xact_rollback")
    b_read    = d("blks_read")
    b_hit     = d("blks_hit")

    # Counters went backwards → stats were reset; don't emit a bogus spike.
    if min(commits, rollbacks, b_read, b_hit) < 0:
        return Rates()

    total_blocks = b_read + b_hit
    interval_hit = (100.0 * b_hit / total_blocks) if total_blocks > 0 else 100.0

    return Rates(
        tps=(commits + rollbacks) / dt_secs,
        commits=commits / dt_secs,
        rollbacks=rollbacks / dt_secs,
        rows_returned=d("tup_returned") / dt_secs,
        rows_fetched=d("tup_fetched") / dt_secs,
        rows_inserted=d("tup_inserted") / dt_secs,
        rows_updated=d("tup_updated") / dt_secs,
        rows_deleted=d("tup_deleted") / dt_secs,
        blocks_read=b_read / dt_secs,
        blocks_hit=b_hit / dt_secs,
        interval_cache_hit=interval_hit,
        deadlocks=d("deadlocks") / dt_secs,
        temp_files=d("temp_files") / dt_secs,
        valid=True,
    )


# ==================================================================== #
#  Formatting helpers                                                    #
# ==================================================================== #

def fmt_duration(secs: float | int | None) -> str:
    """Human-readable duration: 45s, 12m 03s, 3h 22m, 2d 4h."""
    if secs is None:
        return "—"
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m:02d}m"
    days, h = divmod(h, 24)
    return f"{days}d {h}h"


def fmt_count(value: float | int | None) -> str:
    """Compact number: 1.2K, 3.4M, 5.6B."""
    if value is None:
        return "—"
    value = float(value)
    for suffix, threshold in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= threshold:
            return f"{value / threshold:.1f}{suffix}"
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def fmt_rate(value: float | None, unit: str = "/s") -> str:
    """Format a per-second rate compactly."""
    if value is None:
        return "—"
    return f"{fmt_count(value)}{unit}"
