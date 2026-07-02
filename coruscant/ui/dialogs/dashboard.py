"""
coruscant.ui.dialogs.dashboard
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Live Database Monitoring Dashboard.

A single, information-dense window that samples the connected PostgreSQL
server on a timer and renders it as:

  • a strip of KPI gauges (size, connections, cache-hit, TPS, uptime …)
  • live sparklines (transactions/sec, connections, cache-hit %, rows/sec)
  • a tabbed detail area (activity, connections, tables, indexes, cache,
    databases, locks, replication, top statements, settings)

All sampling runs on a background QThread so the UI never blocks, and the
whole thing auto-refreshes at a user-selectable interval.  No business
logic lives here — every SQL string comes from ``coruscant.core.metrics``.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import sys
import time
import logging
from collections import deque
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QWidget, QFrame, QTableWidget, QTableWidgetItem, QTabWidget,
    QComboBox, QCheckBox, QSizePolicy, QAbstractItemView, QHeaderView,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF, QPointF
from PySide6.QtGui import (
    QFont, QPixmap, QColor, QPainter, QPainterPath, QLinearGradient, QPen,
)

from coruscant.core.database import DatabaseManager, QueryResult
import coruscant.core.metrics as _m

log = logging.getLogger(__name__)

_BASE = (
    Path(sys._MEIPASS)                     # type: ignore[attr-defined]
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[3]
)
_BANNER_PATH = str(_BASE / "docs" / "coruscant3.png")

# ── Palette (Catppuccin Mocha, matching Database Doctor) ───────────── #
BG        = "#12121e"
PANEL     = "#1e1e2e"
PANEL2    = "#181825"
BORDER    = "#313244"
TEXT      = "#cdd6f4"
SUBTEXT   = "#a6adc8"
MUTED     = "#6c7086"
BLUE      = "#89b4fa"
GREEN     = "#a6e3a1"
YELLOW    = "#f9e2af"
PEACH     = "#fab387"
RED       = "#f38ba8"
MAUVE     = "#cba6f7"
TEAL      = "#94e2d5"
SKY       = "#74c7ec"

_HISTORY = 80   # rolling sparkline sample count

_STYLE = f"""
QDialog {{ background: {BG}; }}
QLabel  {{ color: {TEXT}; background: transparent; }}

