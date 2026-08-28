"""
coruscant.core.doctor
~~~~~~~~~~~~~~~~~~~~~
SQL queries and severity assessment for the Database Doctor feature.

Four health checks:
  locks       — blocked queries and their blockers
  bloat       — dead tuple accumulation needing VACUUM
  connections — idle / idle-in-transaction connection pile-up
  wraparound  — transaction ID age approaching the 2-billion limit

Each assess_*() function takes the raw rows returned by the companion
SQL query and returns (severity, summary_text).

Severity constants: OK  WARNING  CRITICAL  ERROR

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

OK       = "ok"
WARNING  = "warning"
CRITICAL = "critical"
ERROR    = "error"

# ── 1. Lock Contention ────────────────────────────────────────────── #

LOCKS_SQL = """
SELECT
    blocked.pid                                              AS blocked_pid,
    blocked.usename                                          AS blocked_user,
    left(blocked.query, 80)                                  AS blocked_query,
    EXTRACT(EPOCH FROM (now() - blocked.query_start))::int   AS wait_secs,
    blocking.pid                                             AS blocking_pid,
    blocking.usename                                         AS blocking_user,
    left(blocking.query, 60)                                 AS blocking_query
FROM  pg_stat_activity AS blocked
JOIN  pg_stat_activity AS blocking
      ON  blocking.pid = ANY(pg_blocking_pids(blocked.pid))
ORDER BY wait_secs DESC
"""


def assess_locks(rows: list[tuple]) -> tuple[str, str]:
    n = len(rows)
    if n == 0:
        return OK, "No blocked queries detected."
    max_wait = max(int(r[3] or 0) for r in rows)
    sev = CRITICAL if max_wait > 60 else WARNING
    return sev, f"{n} blocked query/ies — longest waiting {_fmt_dur(max_wait)}."


# ── 2. Table Bloat ────────────────────────────────────────────────── #

BLOAT_SQL = """
SELECT
    schemaname                                               AS schema,
    relname                                                  AS table,
    n_dead_tup                                               AS dead_tuples,
    n_live_tup                                               AS live_tuples,
    CASE WHEN n_live_tup + n_dead_tup > 0
         THEN round(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 1)
         ELSE 0
    END                                                      AS dead_pct,
    coalesce(
        greatest(last_vacuum, last_autovacuum)::text,
        'Never'
    )                                                        AS last_vacuum
FROM  pg_stat_user_tables
WHERE n_dead_tup > 500
   OR (n_live_tup + n_dead_tup > 0
       AND 100.0 * n_dead_tup / (n_live_tup + n_dead_tup) > 5)
ORDER BY dead_pct DESC, n_dead_tup DESC
LIMIT 20
"""


def assess_bloat(rows: list[tuple]) -> tuple[str, str]:
    n = len(rows)
    if n == 0:
        return OK, "No significant table bloat detected."
    max_pct = float(max(r[4] for r in rows))
    sev = CRITICAL if (max_pct >= 30 or n >= 10) else WARNING
    return sev, f"{n} table(s) with significant bloat — worst: {max_pct:.1f}% dead tuples."


# ── 3. Connection Health ──────────────────────────────────────────── #

CONN_SUMMARY_SQL = """
SELECT
    count(*)                                                  AS total,
    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')
                                                              AS max_conn,
    count(*) FILTER (WHERE state = 'idle')                    AS idle,
    count(*) FILTER (WHERE state = 'idle in transaction')     AS idle_in_txn,
    count(*) FILTER (WHERE state = 'active')                  AS active,
    count(*) FILTER (WHERE state = 'active'
        AND query_start < now() - interval '5 minutes')       AS long_running
FROM pg_stat_activity
WHERE pid != pg_backend_pid()
"""

CONN_DETAIL_SQL = """
SELECT
    pid,
    usename                                                   AS user,
    application_name                                          AS app,
    client_addr::text                                         AS client,
    state,
    EXTRACT(EPOCH FROM (now() - state_change))::int           AS idle_secs,
    left(query, 60)                                           AS query
FROM pg_stat_activity
WHERE pid != pg_backend_pid()
  AND state IN ('idle', 'idle in transaction')
ORDER BY state, idle_secs DESC
LIMIT 30
"""


def assess_connections(summary_row: tuple) -> tuple[str, str]:
    """summary_row = (total, max_conn, idle, idle_in_txn, active, long_running)."""
    total, max_conn, idle, idle_txn, active, long_running = summary_row
    pct = round(100.0 * total / max_conn, 1) if max_conn else 0
    if pct >= 85 or idle_txn >= 5:
        sev = CRITICAL
    elif pct >= 70 or idle_txn >= 2 or long_running >= 1:
        sev = WARNING
    else:
        sev = OK
    summary = (
        f"{total}/{max_conn} connections used ({pct}%)  —  "
        f"idle: {idle}   idle-in-txn: {idle_txn}   active: {active}"
    )
    return sev, summary


# ── 4. XID Wraparound ─────────────────────────────────────────────── #

WRAPAROUND_SQL = """
SELECT
    datname                                                   AS database,
    age(datfrozenxid)                                         AS xid_age,
    2147483647 - age(datfrozenxid)                            AS xids_remaining,
    round(100.0 * age(datfrozenxid) / 2147483647, 2)          AS pct_used
FROM  pg_database
WHERE datallowconn
  AND datname NOT IN ('template0')
ORDER BY age(datfrozenxid) DESC
"""


def assess_wraparound(rows: list[tuple]) -> tuple[str, str]:
    if not rows:
        return OK, "No databases found."
    max_pct = float(max(r[3] for r in rows))
    if max_pct >= 70:
        return CRITICAL, (
            f"⚠ XID age at {max_pct:.1f}% of the 2-billion limit — "
            "run VACUUM FREEZE immediately!"
        )
    if max_pct >= 40:
        return WARNING, (
            f"XID age at {max_pct:.1f}% of the limit — "
            "schedule VACUUM FREEZE soon."
        )
    return OK, f"Transaction ID usage healthy — highest at {max_pct:.1f}% of limit."


# ── Helpers ───────────────────────────────────────────────────────── #

def _fmt_dur(secs: int) -> str:
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(int(secs), 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"
