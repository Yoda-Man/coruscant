"""
Severity assessment for the Database Doctor.

Coverage showed core/doctor.py at 31%: all four `assess_*` functions and the
duration formatter were entirely unexercised. The only thing referencing them
was `test_severity_functions_present`, which asserts the function *names* exist
— it passes whether they return the right severity or always return OK.

These functions decide whether a user is shown Healthy, Warning or Critical,
and therefore whether they reach for a repair button. They are pure — row
tuples in, (severity, message) out — so there is no excuse for mocking or for
leaving them untested.

Thresholds are asserted at their boundaries, since off-by-one at a comparison
is the failure these would actually suffer. Every value below is taken from
the source, not assumed.
"""
from __future__ import annotations

import pytest

from coruscant.core.doctor import (
    CRITICAL,
    OK,
    WARNING,
    WAIT_SECS_COL,
    assess_bloat,
    assess_connections,
    assess_locks,
    assess_wraparound,
    _fmt_dur,
)


# ---------------------------------------------------------------------------
# Lock contention:  no rows -> OK;  max wait > 60s -> CRITICAL;  else WARNING
# ---------------------------------------------------------------------------

class TestAssessLocks:
    @staticmethod
    def _row(wait_secs):
        """A LOCKS_SQL row with wait_secs in the position the code reads."""
        row = [None] * 7
        row[WAIT_SECS_COL] = wait_secs
        return tuple(row)

    def test_no_blocked_queries_is_healthy(self):
        sev, msg = assess_locks([])
        assert sev == OK
        assert "no blocked queries" in msg.lower()

    def test_blocked_under_a_minute_is_a_warning(self):
        sev, _ = assess_locks([self._row(59)])
        assert sev == WARNING

    def test_exactly_sixty_seconds_is_still_a_warning(self):
        """The test is `> 60`, so 60 itself must not escalate."""
        sev, _ = assess_locks([self._row(60)])
        assert sev == WARNING

    def test_over_a_minute_is_critical(self):
        sev, _ = assess_locks([self._row(61)])
        assert sev == CRITICAL

    def test_severity_follows_the_longest_waiter(self):
        sev, _ = assess_locks([self._row(5), self._row(300), self._row(1)])
        assert sev == CRITICAL

    def test_null_wait_is_treated_as_zero_not_a_crash(self):
        """query_start can be NULL, so the column can come back as None."""
        sev, _ = assess_locks([self._row(None)])
        assert sev == WARNING

    def test_message_reports_how_many_and_how_long(self):
        _, msg = assess_locks([self._row(90), self._row(10)])
        assert "2" in msg
        assert "1m 30s" in msg


# ---------------------------------------------------------------------------
# Bloat:  no rows -> OK;  worst >= 30% or 10+ tables -> CRITICAL;  else WARNING
# ---------------------------------------------------------------------------

class TestAssessBloat:
    @staticmethod
    def _row(dead_pct):
        # assess_bloat reads column 4 (dead_pct) of a BLOAT_SQL row.
        return ("public", "t", 0, 0, dead_pct, "Never")

    def test_no_bloat_is_healthy(self):
        sev, msg = assess_bloat([])
        assert sev == OK
        assert "no significant table bloat" in msg.lower()

    def test_mild_bloat_is_a_warning(self):
        sev, _ = assess_bloat([self._row(29.9)])
        assert sev == WARNING

    def test_thirty_percent_is_critical(self):
        """Boundary: the test is `>= 30`."""
        sev, _ = assess_bloat([self._row(30.0)])
        assert sev == CRITICAL

    def test_nine_mild_tables_is_a_warning(self):
        sev, _ = assess_bloat([self._row(6.0)] * 9)
        assert sev == WARNING

    def test_ten_tables_is_critical_regardless_of_severity(self):
        """Boundary: breadth escalates even when every table is mildly bloated."""
        sev, _ = assess_bloat([self._row(6.0)] * 10)
        assert sev == CRITICAL

    def test_message_reports_count_and_worst_case(self):
        _, msg = assess_bloat([self._row(12.5), self._row(93.8)])
        assert "2" in msg
        assert "93.8" in msg

    def test_accepts_decimal_values_from_the_driver(self):
        """round() in SQL returns numeric, which psycopg2 hands back as Decimal."""
        from decimal import Decimal
        sev, msg = assess_bloat([self._row(Decimal("93.8"))])
        assert sev == CRITICAL
        assert "93.8" in msg


