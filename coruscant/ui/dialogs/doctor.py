"""
coruscant.ui.dialogs.doctor
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Database Doctor dialog — a live dashboard that diagnoses four common
PostgreSQL problems and repairs them with a single button click.

Checks
------
  🔒 Lock Contention      blocked queries + their blockers
  🗑 Table Bloat           dead tuple accumulation needing VACUUM
  🔌 Connection Health     idle / idle-in-transaction connection pile-up
  ⏱ XID Wraparound         transaction ID age approaching the 2-billion limit

All diagnosis and repair operations run off the UI thread so the
application never freezes.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QTableWidget, QTableWidgetItem,
    QScrollArea, QSizePolicy, QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPixmap, QColor

from coruscant.core.database import DatabaseManager, QueryResult
import coruscant.core.doctor as _dr

log = logging.getLogger(__name__)

_BASE = (
    Path(sys._MEIPASS)
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[3]
)
_BANNER_PATH = str(_BASE / "docs" / "coruscant3.png")

# Severity → (border_color, strip_bg, badge_fg, badge_text)
_SEV: dict[str, tuple[str, str, str, str]] = {
    _dr.OK:       ("#2E7D32", "#0a1f0a", "#66BB6A", "✔  Healthy"),
    _dr.WARNING:  ("#E65100", "#2a1500", "#FFA726", "⚠  Warning"),
    _dr.CRITICAL: ("#B71C1C", "#2a0a0a", "#EF5350", "⛔  Critical"),
    _dr.ERROR:    ("#555555", "#1a1a1a", "#888888", "✗  Error"),
}

_STYLE = """
QDialog { background: #12121e; }
QLabel  { color: #cdd6f4; background: transparent; }

QFrame#card {
    background: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 6px;
}
QLabel#card_title {
    color: #cdd6f4; font-size: 13px; font-weight: 700;
}
QLabel#card_summary {
    color: #a6adc8; font-size: 12px; padding: 2px 0 6px 0;
}
QLabel#badge {
    font-size: 11px; font-weight: 700;
    padding: 2px 8px; border-radius: 3px;
}

QTableWidget {
    background: #181825; color: #cdd6f4;
    border: 1px solid #313244; border-radius: 4px;
    font-size: 11px; gridline-color: #252535;
    selection-background-color: #313244;
    selection-color: #cdd6f4;
}
QHeaderView::section {
    background: #252535; color: #89b4fa;
    padding: 4px 8px; border: none;
    border-right: 1px solid #313244;
    border-bottom: 1px solid #313244;
    font-size: 11px; font-weight: 600;
}
QTableWidget::item { padding: 3px 8px; }

QScrollArea  { border: none; background: transparent; }
QScrollBar:vertical   { background: #12121e; width: 8px; }
QScrollBar::handle:vertical { background: #444; border-radius: 4px; min-height: 20px; }

QPushButton#run_btn {
    background: #1565C0; color: #fff; border: none;
    border-radius: 5px; padding: 7px 22px;
    font-size: 12px; font-weight: 700;
}
QPushButton#run_btn:hover   { background: #1976D2; }
QPushButton#run_btn:pressed { background: #0D47A1; }
QPushButton#run_btn:disabled { background: #1a1a2a; color: #555; }

QPushButton#repair_btn {
    background: #1a2a00; color: #A5D6A7;
    border: 1px solid #2E7D32;
    border-radius: 4px; padding: 4px 12px;
    font-size: 11px; font-weight: 600;
}
QPushButton#repair_btn:hover   { background: #253a00; color: #C8E6C9; }
QPushButton#repair_btn:pressed { background: #1a2500; }
QPushButton#repair_btn:disabled { background: #1a1a1a; color: #555; border-color: #333; }

QPushButton#danger_btn {
    background: #2a0a0a; color: #EF5350;
    border: 1px solid #B71C1C;
    border-radius: 4px; padding: 4px 12px;
    font-size: 11px; font-weight: 600;
}
QPushButton#danger_btn:hover   { background: #3a0f0f; color: #F44336; }
QPushButton#danger_btn:pressed { background: #4a1515; }
QPushButton#danger_btn:disabled { background: #1a1a1a; color: #555; border-color: #333; }

