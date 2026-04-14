"""
coruscant.ui.widgets.results
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
All result-display widgets shown in the result tab area:

  ResultGrid     – sortable table for SELECT results with live filtering
  MessageResult  – success message for DML / DDL
  ExplainResult  – monospace plan text for EXPLAIN
  ErrorResult    – inline error display (replaces modal dialogs)

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import csv
import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QPlainTextEdit, QFileDialog,
)
from coruscant.ui.dialogs.message import StyledMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication

from coruscant.utils.serializers import json_default


# ═══════════════════════════════════════════════════════════════════════ #
#  Internal: copyable table                                               #
# ═══════════════════════════════════════════════════════════════════════ #

class _CopyableTable(QTableWidget):
    """QTableWidget where Ctrl+C copies selected rows as TSV."""

    def keyPressEvent(self, event) -> None:
        if (event.key() == Qt.Key.Key_C
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._copy_to_clipboard()
            return
        super().keyPressEvent(event)

    def _copy_to_clipboard(self) -> None:
        selected: set[int] = set()
        for rng in self.selectedRanges():
            for r in range(rng.topRow(), rng.bottomRow() + 1):
                selected.add(r)

        if not selected:
            return

        cols  = self.columnCount()
        lines = ["\t".join(
            self.horizontalHeaderItem(c).text() if self.horizontalHeaderItem(c) else ""
            for c in range(cols)
        )]
        for row in sorted(selected):
            lines.append("\t".join(
                (self.item(row, c).text() if self.item(row, c) else "")
                for c in range(cols)
            ))
        QGuiApplication.clipboard().setText("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════ #
#  ResultGrid                                                             #
# ═══════════════════════════════════════════════════════════════════════ #

class ResultGrid(QWidget):
    """
    Displays a SELECT result set.

    Features
    --------
    • Row/column count label
    • Live filter box — uses setRowHidden (O(n), no widget rebuild)
    • Truncation warning when the row limit was hit
    • Export CSV and Export JSON buttons
    • Ctrl+C copies selected rows as TSV
    • Sortable columns, NULL shown in grey italic
    """

    def __init__(
        self,
        columns: list[str],
        rows: list[tuple],
        label: str = "",
        truncated: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._columns   = columns
        self._all_rows  = list(rows)
        self._label     = label
        self._truncated = truncated
        self._build_ui()

    # ── Construction ─────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        layout.addWidget(self._build_header())

        if self._truncated:
            layout.addWidget(self._build_truncation_warning())

        self._table = self._build_table()
        layout.addWidget(self._table)

    def _build_header(self) -> QWidget:
        header = QWidget()
        hb = QHBoxLayout(header)
        hb.setContentsMargins(6, 3, 6, 3)
        hb.setSpacing(6)

        self._info_label = QLabel()
        self._info_label.setStyleSheet("font-size: 12px;")
        self._update_info_label(len(self._all_rows))
        hb.addWidget(self._info_label)
        hb.addStretch()

        hb.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("type to filter rows…")
        self._filter_edit.setFixedWidth(200)
        self._filter_edit.setFixedHeight(22)
        self._filter_edit.textChanged.connect(self._apply_filter)
        hb.addWidget(self._filter_edit)

        self._match_label = QLabel("")
        self._match_label.setStyleSheet("font-size: 11px; color: #888;")
        hb.addWidget(self._match_label)

        for label, slot in [("Export CSV", self._export_csv),
                             ("Export JSON", self._export_json)]:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.setStyleSheet("font-size: 11px; padding: 0 8px;")
            btn.clicked.connect(slot)
            hb.addWidget(btn)

        return header

    def _build_truncation_warning(self) -> QLabel:
        w = QLabel(
            f"  ⚠  Showing first {len(self._all_rows):,} rows — results truncated"
        )
        w.setStyleSheet(
            "background: #665500; color: #ffdd57; font-size: 12px; padding: 3px 8px;"
        )
        return w

    def _build_table(self) -> _CopyableTable:
        table = _CopyableTable(len(self._all_rows), len(self._columns))
        table.setHorizontalHeaderLabels(self._columns)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setShowGrid(True)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        hdr.setHighlightSections(False)
        table.verticalHeader().setDefaultSectionSize(22)

        self._populate_table(table)
        return table

    # ── Table population ─────────────────────────────────────────────── #

    def _populate_table(self, table: _CopyableTable) -> None:
        null_font = QFont()
        null_font.setItalic(True)

        table.setSortingEnabled(False)
        for row_idx, row in enumerate(self._all_rows):
            for col_idx, value in enumerate(row):
                if value is None:
                    item = QTableWidgetItem("NULL")
                    item.setForeground(Qt.GlobalColor.gray)
                    item.setFont(null_font)
                else:
                    item = QTableWidgetItem(str(value))
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                table.setItem(row_idx, col_idx, item)
        table.setSortingEnabled(True)

        table.resizeColumnsToContents()
        for col in range(table.columnCount() - 1):
            if table.columnWidth(col) > 300:
                table.setColumnWidth(col, 300)

    # ── Filter ───────────────────────────────────────────────────────── #

    def _apply_filter(self, text: str) -> None:
        """Hide rows that don't match *text*.  O(n) — no repopulation."""
        needle  = text.strip().lower()
        visible = 0

        for row_idx, row in enumerate(self._all_rows):
            if not needle:
                self._table.setRowHidden(row_idx, False)
                visible += 1
            else:
                match = (
                    any(needle in str(v).lower() for v in row if v is not None)
                    or (needle == "null" and any(v is None for v in row))
                )
                self._table.setRowHidden(row_idx, not match)
                if match:
                    visible += 1

        self._match_label.setText(f"{visible:,} match(es)" if needle else "")
        self._update_info_label(visible)

    def _update_info_label(self, visible: int) -> None:
        total = len(self._all_rows)
        cols  = len(self._columns)
        if visible == total:
            self._info_label.setText(
                f"<b>{self._label}</b> &nbsp;–&nbsp; {total:,} row(s),  {cols} column(s)"
            )
        else:
            self._info_label.setText(
                f"<b>{self._label}</b> &nbsp;–&nbsp; "
                f"{visible:,} / {total:,} row(s),  {cols} column(s)"
            )

    # ── Export ───────────────────────────────────────────────────────── #

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(self._columns)
                writer.writerows(
                    ["" if v is None else v for v in row]
                    for row in self._all_rows
                )
            StyledMessageBox.information(self, "Export", f"Saved to:\n{path}")
        except OSError as exc:
            StyledMessageBox.critical(self, "Export Error", str(exc))

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to JSON", "", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            records = [dict(zip(self._columns, row)) for row in self._all_rows]
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(records, fh, indent=2, default=json_default)
            StyledMessageBox.information(self, "Export", f"Saved to:\n{path}")
        except OSError as exc:
            StyledMessageBox.critical(self, "Export Error", str(exc))


