"""
coruscant.ui.widgets.editor
~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQL editor tab and its collapsible parameters panel.

  ParamsPanel  – %(name)s parameter substitution table
  EditorTab    – SQL editor + syntax highlighter + ParamsPanel

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QTableWidget,
)
from PySide6.QtGui import QFont

from coruscant.utils.highlighter import SQLHighlighter


# ═══════════════════════════════════════════════════════════════════════ #
#  ParamsPanel                                                            #
# ═══════════════════════════════════════════════════════════════════════ #

class ParamsPanel(QWidget):
    """
    Collapsible panel with a two-column table for %(name)s parameters.
    Hidden by default; toggled via EditorTab's header button.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.setVisible(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        hint = QLabel(
            "Parameters use <b>%(name)s</b> syntax in SQL.  "
            "Add rows and they will be substituted at execution time."
        )
        hint.setStyleSheet("font-size: 11px; color: #888;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setFixedHeight(130)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        for label, slot in [("Add Row", self._add_row), ("Remove Row", self._remove_row)]:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _add_row(self) -> None:
        self._table.insertRow(self._table.rowCount())

    def _remove_row(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)

    def toggle(self) -> None:
        self.setVisible(not self.isVisible())

    def get_params(self) -> dict[str, str]:
        """Return a ``{name: value}`` dict from the table rows."""
        params: dict[str, str] = {}
        for row in range(self._table.rowCount()):
            name_item  = self._table.item(row, 0)
            value_item = self._table.item(row, 1)
            name  = name_item.text().strip()  if name_item  else ""
            value = value_item.text()         if value_item else ""
            if name:
                params[name] = value
        return params


# ═══════════════════════════════════════════════════════════════════════ #
#  EditorTab                                                              #
# ═══════════════════════════════════════════════════════════════════════ #

class EditorTab(QWidget):
    """
    A single editor tab containing:
      • Header bar with a Parameters toggle button
      • Syntax-highlighted QPlainTextEdit
      • Collapsible ParamsPanel
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        hb = QHBoxLayout(header)
        hb.setContentsMargins(6, 2, 6, 2)
        hb.addWidget(QLabel("SQL Editor", styleSheet="color: #888; font-size: 11px;"))
        hb.addStretch()

        self._params_btn = QPushButton("Parameters ▸")
        self._params_btn.setCheckable(True)
        self._params_btn.setFixedHeight(20)
        self._params_btn.setStyleSheet("font-size: 10px; padding: 0 6px;")
        self._params_btn.toggled.connect(self._on_params_toggled)
        hb.addWidget(self._params_btn)
        layout.addWidget(header)

        # Editor
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "-- Enter SQL here.  Separate statements with semicolons.\n"
            "-- F5 (or ▶ Execute) runs all statements.\n\n"
            "SELECT * FROM my_table;\nSELECT count(*) FROM other_table;"
        )
        mono = QFont("Courier New", 11)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(mono)
        self.editor.setTabStopDistance(32)
        SQLHighlighter(self.editor.document())
        layout.addWidget(self.editor)

        # Params panel
        self.params_panel = ParamsPanel()
        layout.addWidget(self.params_panel)

    def _on_params_toggled(self, checked: bool) -> None:
        self.params_panel.setVisible(checked)
        self._params_btn.setText("Parameters ▾" if checked else "Parameters ▸")

    # ── Public API ───────────────────────────────────────────────────── #

    def get_sql(self) -> str:
        """Return the selection if any, otherwise the full editor content."""
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText().replace('\u2029', '\n')
        return self.editor.toPlainText()

    def has_selection(self) -> bool:
        return self.editor.textCursor().hasSelection()

    def set_sql(self, sql: str) -> None:
        self.editor.setPlainText(sql)

    def insert_sql(self, sql: str) -> None:
        self.editor.insertPlainText(sql)

    def get_params(self) -> dict[str, str]:
        return self.params_panel.get_params()