QPushButton#warn_btn {
    background: #2a1500; color: #FFA726;
    border: 1px solid #E65100;
    border-radius: 4px; padding: 4px 12px;
    font-size: 11px; font-weight: 600;
}
QPushButton#warn_btn:hover   { background: #3a2000; color: #FFB74D; }
QPushButton#warn_btn:pressed { background: #4a2800; }
QPushButton#warn_btn:disabled { background: #1a1a1a; color: #555; border-color: #333; }

QPushButton#close_btn {
    background: transparent; color: #a6adc8;
    border: 1px solid #444; border-radius: 5px;
    padding: 7px 22px; font-size: 12px;
}
QPushButton#close_btn:hover { color: #cdd6f4; border-color: #666; }
"""


# ── Background workers ────────────────────────────────────────────── #

class _DiagnosisWorker(QThread):
    """Runs all four diagnostic SQL queries off the UI thread."""

    finished: Signal = Signal(dict)   # {key: (severity, summary, columns, rows, meta)}
    error:    Signal = Signal(str)

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db = db

    def run(self) -> None:
        results: dict[str, Any] = {}
        checks = [
            ("locks",       _dr.LOCKS_SQL,        None,                    None),
            ("bloat",       _dr.BLOAT_SQL,         None,                    None),
            ("connections", _dr.CONN_SUMMARY_SQL,  _dr.CONN_DETAIL_SQL,     None),
            ("wraparound",  _dr.WRAPAROUND_SQL,    None,                    None),
        ]
        for key, sql, detail_sql, _ in checks:
            try:
                res = self._db.execute(sql)
                rows = res[0].rows if res and isinstance(res[0], QueryResult) else []
                cols = res[0].columns if res and isinstance(res[0], QueryResult) else []

                meta: dict = {}
                detail_rows: list[tuple] = []
                detail_cols: list[str] = []

                if key == "connections":
                    # summary_row is the single row from CONN_SUMMARY_SQL
                    summary_row = rows[0] if rows else (0, 1, 0, 0, 0, 0)
                    sev, summary = _dr.assess_connections(summary_row)
                    meta["summary_row"] = summary_row
                    # now fetch detail
                    dres = self._db.execute(detail_sql)
                    detail_rows = dres[0].rows if dres and isinstance(dres[0], QueryResult) else []
                    detail_cols = dres[0].columns if dres and isinstance(dres[0], QueryResult) else []
                    results[key] = (sev, summary, detail_cols, detail_rows, meta)
                    continue

                if key == "locks":
                    sev, summary = _dr.assess_locks(rows)
                elif key == "bloat":
                    sev, summary = _dr.assess_bloat(rows)
                else:  # wraparound
                    sev, summary = _dr.assess_wraparound(rows)

                results[key] = (sev, summary, cols, rows, meta)

            except Exception as exc:
                results[key] = (_dr.ERROR, str(exc), [], [], {})

        self.finished.emit(results)


def _vacuum_report(db, targets: list[tuple[str, str]]) -> str:
    """
    VACUUM ANALYZE each (schema, table) and describe what actually happened.

    PostgreSQL skips a table you do not own with a WARNING rather than an
    error, so a loop that only watches for exceptions will report success
    having vacuumed nothing.  Count the skips and say so.
    """
    skipped: list[str] = []
    for schema, table in targets:
        if db.vacuum_table(schema, table, full=False, analyze=True):
            skipped.append(f"{schema}.{table}")

    done = len(targets) - len(skipped)
    if not skipped:
        return f"VACUUM ANALYZE complete on {done} table(s)."

    listing = "\n".join(f"  • {n}" for n in skipped[:10])
    if len(skipped) > 10:
        listing += f"\n  … and {len(skipped) - 10} more"

    if done == 0:
        head = (f"No tables were vacuumed.\n\n"
                f"PostgreSQL skipped all {len(skipped)} table(s) because you do "
                f"not own them, and only the table or database owner can vacuum "
                f"a table.")
    else:
        n = len(skipped)
        head = (f"VACUUM ANALYZE completed on {done} of {len(targets)} table(s).\n\n"
                f"{n} {'was' if n == 1 else 'were'} skipped because you do not "
                f"own {'it' if n == 1 else 'them'}:")
    return (f"{head}\n\n{listing}\n\n"
            f"Ask a superuser, or the owning role, to vacuum these — or let "
            f"autovacuum handle them.")


class _RepairWorker(QThread):
    """Runs a single repair callable off the UI thread."""

    finished: Signal = Signal(str)
    error:    Signal = Signal(str)

    def __init__(self, fn: Callable[[], str], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            msg = self._fn()
            self.finished.emit(msg or "Done.")
        except Exception as exc:
            self.error.emit(str(exc))


# ── Card helper ───────────────────────────────────────────────────── #

class _Card:
    """
    Thin data-class that holds references to a diagnostic card's widgets
    so the dialog can update them when results arrive.
    """
    __slots__ = (
        "frame", "strip", "badge", "summary_lbl",
        "table", "button_bar", "buttons",
    )

    def __init__(self) -> None:
        self.frame:      QFrame
        self.strip:      QWidget
        self.badge:      QLabel
        self.summary_lbl: QLabel
        self.table:      QTableWidget
        self.button_bar: QWidget
        self.buttons:    dict[str, QPushButton] = {}


# ── Main dialog ───────────────────────────────────────────────────── #

class DatabaseDoctorDialog(QDialog):
    """
    Live database health dashboard.

    Parameters
    ----------
    db : DatabaseManager
        The active database connection.
    parent : QWidget | None
    """

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._diag_worker:   _DiagnosisWorker | None = None
        self._repair_worker: _RepairWorker    | None = None
        self._cards: dict[str, _Card] = {}
        self._last_results: dict = {}

        self.setWindowTitle("Database Doctor")
        self.setMinimumWidth(680)
        self.setMaximumWidth(820)
        self.setMinimumHeight(500)
        self.setModal(True)
        self.setStyleSheet(_STYLE)

        self._build_ui()
        self._run_diagnosis()

    # ---------------------------------------------------------------- #
    #  UI construction                                                   #
    # ---------------------------------------------------------------- #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Banner ──────────────────────────────────────────────────── #
        banner = QLabel()
        banner.setFixedHeight(80)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet("background: #0d0d1a;")
        pix = QPixmap(_BANNER_PATH)
        if not pix.isNull():
            banner.setPixmap(
                pix.scaledToHeight(80, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            banner.setText("✦  Coruscant  ✦")
            f = QFont(); f.setPointSize(14); f.setBold(True)
            banner.setFont(f)
            banner.setStyleSheet("background: #0d0d1a; color: #89b4fa;")
        root.addWidget(banner)

        # ── Header strip ────────────────────────────────────────────── #
        strip = QWidget()
        strip.setFixedHeight(46)
        strip.setStyleSheet(
            "background: #0d1a2e;"
            " border-top: 1px solid #1565C0;"
            " border-bottom: 1px solid #1565C0;"
        )
        strip_row = QHBoxLayout(strip)
        strip_row.setContentsMargins(16, 0, 16, 0)
        strip_row.setSpacing(10)

        icon_lbl = QLabel("🩺")
        icon_lbl.setStyleSheet("font-size: 18px; background: transparent;")
        strip_row.addWidget(icon_lbl)

        title_lbl = QLabel("Database Doctor")
        title_lbl.setStyleSheet(
            "color: #89b4fa; font-size: 14px; font-weight: 700;"
            " letter-spacing: 0.5px; background: transparent;"
        )
        strip_row.addWidget(title_lbl)
        strip_row.addStretch()

        self._status_lbl = QLabel("Running diagnosis…")
        self._status_lbl.setStyleSheet(
            "color: #6c7086; font-size: 11px; background: transparent;"
        )
        strip_row.addWidget(self._status_lbl)
        root.addWidget(strip)

        # ── Control bar ──────────────────────────────────────────────── #
        ctrl = QWidget()
        ctrl.setStyleSheet("background: #161626; border-bottom: 1px solid #252535;")
        ctrl_row = QHBoxLayout(ctrl)
        ctrl_row.setContentsMargins(16, 8, 16, 8)

        self._run_btn = QPushButton("🔄  Run Diagnosis")
        self._run_btn.setObjectName("run_btn")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._run_diagnosis)
        ctrl_row.addWidget(self._run_btn)
        ctrl_row.addStretch()

        hint = QLabel("Checks run automatically on open and can be repeated at any time.")
        hint.setStyleSheet("color: #6c7086; font-size: 11px; background: transparent;")
        ctrl_row.addWidget(hint)
        root.addWidget(ctrl)

        # ── Scrollable card area ──────────────────────────────────────── #
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: #12121e;")
        cards_layout = QVBoxLayout(scroll_content)
        cards_layout.setContentsMargins(14, 14, 14, 14)
        cards_layout.setSpacing(12)

        cards_layout.addWidget(self._build_card(
            "locks", "🔒", "Lock Contention",
            "Queries waiting because another session holds a conflicting lock.",
            [
                ("Kill Selected Blocker", "danger_btn", self._kill_selected_blocker),
            ],
        ))
        cards_layout.addWidget(self._build_card(
            "bloat", "🗑", "Table Bloat",
            "Tables with high dead-tuple ratios causing slow scans and wasted disk.",
            [
                ("VACUUM Selected",  "repair_btn", self._vacuum_selected),
                ("VACUUM All",       "warn_btn",   self._vacuum_all),
            ],
        ))
        cards_layout.addWidget(self._build_card(
            "connections", "🔌", "Connection Health",
            "Idle and idle-in-transaction connections consuming slots unnecessarily.",
            [
                ("Terminate Idle",          "warn_btn",   self._terminate_idle),
                ("Terminate Idle-in-Txn",   "danger_btn", self._terminate_idle_in_txn),
            ],
        ))
        cards_layout.addWidget(self._build_card(
            "wraparound", "⏱", "XID Wraparound",
            "Transaction ID age approaching the 2-billion PostgreSQL hard limit.",
            [
                ("VACUUM FREEZE", "danger_btn", self._vacuum_freeze),
            ],
        ))
        cards_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(scroll_content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(scroll)

        # ── Footer ───────────────────────────────────────────────────── #
        div = QWidget(); div.setFixedHeight(1)
        div.setStyleSheet("background: #252535;")
        root.addWidget(div)

        footer = QWidget()
        footer.setStyleSheet("background: #0e0e1c;")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(16, 10, 16, 12)
        footer_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("close_btn")
        close_btn.clicked.connect(self.accept)
        footer_row.addWidget(close_btn)
        root.addWidget(footer)

    def _build_card(
        self,
        key: str,
        icon: str,
        title: str,
        description: str,
        buttons: list[tuple[str, str, Callable]],
    ) -> QFrame:
        """Build one diagnostic card and register it in self._cards."""
        card = _Card()

        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Colored left severity strip
        strip = QWidget()
        strip.setFixedWidth(4)
        strip.setStyleSheet("background: #444; border-radius: 6px 0 0 6px;")
        outer.addWidget(strip)
        card.strip = strip

        # Card content
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(content)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(4)

        # Header row: icon + title + badge
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        icon_lbl = QLabel(f"{icon}  {title}")
        icon_lbl.setObjectName("card_title")
        header_row.addWidget(icon_lbl)
        header_row.addStretch()

        badge = QLabel("…")
        badge.setObjectName("badge")
        badge.setStyleSheet(
            "background: #252535; color: #6c7086;"
            " padding: 2px 8px; border-radius: 3px; font-size: 11px;"
        )
        header_row.addWidget(badge)
        card.badge = badge
        vbox.addLayout(header_row)

        # Description (static)
        desc_lbl = QLabel(description)
        desc_lbl.setStyleSheet(
            "color: #585b70; font-size: 11px; background: transparent;"
        )
        desc_lbl.setWordWrap(True)
        vbox.addWidget(desc_lbl)

        # Summary (updated with results)
        summary_lbl = QLabel("Checking…")
        summary_lbl.setObjectName("card_summary")
        summary_lbl.setWordWrap(True)
        vbox.addWidget(summary_lbl)
        card.summary_lbl = summary_lbl

        # Detail table (hidden until results arrive)
        table = QTableWidget(0, 0)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setMaximumHeight(150)
        table.hide()
        vbox.addWidget(table)
        card.table = table

        # Button bar
        btn_bar = QWidget()
        btn_bar.setStyleSheet("background: transparent;")
        btn_row = QHBoxLayout(btn_bar)
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.setSpacing(8)

        card.buttons = {}
        for label, obj_name, handler in buttons:
            btn = QPushButton(label)
            btn.setObjectName(obj_name)
            btn.setEnabled(False)
            btn.clicked.connect(handler)
            btn_row.addWidget(btn)
            card.buttons[label] = btn

        btn_row.addStretch()
        btn_bar.hide()
        vbox.addWidget(btn_bar)
        card.button_bar = btn_bar

        outer.addWidget(content)
        card.frame = frame
        self._cards[key] = card
        return frame

    # ---------------------------------------------------------------- #
    #  Diagnosis                                                         #
    # ---------------------------------------------------------------- #

    def _run_diagnosis(self) -> None:
        if self._diag_worker and self._diag_worker.isRunning():
            return
        self._run_btn.setEnabled(False)
        self._status_lbl.setText("Running diagnosis…")
        for card in self._cards.values():
            card.summary_lbl.setText("Checking…")
            card.badge.setText("…")
            card.badge.setStyleSheet(
                "background: #252535; color: #6c7086;"
                " padding: 2px 8px; border-radius: 3px; font-size: 11px;"
            )
            for btn in card.buttons.values():
                btn.setEnabled(False)
            card.table.hide()
            card.button_bar.hide()

        self._diag_worker = _DiagnosisWorker(self._db, self)
        self._diag_worker.finished.connect(self._on_diagnosis_done)
        self._diag_worker.error.connect(self._on_diagnosis_error)
        self._diag_worker.start()

    def _on_diagnosis_done(self, results: dict) -> None:
        self._last_results = results
        for key, (sev, summary, cols, rows, meta) in results.items():
            self._populate_card(key, sev, summary, cols, rows)
        self._run_btn.setEnabled(True)
        self._status_lbl.setText("Diagnosis complete.")

    def _on_diagnosis_error(self, msg: str) -> None:
        self._status_lbl.setText(f"Diagnosis failed: {msg}")
        self._run_btn.setEnabled(True)

    def _populate_card(
        self,
        key: str,
        sev: str,
        summary: str,
        cols: list[str],
        rows: list[tuple],
    ) -> None:
        card = self._cards[key]
        border_col, _, badge_fg, badge_text = _SEV.get(sev, _SEV[_dr.ERROR])

        # Update severity strip colour
        card.strip.setStyleSheet(
            f"background: {border_col}; border-radius: 6px 0 0 6px;"
        )
        # Update badge
        card.badge.setText(badge_text)
        card.badge.setStyleSheet(
            f"background: {border_col}22; color: {badge_fg};"
            " padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 700;"
        )
        # Update summary
        card.summary_lbl.setText(summary)

        # Populate table
        if rows and cols:
            card.table.clear()
            card.table.setColumnCount(len(cols))
            card.table.setHorizontalHeaderLabels(
                [c.replace("_", " ").title() for c in cols]
            )
            card.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    item = QTableWidgetItem(
                        "" if val is None else str(val)
                    )
                    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    card.table.setItem(r, c, item)
            card.table.resizeColumnsToContents()
            card.table.horizontalHeader().setStretchLastSection(True)
            card.table.show()
        else:
            card.table.hide()

        # Enable buttons when there is something to act on
        has_data = bool(rows)
        for label, btn in card.buttons.items():
            # Kill blocker only if a row is selected (handled in handler)
            # Buttons for bulk actions enable when there's any data
            btn.setEnabled(has_data if sev != _dr.OK else False)

        if sev != _dr.OK:
            card.button_bar.show()
        else:
            card.button_bar.hide()

    # ---------------------------------------------------------------- #
    #  Repair helpers                                                    #
    # ---------------------------------------------------------------- #

    def _start_repair(self, fn: Callable[[], str], on_done: Callable[[str], None]) -> None:
        """Run *fn* off the UI thread, call *on_done* with the result message."""
        if self._repair_worker and self._repair_worker.isRunning():
            from coruscant.ui.dialogs.message import StyledMessageBox
            StyledMessageBox.warning(
                self, "Repair in Progress",
                "Another repair operation is already running. Please wait."
            )
            return
        self._run_btn.setEnabled(False)
        self._status_lbl.setText("Repair in progress…")
        self._repair_worker = _RepairWorker(fn, self)
        self._repair_worker.finished.connect(on_done)
        self._repair_worker.error.connect(self._on_repair_error)
        self._repair_worker.finished.connect(lambda _: self._after_repair())
        self._repair_worker.error.connect(lambda _: self._after_repair())
        self._repair_worker.start()

    def _after_repair(self) -> None:
        self._status_lbl.setText("Repair complete. Re-running diagnosis…")
        self._run_diagnosis()

    def _on_repair_error(self, msg: str) -> None:
        from coruscant.ui.dialogs.message import StyledMessageBox
        StyledMessageBox.critical(self, "Repair Failed", msg)

    def _confirm(self, title: str, text: str) -> bool:
        from coruscant.ui.dialogs.message import StyledMessageBox
        return StyledMessageBox.question(self, title, text)

    # ---------------------------------------------------------------- #
    #  Lock Contention repairs                                           #
    # ---------------------------------------------------------------- #

    def _kill_selected_blocker(self) -> None:
        card = self._cards["locks"]
        selected = card.table.selectedItems()
        if not selected:
            from coruscant.ui.dialogs.message import StyledMessageBox
            StyledMessageBox.information(
                self, "No Selection",
                "Select a row in the Lock Contention table to choose which blocker to kill."
            )
            return

        row = card.table.currentRow()
        # blocking_pid is column index 4
        pid_item = card.table.item(row, 4)
        if not pid_item or not pid_item.text().isdigit():
            return
        pid = int(pid_item.text())
        blocking_user_item = card.table.item(row, 5)
        blocking_user = blocking_user_item.text() if blocking_user_item else "?"

        if not self._confirm(
            "Kill Blocking Session",
            f"Terminate backend PID {pid} (user: {blocking_user})?\n\n"
            "This will roll back any open transaction in that session.",
        ):
            return

        def _do() -> str:
            ok = self._db.kill_connection(pid)
            return (
                f"PID {pid} terminated successfully."
                if ok
                else f"PID {pid} could not be terminated — it may have already finished."
            )

        def _done(msg: str) -> None:
            from coruscant.ui.dialogs.message import StyledMessageBox
            StyledMessageBox.information(self, "Kill Blocker", msg)

        self._start_repair(_do, _done)

    # ---------------------------------------------------------------- #
    #  Table Bloat repairs                                              #
    # ---------------------------------------------------------------- #

    def _vacuum_selected(self) -> None:
        card = self._cards["bloat"]
        rows = list({idx.row() for idx in card.table.selectedIndexes()})
        if not rows:
            from coruscant.ui.dialogs.message import StyledMessageBox
            StyledMessageBox.information(
                self, "No Selection",
                "Select one or more rows in the Table Bloat list to VACUUM."
            )
            return

        targets = []
        for r in rows:
            schema = (card.table.item(r, 0) or QTableWidgetItem("")).text()
            table  = (card.table.item(r, 1) or QTableWidgetItem("")).text()
            if schema and table:
                targets.append((schema, table))

        if not targets:
            return
        names = ", ".join(f"{s}.{t}" for s, t in targets)
        if not self._confirm(
            "VACUUM Tables",
            f"Run VACUUM ANALYZE on:\n{names}\n\nThis is safe and non-blocking."
        ):
            return

        def _do() -> str:
            return _vacuum_report(self._db, targets)

        def _done(msg: str) -> None:
            from coruscant.ui.dialogs.message import StyledMessageBox
            StyledMessageBox.information(self, "VACUUM Complete", msg)

        self._start_repair(_do, _done)

    def _vacuum_all(self) -> None:
        card = self._cards["bloat"]
        n = card.table.rowCount()
        if n == 0:
            return
        targets = []
        for r in range(n):
            schema = (card.table.item(r, 0) or QTableWidgetItem("")).text()
            table  = (card.table.item(r, 1) or QTableWidgetItem("")).text()
            if schema and table:
                targets.append((schema, table))

        if not self._confirm(
            "VACUUM All Bloated Tables",
            f"Run VACUUM ANALYZE on all {len(targets)} bloated table(s)?\n\n"
            "This is safe and non-blocking, but may take a while on large tables."
        ):
            return

        def _do() -> str:
            return _vacuum_report(self._db, targets)

        def _done(msg: str) -> None:
            from coruscant.ui.dialogs.message import StyledMessageBox
            StyledMessageBox.information(self, "VACUUM Complete", msg)

        self._start_repair(_do, _done)

    # ---------------------------------------------------------------- #
    #  Connection Health repairs                                        #
    # ---------------------------------------------------------------- #

    def _terminate_idle(self) -> None:
        if not self._confirm(
            "Terminate Idle Connections",
            "Terminate all idle connections?\n\n"
            "This is safe — idle connections have no open transactions.\n"
            "Applications will reconnect automatically."
        ):
            return

        def _do() -> str:
            n = self._db.terminate_connections(state="idle")
            return f"Terminated {n} idle connection(s)."

        def _done(msg: str) -> None:
            from coruscant.ui.dialogs.message import StyledMessageBox
            StyledMessageBox.information(self, "Connections Terminated", msg)

        self._start_repair(_do, _done)

    def _terminate_idle_in_txn(self) -> None:
        if not self._confirm(
            "Terminate Idle-in-Transaction Connections",
            "Terminate all idle-in-transaction connections?\n\n"
            "⚠ This will roll back any open (uncommitted) transactions in those sessions.\n"
            "Proceed only if you are certain those transactions can be safely discarded."
        ):
            return

        def _do() -> str:
            n = self._db.terminate_connections(state="idle in transaction")
            return f"Terminated {n} idle-in-transaction connection(s)."

        def _done(msg: str) -> None:
            from coruscant.ui.dialogs.message import StyledMessageBox
            StyledMessageBox.information(self, "Connections Terminated", msg)

        self._start_repair(_do, _done)

    # ---------------------------------------------------------------- #
    #  XID Wraparound repairs                                           #
    # ---------------------------------------------------------------- #

    def _vacuum_freeze(self) -> None:
        if not self._confirm(
            "VACUUM FREEZE",
            "Run VACUUM FREEZE on all tables in the current database?\n\n"
            "This resets transaction ID ages and prevents XID wraparound.\n"
            "It may take several minutes on a large database and will\n"
            "generate significant I/O. Schedule during low-traffic periods."
        ):
            return

        def _do() -> str:
            skipped = self._db.vacuum_freeze()
            if not skipped:
                return "VACUUM FREEZE complete on the current database."
            return (
                f"VACUUM FREEZE ran, but PostgreSQL skipped {len(skipped)} table(s) "
                f"that the current role does not own — only the table or database "
                f"owner can vacuum a table, so their transaction ID age is "
                f"unchanged.\n\nRun this as a superuser or as the owning role to "
                f"cover the whole database."
            )

        def _done(msg: str) -> None:
            from coruscant.ui.dialogs.message import StyledMessageBox
            StyledMessageBox.information(self, "VACUUM FREEZE Complete", msg)

        self._start_repair(_do, _done)

    # ---------------------------------------------------------------- #
    #  Cleanup                                                           #
    # ---------------------------------------------------------------- #

    def closeEvent(self, event) -> None:
        for w in (self._diag_worker, self._repair_worker):
            if w and w.isRunning():
                w.wait(1500)
        super().closeEvent(event)
