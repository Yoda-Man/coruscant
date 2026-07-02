"""
coruscant.ui.dialogs.recovery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Recovery Mode dialog — shows PostgreSQL standby/recovery status and
offers a one-click "Promote to Primary" action.

Opened automatically when Coruscant detects pg_is_in_recovery() = true
on connect, or manually via the toolbar.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path
from datetime import timedelta

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QWidget, QFrame, QGridLayout,
    QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap

from coruscant.core.database import DatabaseManager

log = logging.getLogger(__name__)

_BASE = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
_BANNER_PATH = str(_BASE / "docs" / "coruscant3.png")

_STYLE = """
QDialog {
    background: #12121e;
}
QLabel {
    color: #cdd6f4;
    background: transparent;
}
QLabel#section_header {
    color: #89b4fa;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding-top: 4px;
}
QLabel#key_lbl {
    color: #a6adc8;
    font-size: 12px;
}
QLabel#val_lbl {
    color: #cdd6f4;
    font-size: 12px;
    font-weight: 600;
}
QLabel#val_danger {
    color: #f38ba8;
    font-size: 12px;
    font-weight: 700;
}
QLabel#val_ok {
    color: #a6e3a1;
    font-size: 12px;
    font-weight: 700;
}
QLabel#val_warn {
    color: #fab387;
    font-size: 12px;
    font-weight: 700;
}
QFrame#card {
    background: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 6px;
}
QPushButton#promote_btn {
    background: #c0392b;
    color: #fff;
    border: none;
    border-radius: 5px;
    padding: 8px 22px;
    font-size: 13px;
    font-weight: 700;
    min-width: 180px;
}
QPushButton#promote_btn:hover   { background: #e74c3c; }
QPushButton#promote_btn:pressed { background: #922b21; }
QPushButton#promote_btn:disabled { background: #3a3a4a; color: #666; }
QPushButton#refresh_btn {
    background: #1565C0;
    color: #fff;
    border: none;
    border-radius: 5px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#refresh_btn:hover   { background: #1976D2; }
