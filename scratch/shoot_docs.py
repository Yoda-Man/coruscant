"""
scratch/shoot_docs.py
~~~~~~~~~~~~~~~~~~~~~
Capture the UI screenshots embedded in docs/USER_MANUAL.html.

Run against a throwaway PostgreSQL (see the docker command in the manual
regeneration notes).  QSettings is redirected to a temporary directory so the
developer's real query history, saved connections, and theme never appear in
shipped documentation.

    python scratch/shoot_docs.py

Windows render off-screen (moved to negative coordinates) so the desktop is
not disturbed; the real platform plugin is used because the "offscreen" one
ships no fonts and renders every glyph as a tofu box.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

OUT = _ROOT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)

DB = dict(host="127.0.0.1", port=55432, database="northwind",
          user="postgres", password="docshot", ssl_mode="prefer")

# ---------------------------------------------------------------- settings --
# The developer's real query history and saved connections live in the Windows
# registry under Coruscant/Coruscant.  QSettings.setDefaultFormat() does NOT
# reliably override that here (it silently stays on NativeFormat), so patch the
# class itself before any coruscant module does `from PySide6.QtCore import
# QSettings` and binds the name.  Every (org, app) construction is redirected
# to a throwaway INI file, guaranteeing no real data reaches the screenshots.
import PySide6.QtCore as _qtcore                          # noqa: E402
from PySide6.QtCore import Qt, QTimer, QPoint             # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="coruscant-docshot-"))
_INI = str(_TMP / "coruscant.ini")
_RealQSettings = _qtcore.QSettings


class _IsolatedQSettings(_RealQSettings):
    def __init__(self, *args, **kwargs):
        if len(args) == 2 and all(isinstance(a, str) for a in args):
            super().__init__(_INI, _RealQSettings.Format.IniFormat)
        else:
            super().__init__(*args, **kwargs)


_qtcore.QSettings = _IsolatedQSettings
QSettings = _IsolatedQSettings

_probe = QSettings("Coruscant", "Coruscant")
assert Path(_probe.fileName()) == Path(_INI), f"settings not isolated: {_probe.fileName()}"
assert _probe.value("query_history/entries") is None, "real history leaked into the sandbox"
print(f"settings isolated -> {_INI}")

from coruscant.app import create_app                      # noqa: E402
from coruscant.core.connections import SavedConnection, serialise_connections  # noqa: E402

app = create_app()

# Seed one saved profile so the connection manager is not empty on camera.
_s = QSettings("Coruscant", "Coruscant")
_s.setValue("connections/saved", serialise_connections([
    SavedConnection(name="Northwind (local)", group="Local", host="127.0.0.1",
                    port=55432, database="northwind", user="postgres",
                    password="docshot", ssl_mode="prefer"),
    SavedConnection(name="Reporting replica", group="Local", host="127.0.0.1",
                    port=55433, database="reporting", user="analyst",
                    password="", ssl_mode="require"),
]))
_s.sync()

from PySide6.QtWidgets import QApplication               # noqa: E402
from coruscant.ui.main_window import MainWindow          # noqa: E402

OFFSCREEN = QPoint(-4000, -4000)
shots: list[str] = []


def pump(n: int = 8) -> None:
    for _ in range(n):
        QApplication.processEvents()


def settle(widget, ms: int = 400) -> None:
    """Spin the event loop for `ms` so background threads can populate a view."""
    from PySide6.QtCore import QEventLoop, QElapsedTimer
    t = QElapsedTimer(); t.start()
    loop = QEventLoop()
    while t.elapsed() < ms:
        loop.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


def snap(widget, name: str, note: str = "") -> None:
    pump()
    pm = widget.grab()
    path = OUT / f"{name}.png"
    pm.save(str(path), "PNG")
    shots.append(name)
    print(f"  {name:<28} {pm.width():>5} x {pm.height():<5} {note}")


def show(widget, w: int | None = None, h: int | None = None):
    if w and h:
        widget.resize(w, h)
    widget.move(OFFSCREEN)
    widget.show()
    pump()
    return widget


# =============================================================== main window =
print("main window")
win = show(MainWindow(), 1560, 950)
win._db.connect(**DB)
win._current_connection_name = "Northwind (local)"
win._schema_browser.set_connected(True)
win.statusBar().showMessage("Connected to Northwind (local): northwind on 127.0.0.1:55432")
win._update_ui_state()
settle(win, 1500)                      # schema tree loads on a worker thread
pump()

ed = win._current_editor_tab()
ed.editor.setPlainText(
    "-- Orders per country, with freight totals\n"
    "SELECT ship_country,\n"
    "       count(*)            AS orders,\n"
    "       round(sum(freight)) AS total_freight\n"
    "FROM   orders\n"
    "GROUP  BY ship_country\n"
    "ORDER  BY orders DESC;\n\n"
    "SELECT product_name, unit_price, units_in_stock\n"
    "FROM   products\n"
    "WHERE  units_in_stock < 20\n"
    "ORDER  BY units_in_stock;\n"
)
pump()
snap(win, "ui-overview", "connected, schema loaded")

win._on_execute()
settle(win, 2500)
snap(win, "results-tabs", "two result tabs")


# ============================================================ cell viewer ===
print("dialogs")
from coruscant.ui.dialogs.cell_viewer import CellViewerDialog   # noqa: E402
_json = (
    '{\n  "order_id": 10248,\n  "customer": {\n    "company_name": "Alfreds Futterkiste",\n'
    '    "contact_name": "Maria Anders",\n    "country": "Germany"\n  },\n'
    '  "lines": [\n    { "product": "Chai",  "qty": 12, "unit_price": 18.00 },\n'
    '    { "product": "Tofu",  "qty":  5, "unit_price": 23.25 }\n  ],\n'
    '  "freight": 32.38,\n  "shipped": true\n}'
)
cv = show(CellViewerDialog(_json), 760, 470)
snap(cv, "cell-viewer", "JSON value, word wrap on")
cv.close()

# ======================================================= connection manager ==
from coruscant.ui.dialogs.connection import ConnectionDialog, SupabasePresetDialog  # noqa: E402
cd = show(ConnectionDialog(), 980, 640)
cd._host.setText("aws-0-eu-west-2.pooler.supabase.com")
cd._port.setValue(6543)
cd._database.setText("postgres")
cd._user.setText("postgres.abcdefghijklmnopqrst")
cd._name.setText("Supabase production")
cd._group.setText("Supabase")
cd._ssl_mode.setCurrentText("require")
pump()
snap(cd, "connection-pooler-warning", "transaction-pooler warning")

cd._host.setText("127.0.0.1"); cd._port.setValue(55432)
cd._name.setText("Northwind (local)"); cd._group.setText("Local")
cd._user.setText("postgres"); cd._ssl_mode.setCurrentText("prefer")
pump()
snap(cd, "connection-manager", "saved profiles")
cd.close()

sp = show(SupabasePresetDialog(), 470, 300)
sp._ref.setText("abcdefghijklmnopqrst")
sp._region.setCurrentText("eu-west-2")
pump()
snap(sp, "supabase-preset", "session pooler selected")
sp.close()

# ============================================================== guide/about ==
from coruscant.ui.dialogs.guide import ShortcutGuideDialog       # noqa: E402
gd = show(ShortcutGuideDialog(), 900, 660)
snap(gd, "guide", "quick-reference")
gd.close()


# ============================================================ query builder ==
print("db-backed dialogs")
from coruscant.ui.dialogs.query_builder import QueryBuilderDialog   # noqa: E402
_tables = next((s.get("tables", []) for s in win._schema_browser._tree_data
                if s.get("schema") == "public"), [])
qb = show(QueryBuilderDialog("public", _tables), 1180, 760)
pump()
# Base table "orders", then join "customers" so the FK is detected and the
# ON clause pre-fills with the auto-linked badge — the feature worth showing.
_i = qb._base_cb.findText("orders")
assert _i >= 0, "orders not in base table list"
qb._base_cb.setCurrentIndex(_i)
settle(qb, 400)

qb._add_join()
settle(qb, 300)
_row = qb._join_rows[-1]
_j = _row.table_cb.findText("customers")
assert _j >= 0, "customers not offered as a join target"
_row.table_cb.setCurrentIndex(_j)
settle(qb, 400)

# Tick a few output fields so the preview is a real statement, not SELECT *.
_tree = getattr(qb, "_fields_tree", None)
if _tree is not None:
    from PySide6.QtCore import Qt as _Qt
    _wanted = {"order_id", "order_date", "freight", "company_name", "country"}
    _it = __import__("PySide6.QtWidgets", fromlist=["QTreeWidgetItemIterator"]).QTreeWidgetItemIterator(_tree)
    while _it.value():
        _item = _it.value()
        if _item.text(0) in _wanted:
            _item.setCheckState(0, _Qt.CheckState.Checked)
        _it += 1
settle(qb, 500)
snap(qb, "query-builder", "orders + FK-linked join")
qb.close()

# ================================================================ QA engine ==
from coruscant.core.qa_engine import run_qa                          # noqa: E402
from coruscant.ui.dialogs.qa_dialog import QADialog                  # noqa: E402
_report = run_qa(win._db._conn, "public")   # run_qa takes the raw psycopg2 connection
qa = show(QADialog(_report), 1120, 720)
# Select the first finding that carries a fix script so the Fix SQL pane shows
# the generated CREATE INDEX CONCURRENTLY rather than the empty placeholder.
_top = qa._tree.topLevelItem(0)
if _top is not None and _top.childCount():
    _top.setExpanded(True)
    qa._tree.setCurrentItem(_top.child(0))
settle(qa, 400)
snap(qa, "qa-engine", f"health {_report.health_score}, fix SQL shown")
qa.close()

# =========================================================== database doctor =
from coruscant.ui.dialogs.doctor import DatabaseDoctorDialog         # noqa: E402
doc = show(DatabaseDoctorDialog(win._db), 1120, 780)
settle(doc, 3000)
snap(doc, "database-doctor", "four health cards")
doc.close()

# ========================================================== live monitor ====
from coruscant.ui.dialogs.dashboard import DashboardDialog           # noqa: E402
dash = show(DashboardDialog(win._db), 1400, 880)
settle(dash, 2500)
# Per-second rates are deltas between consecutive samples, so a single refresh
# leaves them showing "collecting...".  Generate a little load, then refresh
# again so the gauges and sparklines have real numbers on camera.
import psycopg2                                                      # noqa: E402
_load = psycopg2.connect(host=DB["host"], port=DB["port"], dbname=DB["database"],
                         user=DB["user"], password=DB["password"])
_load.autocommit = True
_lc = _load.cursor()
for _ in range(150):
    _lc.execute("SELECT count(*) FROM order_details od JOIN orders o USING (order_id)")
    _lc.fetchall()
settle(dash, 500)
dash._refresh()
settle(dash, 2500)
for _ in range(150):
    _lc.execute("SELECT ship_country, sum(freight) FROM orders GROUP BY 1")
    _lc.fetchall()
dash._refresh()
settle(dash, 2000)
# The Tables tab has real content; Activity is empty on an idle server.
_ti = next((i for i in range(dash._tabs.count()) if "Tables" in dash._tabs.tabText(i)), 0)
dash._tabs.setCurrentIndex(_ti)
settle(dash, 800)
snap(dash, "live-monitor", "KPI gauges + Tables tab")
_load.close()
dash.close()

# ============================================================== recovery ====
from coruscant.ui.dialogs.recovery import RecoveryDialog             # noqa: E402
rec = show(RecoveryDialog(win._db), 900, 620)
settle(rec, 1500)
snap(rec, "recovery-primary", "primary server state")
rec.close()

print(f"\n{len(shots)} screenshots -> {OUT}")
win._db.disconnect()
shutil.rmtree(_TMP, ignore_errors=True)