# ═══════════════════════════════════════════════════════════════════════ #
#  MessageResult                                                          #
# ═══════════════════════════════════════════════════════════════════════ #

class MessageResult(QWidget):
    """Success message displayed for DML / DDL statements."""

    def __init__(self, message: str, label: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        lbl = QLabel(f"<b>{label}</b><br><br>{message.replace(chr(10), '<br>')}")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #81c784; font-size: 14px; padding: 30px;")
        layout.addWidget(lbl)


# ═══════════════════════════════════════════════════════════════════════ #
#  ExplainResult                                                          #
# ═══════════════════════════════════════════════════════════════════════ #

class ExplainResult(QWidget):
    """Read-only monospace text widget for EXPLAIN / EXPLAIN ANALYZE output."""

    def __init__(self, text: str, label: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(f"  <b>{label}</b>")
        title.setStyleSheet("font-size: 11px; padding: 4px 6px;")
        layout.addWidget(title)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(text)
        font = QFont("Courier New", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        editor.setFont(font)
        layout.addWidget(editor)


# ═══════════════════════════════════════════════════════════════════════ #
#  ErrorResult                                                            #
# ═══════════════════════════════════════════════════════════════════════ #

class ErrorResult(QWidget):
    """
    Inline error display shown as a result tab.

    Replaces blocking StyledMessageBox.critical so the user can keep working
    and refer back to the error without re-running.
    """

    def __init__(self, message: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("⚠  Query Error")
        title.setStyleSheet(
            "color: #ef5350; font-size: 14px; font-weight: bold; padding-bottom: 6px;"
        )
        layout.addWidget(title)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(message)
        font = QFont("Courier New", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        text.setFont(font)
        text.setStyleSheet("color: #ef9a9a;")
        layout.addWidget(text)