QPushButton#refresh_btn:pressed { background: #0D47A1; }
QPushButton#refresh_btn:disabled { background: #1a1a2a; color: #555; }
QPushButton#close_btn {
    background: transparent;
    color: #a6adc8;
    border: 1px solid #444;
    border-radius: 5px;
    padding: 8px 18px;
    font-size: 12px;
}
QPushButton#close_btn:hover { color: #cdd6f4; border-color: #666; }
QScrollArea { border: none; background: transparent; }
"""


class _StatusWorker(QThread):
    """Fetch recovery status off the UI thread."""
    finished: Signal = Signal(dict)
    error:    Signal = Signal(str)

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db = db

    def run(self) -> None:
        try:
            status = self._db.check_recovery_status()
            self.finished.emit(status)
        except Exception as exc:
            self.error.emit(str(exc))


class _PromoteWorker(QThread):
    """Run promote_standby() off the UI thread."""
    finished: Signal = Signal(str)
    error:    Signal = Signal(str)

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db = db

    def run(self) -> None:
        try:
            msg = self._db.promote_standby()
            self.finished.emit(msg)
        except Exception as exc:
            self.error.emit(str(exc))


def _fmt_delay(secs: int | None) -> tuple[str, str]:
    """Return (text, object_name) for the replication delay label."""
    if secs is None:
        return "N/A", "val_lbl"
    if secs < 0:
        secs = 0
    td = timedelta(seconds=secs)
    hours, rem = divmod(int(td.total_seconds()), 3600)
    mins, s = divmod(rem, 60)
    if hours:
        text = f"{hours}h {mins}m {s}s"
    elif mins:
        text = f"{mins}m {s}s"
    else:
        text = f"{s}s"

    if secs > 300:
        return text, "val_danger"
    if secs > 60:
        return text, "val_warn"
    return text, "val_ok"


class RecoveryDialog(QDialog):
    """
    Shows PostgreSQL recovery/standby status and offers a promote action.

    Parameters
    ----------
    db : DatabaseManager
        The active database connection.
    auto_refresh : bool
        If True, poll for updates every 10 seconds automatically.
    """

    def __init__(self, db: DatabaseManager, parent=None,
                 auto_refresh: bool = True) -> None:
        super().__init__(parent)
        self._db = db
        self._status_worker: _StatusWorker | None = None
        self._promote_worker: _PromoteWorker | None = None
        self._last_status: dict | None = None

        self.setWindowTitle("Recovery Mode — Database Status")
        self.setMinimumWidth(560)
        self.setMaximumWidth(700)
        self.setModal(True)
        self.setStyleSheet(_STYLE)

        self._build_ui()

        if auto_refresh:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._refresh)
            self._timer.start(10_000)  # 10-second auto-refresh
        else:
            self._timer = None

        # Kick off the first status fetch
        self._refresh()

    # ------------------------------------------------------------------ #
    #  UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Banner ───────────────────────────────────────────────────── #
        banner = QLabel()
        banner.setFixedHeight(90)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet("background: #0d0d1a;")
        pixmap = QPixmap(_BANNER_PATH)
        if not pixmap.isNull():
            banner.setPixmap(
                pixmap.scaledToHeight(90, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            banner.setText("✦  Coruscant  ✦")
            f = QFont(); f.setPointSize(15); f.setBold(True)
            banner.setFont(f)
            banner.setStyleSheet("background: #0d0d1a; color: #89b4fa;")
        root.addWidget(banner)

        # ── Header strip ─────────────────────────────────────────────── #
        self._strip = QWidget()
        self._strip.setFixedHeight(46)
        self._strip.setStyleSheet(
            "background: #2a0a00; border-top: 1px solid #b71c1c;"
            " border-bottom: 1px solid #b71c1c;"
        )
        strip_layout = QHBoxLayout(self._strip)
        strip_layout.setContentsMargins(16, 0, 16, 0)
        strip_layout.setSpacing(10)

        self._strip_icon = QLabel("⚠")
        self._strip_icon.setStyleSheet(
            "color: #ef5350; font-size: 18px; background: transparent;"
        )
        strip_layout.addWidget(self._strip_icon)

        self._strip_title = QLabel("Database is in Recovery Mode")
        self._strip_title.setStyleSheet(
            "color: #ffcdd2; font-size: 13px; font-weight: 700;"
            " letter-spacing: 0.5px; background: transparent;"
        )
        strip_layout.addWidget(self._strip_title)
        strip_layout.addStretch()

        self._status_lbl = QLabel("Fetching…")
        self._status_lbl.setStyleSheet(
            "color: #fab387; font-size: 11px; background: transparent;"
        )
        strip_layout.addWidget(self._status_lbl)
        root.addWidget(self._strip)

        # ── Scrollable body ───────────────────────────────────────────── #
        body_outer = QWidget()
        body_outer.setStyleSheet("background: #12121e;")
        body_layout = QVBoxLayout(body_outer)
        body_layout.setContentsMargins(16, 14, 16, 10)
        body_layout.setSpacing(12)

        # Status card
        self._card = self._make_card()
        self._grid = QGridLayout(self._card)
        self._grid.setContentsMargins(14, 10, 14, 12)
        self._grid.setVerticalSpacing(6)
        self._grid.setHorizontalSpacing(16)
        self._grid.setColumnStretch(1, 1)
        body_layout.addWidget(self._card)

        # Action hint label
        self._hint_lbl = QLabel(
            "⚙  Promoting converts this standby to a primary server. "
            "This is irreversible — ensure the original primary is offline first."
        )
        self._hint_lbl.setWordWrap(True)
        self._hint_lbl.setStyleSheet(
            "color: #a6adc8; font-size: 11px; background: transparent; padding: 2px 0;"
        )
        body_layout.addWidget(self._hint_lbl)
        body_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(body_outer)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMaximumHeight(340)
        root.addWidget(scroll)

        # ── Divider ───────────────────────────────────────────────────── #
        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet("background: #252535;")
        root.addWidget(div)

        # ── Footer ────────────────────────────────────────────────────── #
        footer = QWidget()
        footer.setStyleSheet("background: #0e0e1c;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 12)

        self._refresh_btn = QPushButton("⟳  Refresh")
        self._refresh_btn.setObjectName("refresh_btn")
        self._refresh_btn.clicked.connect(self._refresh)
        footer_layout.addWidget(self._refresh_btn)

        footer_layout.addStretch()

        self._promote_btn = QPushButton("⚡  Promote to Primary")
        self._promote_btn.setObjectName("promote_btn")
        self._promote_btn.setToolTip(
            "Promote this standby server to primary (pg_promote / pg_wal_replay_resume)"
        )
        self._promote_btn.setEnabled(False)
        self._promote_btn.clicked.connect(self._on_promote)
        footer_layout.addWidget(self._promote_btn)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("close_btn")
        close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(close_btn)

        root.addWidget(footer)

    @staticmethod
    def _make_card() -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return card

    # ------------------------------------------------------------------ #
    #  Status loading                                                      #
    # ------------------------------------------------------------------ #

    def _refresh(self) -> None:
        if self._status_worker and self._status_worker.isRunning():
            return
        self._status_lbl.setText("Refreshing…")
        self._refresh_btn.setEnabled(False)
        self._status_worker = _StatusWorker(self._db, self)
        self._status_worker.finished.connect(self._on_status)
        self._status_worker.error.connect(self._on_status_error)
        self._status_worker.start()

    def _on_status(self, status: dict) -> None:
        self._last_status = status
        self._populate_grid(status)
        self._refresh_btn.setEnabled(True)
        self._status_lbl.setText("Updated just now")

        in_recovery = bool(status.get("is_in_recovery"))
        self._promote_btn.setEnabled(in_recovery)

        if in_recovery:
            self._strip.setStyleSheet(
                "background: #2a0a00; border-top: 1px solid #b71c1c;"
                " border-bottom: 1px solid #b71c1c;"
            )
            self._strip_icon.setText("⚠")
            self._strip_icon.setStyleSheet(
                "color: #ef5350; font-size: 18px; background: transparent;"
            )
            self._strip_title.setText("Database is in Recovery Mode")
            self._strip_title.setStyleSheet(
                "color: #ffcdd2; font-size: 13px; font-weight: 700;"
                " letter-spacing: 0.5px; background: transparent;"
            )
        else:
            self._strip.setStyleSheet(
                "background: #0a2a0a; border-top: 1px solid #2E7D32;"
                " border-bottom: 1px solid #2E7D32;"
            )
            self._strip_icon.setText("✔")
            self._strip_icon.setStyleSheet(
                "color: #66BB6A; font-size: 18px; background: transparent;"
            )
            self._strip_title.setText("Database is Operating Normally (Primary)")
            self._strip_title.setStyleSheet(
                "color: #A5D6A7; font-size: 13px; font-weight: 700;"
                " letter-spacing: 0.5px; background: transparent;"
            )
            self._hint_lbl.setText(
                "✔  This server is now operating as a primary. No action is required."
            )

    def _on_status_error(self, msg: str) -> None:
        self._status_lbl.setText("Error fetching status")
        self._refresh_btn.setEnabled(True)
        log.error("Recovery status fetch failed: %s", msg)
        self._clear_grid()
        self._add_grid_row(0, "Error", msg, "val_danger")

    def _populate_grid(self, s: dict) -> None:
        self._clear_grid()
        row = 0

        in_recovery = bool(s.get("is_in_recovery"))
        recovery_text = "YES — standby / recovery" if in_recovery else "NO — primary"
        recovery_style = "val_danger" if in_recovery else "val_ok"

        paused = s.get("wal_replay_paused")
        if paused is True:
            paused_text, paused_style = "YES (replay paused)", "val_warn"
        elif paused is False:
            paused_text, paused_style = "No", "val_ok"
        else:
            paused_text, paused_style = "N/A", "val_lbl"

        delay_text, delay_style = _fmt_delay(s.get("replication_delay_secs"))

        rows_data = [
            ("In Recovery",         recovery_text,                                      recovery_style),
            ("WAL Replay Paused",   paused_text,                                        paused_style),
            ("Replication Delay",   delay_text,                                         delay_style),
            ("Last WAL Received",   s.get("last_wal_receive_lsn")  or "N/A",           "val_lbl"),
            ("Last WAL Replayed",   s.get("last_wal_replay_lsn")   or "N/A",           "val_lbl"),
            ("Last Txn Replayed",   s.get("last_xact_replay_ts")   or "N/A",           "val_lbl"),
            ("Server Started",      s.get("server_start_time")     or "N/A",           "val_lbl"),
            ("PG Version",          (s.get("pg_version") or "").split(" on ")[0][:60], "val_lbl"),
        ]

        for key, val, style in rows_data:
            self._add_grid_row(row, key, str(val), style)
            row += 1

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _add_grid_row(self, row: int, key: str, val: str, val_style: str) -> None:
        key_lbl = QLabel(key)
        key_lbl.setObjectName("key_lbl")
        val_lbl = QLabel(val)
        val_lbl.setObjectName(val_style)
        val_lbl.setWordWrap(True)
        val_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._grid.addWidget(key_lbl, row, 0)
        self._grid.addWidget(val_lbl, row, 1)

    # ------------------------------------------------------------------ #
    #  Promote action                                                      #
    # ------------------------------------------------------------------ #

    def _on_promote(self) -> None:
        from coruscant.ui.dialogs.message import StyledMessageBox
        confirmed = StyledMessageBox.question(
            self,
            "Confirm Promotion",
            "Are you sure you want to promote this standby to primary?\n\n"
            "This action is irreversible. Make sure the original primary "
            "server is offline or fenced before proceeding.",
        )
        if not confirmed:
            return

        self._promote_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._status_lbl.setText("Promoting…")

        self._promote_worker = _PromoteWorker(self._db, self)
        self._promote_worker.finished.connect(self._on_promote_done)
        self._promote_worker.error.connect(self._on_promote_error)
        self._promote_worker.start()

    def _on_promote_done(self, msg: str) -> None:
        from coruscant.ui.dialogs.message import StyledMessageBox
        log.info("Promote standby succeeded: %s", msg)
        self._status_lbl.setText("Promotion sent")
        StyledMessageBox.information(self, "Promotion Initiated", msg)
        # Refresh to reflect new state
        self._refresh()

    def _on_promote_error(self, msg: str) -> None:
        from coruscant.ui.dialogs.message import StyledMessageBox
        log.error("Promote standby failed: %s", msg)
        self._status_lbl.setText("Promotion failed")
        self._promote_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        StyledMessageBox.critical(
            self, "Promotion Failed",
            f"Could not promote the standby server:\n\n{msg}\n\n"
            "This usually means the user lacks the pg_promote privilege, "
            "or the server is already a primary.",
        )

    # ------------------------------------------------------------------ #
    #  Cleanup                                                             #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:
        if self._timer:
            self._timer.stop()
        for w in (self._status_worker, self._promote_worker):
            if w and w.isRunning():
                w.wait(1000)
        super().closeEvent(event)
