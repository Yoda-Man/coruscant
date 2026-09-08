"""
Shared pytest setup.

tests/test_database.py installs a psycopg2 stub so the mocked database tests
run on a machine without the driver. It does so with
``sys.modules.setdefault("psycopg2", stub)`` — which checks whether psycopg2
has been *imported*, not whether it is installed. So even where the real
driver is present, whichever module imports first wins, and test_database
sorts ahead of test_live_sql.

That silently handed the live SQL tests a MagicMock instead of a real driver:
every "connection" succeeded, every query "ran", and nothing was actually
executed against PostgreSQL — the precise blind spot those tests exist to
close.

Importing the real driver here, before any test module is collected, makes the
stub the fallback it was meant to be: used only when psycopg2 genuinely is not
installed.
"""
from __future__ import annotations

try:  # pragma: no cover - trivial
    import psycopg2  # noqa: F401
except ImportError:
    # No driver installed. test_database.py's stub will take over, and
    # tests/test_live_sql.py skips itself for want of a server anyway.
    pass