QFrame#kpi {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: {PANEL2};
    top: -1px;
}}
QTabBar::tab {{
    background: {PANEL2};
    color: {SUBTEXT};
    padding: 6px 14px;
    margin-right: 2px;
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    font-size: 11px; font-weight: 600;
}}
QTabBar::tab:selected {{ background: {PANEL}; color: {BLUE}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}

QTableWidget {{
    background: {PANEL2}; color: {TEXT};
    border: none; border-radius: 4px;
    font-size: 11px; gridline-color: #252535;
    selection-background-color: {BORDER};
    selection-color: {TEXT};
    alternate-background-color: #1c1c2b;
}}
QHeaderView::section {{
    background: #252535; color: {BLUE};
    padding: 5px 8px; border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    font-size: 11px; font-weight: 700;
}}
QTableWidget::item {{ padding: 3px 8px; }}

QComboBox {{
    background: {PANEL2}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 4px;
    padding: 3px 22px 3px 8px; font-size: 11px; min-width: 70px;
}}
QComboBox:hover {{ border-color: {BLUE}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {SUBTEXT};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {PANEL2}; color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {BORDER};
    outline: none;
}}

QCheckBox {{ color: {SUBTEXT}; font-size: 11px; spacing: 6px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {BORDER}; background: {PANEL2};
}}
QCheckBox::indicator:checked {{
    background: {GREEN}; border-color: {GREEN};
}}

QScrollBar:vertical {{ background: {BG}; width: 9px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #45475a; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #585b70; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: {BG}; height: 9px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #45475a; border-radius: 4px; min-width: 24px; }}

QPushButton#refresh_btn {{
    background: #1565C0; color: #fff; border: none;
    border-radius: 5px; padding: 6px 18px;
    font-size: 12px; font-weight: 700;
}}
QPushButton#refresh_btn:hover   {{ background: #1976D2; }}
QPushButton#refresh_btn:pressed {{ background: #0D47A1; }}
QPushButton#refresh_btn:disabled {{ background: #1a1a2a; color: #555; }}

QPushButton#close_btn {{
    background: transparent; color: {SUBTEXT};
    border: 1px solid #444; border-radius: 5px;
    padding: 6px 18px; font-size: 12px;
}}
QPushButton#close_btn:hover {{ color: {TEXT}; border-color: #666; }}
"""


# ==================================================================== #
#  Sparkline — a lightweight QPainter line chart (no extra deps)         #
# ==================================================================== #

class Sparkline(QWidget):
    """
    Compact rolling line chart drawn with QPainter.

    Feed it values via :meth:`push`; it keeps the last ``_HISTORY`` points
    and paints a gradient-filled trend line with the current value and
    min/max overlaid.  Deliberately dependency-free so the dashboard needs
    nothing beyond base PySide6.
    """

    def __init__(self, title: str, color: str, unit: str = "",
                 as_percent: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._color = QColor(color)
        self._unit = unit
        self._as_percent = as_percent
        self._data: deque[float] = deque(maxlen=_HISTORY)
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def push(self, value: float) -> None:
        self._data.append(float(value))
        self.update()

    def clear(self) -> None:
        self._data.clear()
        self.update()

    def _fmt(self, v: float) -> str:
        if self._as_percent:
            return f"{v:.1f}%"
        return _m.fmt_count(v) + self._unit

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        # Card background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(PANEL))
        p.drawRoundedRect(0, 0, w, h, 8, 8)
        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)

        # Title (top-left) and current value (top-right)
        p.setPen(QColor(SUBTEXT))
        f = QFont(); f.setPointSize(8); f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, 6, w - 20, 14),
                   Qt.AlignmentFlag.AlignLeft, self._title.upper())

        current = self._data[-1] if self._data else 0.0
        p.setPen(self._color)
        vf = QFont(); vf.setPointSize(13); vf.setBold(True)
        p.setFont(vf)
        p.drawText(QRectF(10, 18, w - 20, 20),
                   Qt.AlignmentFlag.AlignLeft, self._fmt(current))

        if len(self._data) < 2:
            p.setPen(QColor(MUTED))
            sf = QFont(); sf.setPointSize(8)
            p.setFont(sf)
            p.drawText(QRectF(0, h - 24, w, 16),
                       Qt.AlignmentFlag.AlignCenter, "collecting…")
            p.end()
            return

        # Plot area
        pad_l, pad_r, pad_t, pad_b = 10, 10, 42, 12
        gw = max(1, w - pad_l - pad_r)
        gh = max(1, h - pad_t - pad_b)

        data = list(self._data)
        lo = min(data)
        hi = max(data)
        if self._as_percent:
            # For percentages, anchor scale around the data with headroom
            lo = min(lo, hi - 1.0)
        rng = (hi - lo) or 1.0
        n = len(data)

        def pt(i: int, v: float) -> QPointF:
            x = pad_l + gw * (i / (n - 1))
            y = pad_t + gh * (1.0 - (v - lo) / rng)
            return QPointF(x, y)

        # Filled area under the curve
        area = QPainterPath()
        area.moveTo(pad_l, pad_t + gh)
        for i, v in enumerate(data):
            area.lineTo(pt(i, v))
        area.lineTo(pad_l + gw, pad_t + gh)
        area.closeSubpath()

        grad = QLinearGradient(0, pad_t, 0, pad_t + gh)
        fill = QColor(self._color); fill.setAlpha(70)
        grad.setColorAt(0.0, fill)
        fill2 = QColor(self._color); fill2.setAlpha(0)
        grad.setColorAt(1.0, fill2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawPath(area)

        # Trend line
        line = QPainterPath()
        line.moveTo(pt(0, data[0]))
        for i, v in enumerate(data[1:], start=1):
            line.lineTo(pt(i, v))
        p.setPen(QPen(self._color, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(line)

        # Endpoint dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        end = pt(n - 1, data[-1])
        p.drawEllipse(end, 2.6, 2.6)

        # Min / max labels
        p.setPen(QColor(MUTED))
        mf = QFont(); mf.setPointSize(7)
        p.setFont(mf)
        p.drawText(QRectF(pad_l, pad_t - 2, gw, 10),
                   Qt.AlignmentFlag.AlignRight, f"max {self._fmt(hi)}")
        p.drawText(QRectF(pad_l, pad_t + gh - 9, gw, 10),
                   Qt.AlignmentFlag.AlignRight, f"min {self._fmt(lo)}")
        p.end()


# ==================================================================== #
#  KPI card                                                              #
# ==================================================================== #

class _Kpi:
    """Holds the widgets of one KPI gauge so the dialog can update it."""
    __slots__ = ("frame", "value_lbl", "sub_lbl", "title")

    def __init__(self, frame: QFrame, value_lbl: QLabel,
                 sub_lbl: QLabel, title: str) -> None:
        self.frame = frame
        self.value_lbl = value_lbl
        self.sub_lbl = sub_lbl
        self.title = title

    def set(self, value: str, sub: str = "", color: str = TEXT) -> None:
        self.value_lbl.setText(value)
        self.value_lbl.setStyleSheet(
            f"color: {color}; font-size: 22px; font-weight: 800;"
            " background: transparent;"
        )
        if sub:
            self.sub_lbl.setText(sub)


# ==================================================================== #
#  Background sampling worker                                            #
# ==================================================================== #

class _MetricWorker(QThread):
    """Runs every dashboard query off the UI thread and emits a payload."""

    finished: Signal = Signal(dict)
    failed:   Signal = Signal(str)

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db = db

    def _one(self, sql: str) -> tuple[list[str], list[tuple]] | tuple[str, str]:
        """Run a single query; return (columns, rows) or ('__error__', msg)."""
        try:
            res = self._db.execute(sql)
            if res and isinstance(res[0], QueryResult):
                return res[0].columns, res[0].rows
            return [], []
        except Exception as exc:  # noqa: BLE001
            return "__error__", str(exc).strip().splitlines()[0]

    def run(self) -> None:
        payload: dict[str, Any] = {}

        # ── Instant gauges ──────────────────────────────────────────── #
        g_cols, g_rows = ([], [])
        try:
            gres = self._db.execute(_m.GLOBAL_SQL)
            if gres and isinstance(gres[0], QueryResult):
                g_cols, g_rows = gres[0].columns, gres[0].rows
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc).strip().splitlines()[0])
            return

        payload["global"] = (
            dict(zip(g_cols, g_rows[0])) if g_rows else {}
        )

        dres = self._one(_m.DBSTATS_SQL)
        if isinstance(dres[0], list) and dres[1]:
            payload["dbstats"] = _m.dbstats_to_dict(dres[1][0])
        else:
            payload["dbstats"] = None

        # ── Detail tables (+ optional pg_stat_statements) ───────────── #
        details: dict[str, Any] = {}
        queries = dict(_m.DETAIL_QUERIES)
        queries["statements"] = _m.STATEMENTS_SQL
        for key, sql in queries.items():
            details[key] = self._one(sql)
        payload["details"] = details

        self.finished.emit(payload)


# ==================================================================== #
#  Main dialog                                                          #
# ==================================================================== #

class DashboardDialog(QDialog):
    """Live database monitoring dashboard."""

    # (tab title, [(section label | None, detail-query key)])
    _TAB_SPEC = [
        ("⚡ Activity",     [(None, "activity")]),
        ("🔌 Connections",  [("By state", "conn_state"),
                             ("By user · application · client", "conn_user")]),
        ("📊 Tables",       [(None, "tables")]),
        ("🔍 Indexes",      [(None, "indexes")]),
        ("💾 Cache",        [(None, "table_cache")]),
        ("🗄 Databases",    [(None, "databases")]),
        ("🔒 Locks",        [(None, "locks")]),
        ("🔁 Replication",  [(None, "replication")]),
        ("🐢 Top Queries",  [(None, "statements")]),
        ("⚙ Settings",      [(None, "settings")]),
    ]

    # Empty-state note per key when a query returns no rows.
    _EMPTY_NOTE = {
        "locks":       "✔  No lock contention — nothing is blocked.",
        "replication": "No streaming standbys connected to this server.",
        "activity":    "✔  No active or in-transaction sessions right now.",
        "statements":  "pg_stat_statements is not enabled on this server.\n"
                       "Enable it (shared_preload_libraries) for per-query timing.",
    }

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._worker: _MetricWorker | None = None

        # Rolling state
        self._prev_dbstats: dict[str, Any] | None = None
        self._last_sample_t: float | None = None
        self._kpis: dict[str, _Kpi] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._notes: dict[str, QLabel] = {}
        self._refresh_count = 0

        self.setWindowTitle("Database Monitor")
        self.setMinimumSize(1040, 720)
        self.resize(1180, 820)
        self.setModal(False)
        self.setStyleSheet(_STYLE)

        self._build_ui()

        # Auto-refresh timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._apply_interval()

        self._refresh()   # first sample immediately

    # ---------------------------------------------------------------- #
    #  UI construction                                                   #
    # ---------------------------------------------------------------- #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(self._build_banner())
        root.addWidget(self._build_header_strip())
        root.addWidget(self._build_control_bar())

        body = QWidget()
        body.setStyleSheet(f"background: {BG};")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(14, 12, 14, 8)
        body_lay.setSpacing(12)

        body_lay.addWidget(self._build_kpi_grid())
        body_lay.addWidget(self._build_sparkline_row())
        body_lay.addWidget(self._build_tabs(), stretch=1)

        root.addWidget(body, stretch=1)
        root.addWidget(self._build_footer())

    def _build_banner(self) -> QWidget:
        banner = QLabel()
        banner.setFixedHeight(72)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet("background: #0d0d1a;")
        pix = QPixmap(_BANNER_PATH)
        if not pix.isNull():
            banner.setPixmap(
                pix.scaledToHeight(72, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            banner.setText("✦  Coruscant  ✦")
            f = QFont(); f.setPointSize(13); f.setBold(True)
            banner.setFont(f)
            banner.setStyleSheet(f"background: #0d0d1a; color: {BLUE};")
        return banner

    def _build_header_strip(self) -> QWidget:
        strip = QWidget()
        strip.setFixedHeight(48)
        strip.setStyleSheet(
            f"background: #0d1a2e; border-top: 1px solid #1565C0;"
            f" border-bottom: 1px solid #1565C0;"
        )
        row = QHBoxLayout(strip)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)

        icon = QLabel("📊")
        icon.setStyleSheet("font-size: 18px; background: transparent;")
        row.addWidget(icon)

        title = QLabel("Database Monitor")
        title.setStyleSheet(
            f"color: {BLUE}; font-size: 14px; font-weight: 700;"
            " letter-spacing: 0.5px; background: transparent;"
        )
        row.addWidget(title)

        self._live_dot = QLabel("●")
        self._live_dot.setStyleSheet(
            f"color: {GREEN}; font-size: 12px; background: transparent;"
        )
        row.addWidget(self._live_dot)

        self._server_lbl = QLabel("")
        self._server_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 11px; background: transparent;"
        )
        row.addWidget(self._server_lbl)

        row.addStretch()

        self._status_lbl = QLabel("Connecting…")
        self._status_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 11px; background: transparent;"
        )
        row.addWidget(self._status_lbl)
        return strip

    def _build_control_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background: #161626; border-bottom: 1px solid #252535;")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(12)

        self._refresh_btn = QPushButton("🔄  Refresh")
        self._refresh_btn.setObjectName("refresh_btn")
        self._refresh_btn.clicked.connect(self._refresh)
        row.addWidget(self._refresh_btn)

        self._auto_chk = QCheckBox("Auto-refresh")
        self._auto_chk.setChecked(True)
        self._auto_chk.toggled.connect(self._on_auto_toggled)
        row.addWidget(self._auto_chk)

        every = QLabel("every")
        every.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        row.addWidget(every)

        self._interval_combo = QComboBox()
        for label, ms in (("2s", 2000), ("5s", 5000),
                          ("10s", 10000), ("30s", 30000), ("60s", 60000)):
            self._interval_combo.addItem(label, ms)
        self._interval_combo.setCurrentIndex(1)   # 5s default
        self._interval_combo.currentIndexChanged.connect(self._apply_interval)
        row.addWidget(self._interval_combo)

        row.addStretch()

        self._updated_lbl = QLabel("")
        self._updated_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        row.addWidget(self._updated_lbl)
        return bar

    def _build_kpi_grid(self) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        specs = [
            ("db_size",     "Database Size"),
            ("connections", "Connections"),
            ("cache",       "Cache Hit"),
            ("tps",         "Transactions/s"),
            ("active",      "Active Queries"),
            ("uptime",      "Uptime"),
            ("writes",      "Row Writes/s"),
            ("reads",       "Rows Read/s"),
            ("locks",       "Blocked / Locks"),
            ("health",      "Commit Ratio"),
        ]
        cols = 5
        for i, (key, title) in enumerate(specs):
            card = self._make_kpi(key, title)
            grid.addWidget(card, i // cols, i % cols)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        return wrap

    def _make_kpi(self, key: str, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("kpi")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        frame.setMinimumHeight(78)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(1)

        title_lbl = QLabel(title.upper())
        title_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 9px; font-weight: 700;"
            " letter-spacing: 0.6px; background: transparent;"
        )
        lay.addWidget(title_lbl)

        value_lbl = QLabel("—")
        value_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 22px; font-weight: 800;"
            " background: transparent;"
        )
        lay.addWidget(value_lbl)

        sub_lbl = QLabel("")
        sub_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; background: transparent;"
        )
        sub_lbl.setWordWrap(False)
        lay.addWidget(sub_lbl)

        self._kpis[key] = _Kpi(frame, value_lbl, sub_lbl, title)
        return frame

    def _build_sparkline_row(self) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self._spark_tps   = Sparkline("Transactions / sec", GREEN)
        self._spark_conn  = Sparkline("Connections", SKY)
        self._spark_cache = Sparkline("Cache hit %", MAUVE, as_percent=True)
        self._spark_rows  = Sparkline("Rows returned / sec", PEACH)
        for s in (self._spark_tps, self._spark_conn,
                  self._spark_cache, self._spark_rows):
            row.addWidget(s)
        return wrap

    def _build_tabs(self) -> QWidget:
        self._tabs = QTabWidget()
        for title, sections in self._TAB_SPEC:
            page = QWidget()
            page.setStyleSheet("background: transparent;")
            v = QVBoxLayout(page)
            v.setContentsMargins(8, 8, 8, 8)
            v.setSpacing(6)
            for label, key in sections:
                if label:
                    hdr = QLabel(label)
                    hdr.setStyleSheet(
                        f"color: {BLUE}; font-size: 11px; font-weight: 700;"
                        " padding: 2px; background: transparent;"
                    )
                    v.addWidget(hdr)

                note = QLabel("")
                note.setStyleSheet(
                    f"color: {MUTED}; font-size: 12px; padding: 10px;"
                    " background: transparent;"
                )
                note.setWordWrap(True)
                note.hide()
                v.addWidget(note)
                self._notes[key] = note

                table = QTableWidget(0, 0)
                table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                table.setAlternatingRowColors(True)
                table.verticalHeader().setVisible(False)
                table.horizontalHeader().setStretchLastSection(True)
                table.horizontalHeader().setHighlightSections(False)
                if len(sections) > 1:
                    table.setMaximumHeight(150)
                v.addWidget(table, stretch=1)
                self._tables[key] = table
            self._tabs.addTab(page, title)
        return self._tabs

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setStyleSheet("background: #0e0e1c; border-top: 1px solid #252535;")
        row = QHBoxLayout(footer)
        row.setContentsMargins(16, 8, 16, 10)

        hint = QLabel("Live metrics sampled from pg_stat_* views. "
                      "Rates are per-second deltas between refreshes.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
        row.addWidget(hint)
        row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("close_btn")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        return footer

    # ---------------------------------------------------------------- #
    #  Refresh cycle                                                     #
    # ---------------------------------------------------------------- #

    def _apply_interval(self) -> None:
        ms = self._interval_combo.currentData()
        if self._auto_chk.isChecked():
            self._timer.start(int(ms))
        else:
            self._timer.stop()

    def _on_auto_toggled(self, on: bool) -> None:
        self._live_dot.setStyleSheet(
            f"color: {GREEN if on else MUTED}; font-size: 12px;"
            " background: transparent;"
        )
        self._apply_interval()

    def _refresh(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._status_lbl.setText("Refreshing…")
        self._worker = _MetricWorker(self._db, self)
        self._worker.finished.connect(self._on_metrics)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_failed(self, msg: str) -> None:
        self._status_lbl.setText(f"⚠ {msg}")
        self._live_dot.setStyleSheet(
            f"color: {RED}; font-size: 12px; background: transparent;"
        )

    def _on_metrics(self, payload: dict) -> None:
        now = time.monotonic()
        g = payload.get("global", {}) or {}
        dbstats = payload.get("dbstats")

        # Rates from consecutive dbstats samples
        dt = (now - self._last_sample_t) if self._last_sample_t else 0.0
        rates = _m.compute_rates(self._prev_dbstats, dbstats or {}, dt) \
            if dbstats else _m.Rates()
        self._prev_dbstats = dbstats
        self._last_sample_t = now
        self._refresh_count += 1

        self._update_kpis(g, dbstats or {}, rates)
        self._update_sparklines(g, rates)
        self._update_details(payload.get("details", {}))

        # Header + footer status
        ver = str(g.get("version", "")).split(" on ")[0].replace("PostgreSQL", "PG")
        dbname = g.get("database", "?")
        role = "standby" if g.get("in_recovery") else "primary"
        self._server_lbl.setText(f"{dbname}  ·  {ver.strip()}  ·  {role}")
        self._status_lbl.setText(f"Live  ·  {self._refresh_count} refresh(es)")
        if not (self._auto_chk.isChecked()):
            self._status_lbl.setText(f"Paused  ·  {self._refresh_count} refresh(es)")
        self._updated_lbl.setText("Updated " + time.strftime("%H:%M:%S"))
        self._live_dot.setStyleSheet(
            f"color: {GREEN if self._auto_chk.isChecked() else MUTED};"
            f" font-size: 12px; background: transparent;"
        )

    # ---------------------------------------------------------------- #
    #  KPI + sparkline updates                                           #
    # ---------------------------------------------------------------- #

    def _update_kpis(self, g: dict, db: dict, r: _m.Rates) -> None:
        def gi(key, default=0):
            try:
                return int(g.get(key) or default)
            except (TypeError, ValueError):
                return default

        # Database size
        self._kpis["db_size"].set(
            str(g.get("db_size", "—")),
            f"{g.get('database', '')}", BLUE,
        )

        # Connections
        total = gi("total_conn")
        maxc = gi("max_conn", 1) or 1
        active = gi("active_conn")
        idle = gi("idle_conn")
        idle_txn = gi("idle_txn_conn")
        pct = 100.0 * total / maxc
        conn_color = RED if pct >= 85 else YELLOW if pct >= 70 else GREEN
        self._kpis["connections"].set(
            f"{total}/{maxc}",
            f"{pct:.0f}% used · idle {idle} · in-txn {idle_txn}", conn_color,
        )

        # Cache hit — prefer interval rate, fall back to lifetime
        if r.valid and (r.blocks_hit + r.blocks_read) > 0:
            hit = r.interval_cache_hit
        else:
            try:
                hit = float(db.get("cache_hit_pct") or 100.0)
            except (TypeError, ValueError):
                hit = 100.0
        cache_color = GREEN if hit >= 99 else YELLOW if hit >= 90 else RED
        self._kpis["cache"].set(
            f"{hit:.1f}%",
            "buffer cache efficiency", cache_color,
        )

        # TPS
        tps_txt = _m.fmt_count(r.tps) if r.valid else "…"
        self._kpis["tps"].set(
            tps_txt,
            f"commit {_m.fmt_count(r.commits)}/s · rollback {_m.fmt_count(r.rollbacks)}/s"
            if r.valid else "collecting…", GREEN,
        )

        # Active queries
        longest = gi("longest_query_secs")
        self._kpis["active"].set(
            str(active),
            f"longest {_m.fmt_duration(longest)}" if active else "idle",
            PEACH if active > 0 else SUBTEXT,
        )

        # Uptime
        self._kpis["uptime"].set(
            _m.fmt_duration(gi("uptime_secs")),
            f"since {str(g.get('start_time',''))[:16]}", TEAL,
        )

        # Row writes / reads per sec
        writes = r.rows_inserted + r.rows_updated + r.rows_deleted
        self._kpis["writes"].set(
            _m.fmt_count(writes) if r.valid else "…",
            f"ins {_m.fmt_count(r.rows_inserted)} · upd {_m.fmt_count(r.rows_updated)}"
            f" · del {_m.fmt_count(r.rows_deleted)}" if r.valid else "collecting…",
            SKY,
        )
        self._kpis["reads"].set(
            _m.fmt_count(r.rows_returned) if r.valid else "…",
            f"fetched {_m.fmt_count(r.rows_fetched)}/s" if r.valid else "collecting…",
            SKY,
        )

        # Blocked / locks
        blocked = gi("blocked_conn")
        waiting = gi("waiting_conn")
        lock_color = RED if blocked > 0 else GREEN
        self._kpis["locks"].set(
            str(blocked),
            f"waiting on lock: {waiting}", lock_color,
        )

        # Commit ratio (health)
        try:
            commits = float(db.get("xact_commit") or 0)
            rollbacks = float(db.get("xact_rollback") or 0)
            ratio = 100.0 * commits / (commits + rollbacks) if (commits + rollbacks) else 100.0
        except (TypeError, ValueError):
            ratio = 100.0
        ratio_color = GREEN if ratio >= 98 else YELLOW if ratio >= 90 else RED
        deadlocks = int(db.get("deadlocks") or 0)
        self._kpis["health"].set(
            f"{ratio:.1f}%",
            f"deadlocks: {deadlocks}", ratio_color,
        )

    def _update_sparklines(self, g: dict, r: _m.Rates) -> None:
        try:
            total = int(g.get("total_conn") or 0)
        except (TypeError, ValueError):
            total = 0
        self._spark_conn.push(total)
        if r.valid:
            self._spark_tps.push(r.tps)
            self._spark_cache.push(r.interval_cache_hit)
            self._spark_rows.push(r.rows_returned)

    # ---------------------------------------------------------------- #
    #  Detail table updates                                              #
    # ---------------------------------------------------------------- #

    def _update_details(self, details: dict) -> None:
        for key, table in self._tables.items():
            data = details.get(key)
            note = self._notes.get(key)
            if not data:
                continue

            cols, rows = data
            # Error from the query itself
            if cols == "__error__":
                table.hide()
                if note:
                    note.setText(f"⚠  {rows}")
                    note.show()
                continue

            if not rows:
                table.hide()
                if note:
                    note.setText(self._EMPTY_NOTE.get(key, "No data."))
                    note.show()
                continue

            if note:
                note.hide()
            table.show()
            self._fill_table(table, cols, rows)

    @staticmethod
    def _fill_table(table: QTableWidget, cols: list[str], rows: list[tuple]) -> None:
        # Preserve current selection/scroll feel by only rebuilding contents
        table.setUpdatesEnabled(False)
        table.clear()
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels([c.replace("_", " ").title() for c in cols])
        table.setRowCount(len(rows))
        for rix, row in enumerate(rows):
            for cix, val in enumerate(row):
                text = "" if val is None else str(val)
                item = QTableWidgetItem(text)
                # Right-align numeric-looking values
                stripped = text.replace(",", "").replace(".", "").replace("-", "").replace("%", "")
                if stripped.isdigit():
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                table.setItem(rix, cix, item)
        table.resizeColumnsToContents()
        # Cap very wide (query text) columns
        hdr = table.horizontalHeader()
        for c in range(table.columnCount()):
            if table.columnWidth(c) > 460:
                table.setColumnWidth(c, 460)
        hdr.setStretchLastSection(True)
        table.setUpdatesEnabled(True)

    # ---------------------------------------------------------------- #
    #  Cleanup                                                           #
    # ---------------------------------------------------------------- #

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        if self._worker and self._worker.isRunning():
            self._worker.wait(2000)
        super().closeEvent(event)
