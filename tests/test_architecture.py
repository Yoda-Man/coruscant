"""
Architectural constraints, enforced.

Coruscant's layering is its main design asset: `core/` and `utils/` know
nothing about the UI, and the UI never talks to the database driver directly.
That was true by convention and drifted anyway —

  * `ui/dialogs/connection.py` imported psycopg2 and opened its own connection
    for Test Connection, so that button bypassed every change made centrally
    and had drifted to its own connect timeout.
  * `utils/logging_config.py` imported a dialog from `ui/`, inverting the
    dependency it sits below.
  * `LOCKS_SQL` existed in both `core/doctor.py` and `core/metrics.py` with
    different text — one concept, two spellings, already diverged.

A README claiming a rule is not the same as a rule. These tests are the rule.
They read source with `ast`, so they need neither PySide6 nor a database.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PKG = _ROOT / "coruscant"


def _modules(*subdirs: str) -> list[Path]:
    out: list[Path] = []
    for sub in subdirs:
        out.extend(
            p for p in (_PKG / sub).rglob("*.py")
            if "__pycache__" not in p.parts
        )
    return sorted(out)


def _imported_names(path: Path) -> set[str]:
    """Every module named by an import in this file, including local imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _rel(path: Path) -> str:
    return path.relative_to(_ROOT).as_posix()


# ---------------------------------------------------------------------------
# Layering
# ---------------------------------------------------------------------------

class TestDependenciesPointInward:
    def test_core_and_utils_never_import_the_ui(self):
        """
        The lower layers must stay independently testable and importable before
        any GUI exists. Where the UI genuinely has to be involved — presenting a
        crash dialog — it registers a callback instead
        (logging_config.set_crash_reporter).
        """
        offenders = []
        for path in _modules("core", "utils"):
            for name in _imported_names(path):
                if name.startswith("coruscant.ui"):
                    offenders.append(f"  {_rel(path)} imports {name}")
        assert not offenders, (
            "lower layers must not depend on the UI:\n" + "\n".join(offenders)
        )

    def test_ui_never_talks_to_the_database_driver(self):
        """
        Every connection must go through DatabaseManager, so behaviour added
        there — timeouts, logging, reconnect, ownership checks — applies
        everywhere rather than to whichever call sites remembered.
        """
        offenders = []
        for path in _modules("ui"):
            for name in _imported_names(path):
                if name == "psycopg2" or name.startswith("psycopg2."):
                    offenders.append(f"  {_rel(path)} imports {name}")
        assert not offenders, (
            "the UI must reach the database only through core.database:\n"
            + "\n".join(offenders)
        )

    def test_only_the_designated_module_imports_the_driver(self):
        """psycopg2 belongs to core.database and nowhere else."""
        allowed = {"coruscant/core/database.py"}
        offenders = []
        for path in _modules("core", "utils", "ui"):
            rel = _rel(path).replace("coruscant/", "", 1)
            full = f"coruscant/{rel}"
            if full in allowed:
                continue
            for name in _imported_names(path):
                if name == "psycopg2" or name.startswith("psycopg2."):
                    offenders.append(f"  {full} imports {name}")
        assert not offenders, (
            "psycopg2 should be confined to core/database.py:\n" + "\n".join(offenders)
        )


class TestCoreStaysHeadless:
    """
    `core/` is testable without a running Qt application. worker.py is the one
    deliberate exception — it *is* a QThread — and is named here so the
    exception stays visible instead of quietly becoming the rule.
    """

    QT_EXEMPT = {"coruscant/core/worker.py"}

    def test_core_modules_do_not_import_qt(self):
        offenders = []
        for path in _modules("core"):
            if _rel(path) in self.QT_EXEMPT:
                continue
            for name in _imported_names(path):
                if name.startswith("PySide6"):
                    offenders.append(f"  {_rel(path)} imports {name}")
        assert not offenders, (
            "core/ must stay importable without Qt (add to QT_EXEMPT only with "
            "a reason):\n" + "\n".join(offenders)
        )

    def test_the_qt_exemption_is_still_real(self):
        """Guards the guard: a stale exemption silently weakens the rule."""
        for rel in self.QT_EXEMPT:
            path = _ROOT / rel
            assert path.exists(), f"exempt module no longer exists: {rel}"
            assert any(n.startswith("PySide6") for n in _imported_names(path)), (
                f"{rel} no longer imports Qt — remove it from QT_EXEMPT"
            )


# ---------------------------------------------------------------------------
# One concept, one definition
# ---------------------------------------------------------------------------

def test_no_sql_constant_is_defined_twice():
    """
    A query defined in two modules will drift, and the copy nobody exercises is
    where a bad column name survives. LOCKS_SQL had already diverged between
    doctor.py and metrics.py before this test existed.
    """
    seen: dict[str, list[str]] = {}
    for path in _modules("core"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:                       # module level only
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and target.id.endswith("_SQL")
                        and isinstance(node.value, ast.Constant)):
                    seen.setdefault(target.id, []).append(_rel(path))

    dupes = {name: files for name, files in seen.items() if len(files) > 1}
    assert not dupes, (
        "SQL constant defined in more than one module — define it once and "
        f"import it:\n" + "\n".join(f"  {n}: {', '.join(f)}" for n, f in dupes.items())
    )


def test_sql_constants_were_actually_found():
    """Guards the guard: an empty scan would make the duplicate check vacuous."""
    found = []
    for path in _modules("core"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found += [
            t.id for node in tree.body if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Name) and t.id.endswith("_SQL")
        ]
    assert "BLOAT_SQL" in found, f"scan missed BLOAT_SQL; found {sorted(set(found))}"
