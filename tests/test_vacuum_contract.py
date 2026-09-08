"""
Contract tests for PostgreSQL maintenance commands (VACUUM and friends).

These exist because of a bug that shipped twice over:

  * The Database Doctor reported "VACUUM ANALYZE complete on 20 table(s)"
    having vacuumed none. PostgreSQL refuses maintenance on a table you do not
    own by emitting a WARNING and reporting overall success, and the code
    treated "no exception" as "work done".

  * The first fix detected that refusal by matching the English words in the
    warning. Those messages are translated per the server's lc_messages, so on
    a non-English server the fix silently stopped working — and failed open,
    straight back to reporting success.

The guards below are deliberately written against the *contract* ("never
report success for work the server declined") rather than any one mechanism
for discovering it, because that mechanism has already changed once.

psycopg2 is stubbed by tests.test_database at import time; the connection
helper is reused from there.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from tests.test_database import _make_connected_db  # also installs the psycopg2 stub

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fake server states
# ---------------------------------------------------------------------------

def _server_refuses_maintenance(mc, cur):
    """
    Make the fake server answer "this role may not maintain anything".

    Mechanism-agnostic on purpose: it sets the *answers a real server would
    give*, not the internals the code uses to ask. can_maintain() reads
    fetchone(); unmaintainable_tables() reads fetchall(); the previous
    implementation read conn.notices. All three are satisfied, so these tests
    survive another change of strategy.
    """
    cur.fetchone.return_value = (False,)
    cur.fetchall.return_value = [("public.t",)]
    mc.notices = []
    cur.execute.side_effect = lambda *a, **k: mc.notices.append(
        'WARNING:  skipping "t" --- only table or database owner can vacuum it\n'
    )


def _server_permits_maintenance(mc, cur):
    cur.fetchone.return_value = (True,)
    cur.fetchall.return_value = []
    mc.notices = []
    cur.execute.side_effect = None


# ---------------------------------------------------------------------------
# vacuum_table behaviour
# ---------------------------------------------------------------------------

class TestVacuumReportsRefusedWork:
    def test_reports_a_reason_when_role_may_not_vacuum(self):
        db, mc, cur = _make_connected_db()
        _server_refuses_maintenance(mc, cur)
        reasons = db.vacuum_table("tgorganisation", "tgorganisationidentification")
        assert reasons, "a refused VACUUM must be reported to the caller"
        assert "owner" in reasons[0].lower()
        assert "tgorganisationidentification" in reasons[0]

    def test_returns_empty_when_vacuum_actually_ran(self):
        db, mc, cur = _make_connected_db()
        _server_permits_maintenance(mc, cur)
        assert db.vacuum_table("public", "orders") == []

    def test_does_not_issue_a_vacuum_the_server_will_refuse(self):
        db, mc, cur = _make_connected_db()
        _server_refuses_maintenance(mc, cur)
        cur.execute.reset_mock()
        db.vacuum_table("public", "orders")
        issued = [c for c in cur.execute.call_args_list if "VACUUM" in str(c).upper()]
        assert not issued, f"issued a VACUUM despite lacking rights: {issued}"

    def test_autocommit_is_restored(self):
        db, mc, cur = _make_connected_db(autocommit=False)
        _server_permits_maintenance(mc, cur)
        db.vacuum_table("s", "t")
        assert mc.autocommit is False


class TestVacuumFullIsOptIn:
    """VACUUM FULL takes ACCESS EXCLUSIVE and rewrites the table — it must
    never appear on the default path."""

    def test_full_true_issues_vacuum_full(self):
        db, mc, cur = _make_connected_db()
        _server_permits_maintenance(mc, cur)
        db.vacuum_table("public", "orders", full=True)
        sql = " ".join(str(c) for c in cur.execute.call_args_list).upper()
        assert "FULL" in sql, f"FULL not issued: {sql}"

    def test_default_vacuum_is_never_full(self):
        db, mc, cur = _make_connected_db()
        _server_permits_maintenance(mc, cur)
        db.vacuum_table("public", "orders")
        sql = " ".join(str(c) for c in cur.execute.call_args_list).upper()
        assert "FULL" not in sql, f"default VACUUM must never be FULL: {sql}"


class TestLocaleIndependence:
    """
    Detection must not depend on the wording of PostgreSQL's warning, which is
    translated according to the server's lc_messages.
    """

    def test_refusal_detected_when_the_warning_is_not_english(self):
        db, mc, cur = _make_connected_db()
        cur.fetchone.return_value = (False,)      # catalog says: not permitted
        mc.notices = []
        cur.execute.side_effect = lambda *a, **k: mc.notices.append(
            "AVERTISSEMENT:  ignore « t » --- seul le "
            "propriétaire peut exécuter un VACUUM\n"
        )
        assert db.vacuum_table("public", "t"), (
            "refusal detection must not depend on English warning text"
        )

    def test_permission_check_reads_the_catalog_not_a_message(self):
        from coruscant.core.database import CAN_MAINTAIN_SQL
        sql = CAN_MAINTAIN_SQL.lower()
        assert "pg_has_role" in sql and "pg_class" in sql
        for word in ("skipping", "warning", "can vacuum it"):
            assert word not in sql, f"permission check depends on message text: {word}"


# ---------------------------------------------------------------------------
# Class-wide contract
# ---------------------------------------------------------------------------

class TestMaintenanceCommandsSurfaceRefusals:
    """
    Maintenance methods are discovered by parsing core/database.py rather than
    listed by hand, so a repair added later is covered without anyone
    remembering to write a test for it.
    """

    MAINTENANCE_SQL = ("VACUUM", "REINDEX", "CLUSTER", "ANALYZE")

    # Methods issuing a maintenance command that legitimately cannot be refused
    # for ownership. Keep empty unless there is a real reason, and state it —
    # this set is the escape hatch that would let the bug back in.
    EXEMPT: dict[str, str] = {}

    @classmethod
    def _maintenance_methods(cls) -> dict[str, int]:
        src = (_ROOT / "coruscant" / "core" / "database.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found: dict[str, int] = {}
        for cls_node in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            if cls_node.name != "DatabaseManager":
                continue
            for fn in (n for n in cls_node.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
                for sub in ast.walk(fn):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        if any(sub.value.strip().upper().startswith(v)
                               for v in cls.MAINTENANCE_SQL):
                            found[fn.name] = fn.lineno
                            break
        return found

    def test_discovery_finds_the_known_maintenance_methods(self):
        """Guards the guard: silent discovery failure would make the rest vacuous."""
        found = self._maintenance_methods()
        assert "vacuum_table" in found, f"discovery missed vacuum_table; found {sorted(found)}"
        assert "vacuum_freeze" in found, f"discovery missed vacuum_freeze; found {sorted(found)}"

    def test_each_maintenance_method_reports_a_refusal(self):
        offenders = []
        for name in self._maintenance_methods():
            if name in self.EXEMPT:
                continue
            db, mc, cur = _make_connected_db()
            _server_refuses_maintenance(mc, cur)

            method = getattr(db, name)
            required = [
                p for p in inspect.signature(method).parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
            ]
            try:
                result = method(*["x"] * len(required))
            except Exception:
                continue          # raising is an acceptable way not to lie
            if not result:
                offenders.append(
                    f"  {name}() returned {result!r} while the server was "
                    f"refusing maintenance"
                )
        assert not offenders, (
            "maintenance method(s) reported success for refused work:\n"
            + "\n".join(offenders)
        )

    def test_doctor_never_discards_a_maintenance_result(self):
        """
        The other half of the bug: core can report the refusal faithfully and
        the dialog can still throw it away, as it originally did.
        """
        path = _ROOT / "coruscant" / "ui" / "dialogs" / "doctor.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        maintenance = set(self._maintenance_methods())

        discarded = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            fn = node.value.func
            if isinstance(fn, ast.Attribute) and fn.attr in maintenance:
                discarded.append(f"  line {node.lineno}: {fn.attr}() result discarded")

        assert not discarded, (
            "doctor.py drops the return value of a maintenance call, so a "
            "reported refusal cannot reach the user:\n" + "\n".join(discarded)
        )