# ---------------------------------------------------------------------------
# Connections:  pct >= 85 or idle_txn >= 5 -> CRITICAL
#               pct >= 70 or idle_txn >= 2 or long_running >= 1 -> WARNING
# ---------------------------------------------------------------------------

class TestAssessConnections:
    @staticmethod
    def _row(total=10, max_conn=100, idle=0, idle_txn=0, active=0, long_running=0):
        return (total, max_conn, idle, idle_txn, active, long_running)

    def test_quiet_server_is_healthy(self):
        sev, _ = assess_connections(self._row(total=10))
        assert sev == OK

    def test_seventy_percent_used_is_a_warning(self):
        sev, _ = assess_connections(self._row(total=70))
        assert sev == WARNING

    def test_eighty_five_percent_used_is_critical(self):
        sev, _ = assess_connections(self._row(total=85))
        assert sev == CRITICAL

    def test_two_idle_in_transaction_is_a_warning(self):
        sev, _ = assess_connections(self._row(total=5, idle_txn=2))
        assert sev == WARNING

    def test_five_idle_in_transaction_is_critical_even_on_a_quiet_server(self):
        """Idle-in-transaction holds locks and blocks vacuum, so count matters
        more than the connection percentage."""
        sev, _ = assess_connections(self._row(total=5, idle_txn=5))
        assert sev == CRITICAL

    def test_a_single_long_running_query_is_a_warning(self):
        sev, _ = assess_connections(self._row(total=1, long_running=1))
        assert sev == WARNING

    def test_zero_max_connections_does_not_divide_by_zero(self):
        """max_conn arrives from a subquery and could be 0 or missing."""
        sev, msg = assess_connections(self._row(total=5, max_conn=0))
        assert sev == OK
        assert "0%" in msg

    def test_message_reports_the_breakdown(self):
        _, msg = assess_connections(self._row(total=27, max_conn=2000, idle=3, idle_txn=1, active=2))
        assert "27/2000" in msg
        assert "idle: 3" in msg
        assert "idle-in-txn: 1" in msg
        assert "active: 2" in msg


# ---------------------------------------------------------------------------
# Wraparound:  >= 70% -> CRITICAL;  >= 40% -> WARNING;  else OK
# ---------------------------------------------------------------------------

class TestAssessWraparound:
    @staticmethod
    def _row(pct):
        return ("db", 1, 1, pct)

    def test_no_databases_is_healthy(self):
        sev, msg = assess_wraparound([])
        assert sev == OK
        assert "no databases" in msg.lower()

    def test_low_age_is_healthy(self):
        sev, _ = assess_wraparound([self._row(7.5)])
        assert sev == OK

    def test_forty_percent_is_a_warning(self):
        sev, msg = assess_wraparound([self._row(40.0)])
        assert sev == WARNING
        assert "vacuum freeze" in msg.lower()

    def test_seventy_percent_is_critical(self):
        sev, msg = assess_wraparound([self._row(70.0)])
        assert sev == CRITICAL
        assert "immediately" in msg.lower()

    def test_severity_follows_the_worst_database(self):
        sev, _ = assess_wraparound([self._row(1.0), self._row(88.0), self._row(3.0)])
        assert sev == CRITICAL

    def test_accepts_decimal_values_from_the_driver(self):
        from decimal import Decimal
        sev, _ = assess_wraparound([self._row(Decimal("72.10"))])
        assert sev == CRITICAL


# ---------------------------------------------------------------------------
# Duration formatting — appears in the lock summary the user reads
# ---------------------------------------------------------------------------

class TestFormatDuration:
    @pytest.mark.parametrize("secs,expected", [
        (0,     "0s"),
        (59,    "59s"),
        (60,    "1m 0s"),
        (61,    "1m 1s"),
        (3599,  "59m 59s"),
        (3600,  "1h 0m"),
        (7325,  "2h 2m"),
    ])
    def test_boundaries(self, secs, expected):
        assert _fmt_dur(secs) == expected
