"""
coruscant.ui.panels.history
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Query history panel — stores and displays the last 100 executed queries.

Each entry shows the first 80 characters of SQL, a timestamp, and elapsed time.
Double-clicking emits ``query_selected(sql)`` so MainWindow can load it.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, Signal, QSettings

_SETTINGS_ORG = "Coruscant"
_SETTINGS_APP = "Coruscant"
_HISTORY_KEY  = "query_history/entries"
_MAX_ENTRIES  = 100


class HistoryPanel(QWidget):
    """Left-dock panel showing recently executed queries."""

    query_selected: Signal = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._entries: list[dict] = self._load()
        self._build_ui()
        self._refresh_list()

    # ── Construction ─────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Query History</b>",
                                styleSheet="font-size: 11px;"))
        header.addStretch()
        clear_btn = QPushButton("Clear History")
        clear_btn.setFixedHeight(22)
        clear_btn.setStyleSheet("font-size: 10px; padding: 0 6px;")
        clear_btn.clicked.connect(self._on_clear)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setWordWrap(False)
        self._list.setMouseTracking(True)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._list)

    # ── Public API ───────────────────────────────────────────────────── #

    def add_entry(self, sql: str, elapsed_ms: float) -> None:
        """
        Add *sql* to the top of the history list.

        Consecutive identical queries update the existing entry instead of
        creating a duplicate.
        """
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {"sql": sql, "timestamp": ts, "elapsed_ms": round(elapsed_ms, 1)}

        if self._entries and self._entries[0]["sql"] == sql:
            self._entries[0].update(timestamp=ts, elapsed_ms=round(elapsed_ms, 1))
        else:
            self._entries.insert(0, entry)
            if len(self._entries) > _MAX_ENTRIES:
                self._entries = self._entries[:_MAX_ENTRIES]

        self._save()
        self._refresh_list()

    # ── Private helpers ──────────────────────────────────────────────── #

    def _refresh_list(self) -> None:
        self._list.clear()
        for entry in self._entries:
            preview = entry["sql"].replace("\n", " ").replace("\r", "")
            if len(preview) > 80:
                preview = preview[:77] + "…"

            elapsed = entry.get("elapsed_ms", 0)
            elapsed_str = (f"{elapsed:.0f} ms" if elapsed < 1000
                           else f"{elapsed / 1000:.2f} s")

            item = QListWidgetItem(
                f"{preview}\n{entry['timestamp']}  •  {elapsed_str}"
            )
            item.setData(Qt.ItemDataRole.UserRole, entry["sql"])
            item.setToolTip(entry["sql"])
            self._list.addItem(item)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        sql = item.data(Qt.ItemDataRole.UserRole)
        if sql:
            self.query_selected.emit(sql)

    def _on_clear(self) -> None:
        self._entries = []
        self._save()
        self._refresh_list()

    # ── Persistence ──────────────────────────────────────────────────── #

    def _save(self) -> None:
        try:
            self._settings.setValue(_HISTORY_KEY, json.dumps(self._entries))
        except Exception:
            pass  # History is a convenience feature — never fatal

    def _load(self) -> list[dict]:
        raw = self._settings.value(_HISTORY_KEY, "[]")
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data[:_MAX_ENTRIES]
        except Exception:
            pass
        return []
