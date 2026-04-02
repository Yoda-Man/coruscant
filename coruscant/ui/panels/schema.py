"""
coruscant.ui.panels.schema
~~~~~~~~~~~~~~~~~~~~~~~~~~
Schema browser panel — displays a live tree of database objects.

Tree layout
-----------
  schema (bold)
    ├── table_name  [T]
    │     ├── Columns (n)
    │     │     col_name   data_type
    │     ├── Indexes (n)
    │     │     index_name   (hover for definition)
    │     └── Foreign Keys (n)
    │           fk_name      (hover for definition)
    └── Functions / Procedures (n)
          fn_name   return_type

Interactions
------------
Double-clicking a table emits ``insert_sql`` with a SELECT template.
Double-clicking a function emits ``insert_sql`` with a SELECT call template.
Right-clicking a table shows a context menu with three script generators:
  • SELECT script — all columns, WHERE placeholder, LIMIT 100
  • UPDATE script — SET clause for every column, WHERE placeholder
  • DELETE script — WHERE clause seeded with the first column

All three emit ``insert_sql``; the script is inserted at the cursor in the
active editor tab but not executed.

Logging
-------
Schema refresh start and completion (schemas/tables count) are logged at
INFO.  Errors from the background worker are logged at ERROR.  Any
unexpected exception during tree construction is caught, logged at ERROR
with a full traceback, and surfaced as a status-bar message so the UI
never silently stalls.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTreeWidget, QTreeWidgetItem, QStackedWidget, QMenu,
)
from PySide6.QtCore import Qt, Signal, QThread

from coruscant.core.database import DatabaseManager

log = logging.getLogger(__name__)


class _SchemaWorker(QThread):
    """Fetches the schema tree in a background thread."""

    finished: Signal = Signal(list)
    error:    Signal = Signal(str)

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db = db

    def run(self) -> None:
        log.info("Schema refresh started")
        try:
            self.finished.emit(self._db.get_schema_tree())
        except Exception as exc:
            log.exception("Schema fetch failed")
            self.error.emit(str(exc))


class SchemaBrowser(QWidget):
    """Left-dock schema tree panel."""

    insert_sql: Signal = Signal(str)

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db     = db
        self._worker: _SchemaWorker | None = None
        self._build_ui()
        self._set_connected(False)

    # ── Construction ─────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Schema Browser</b>",
                                styleSheet="font-size: 11px;"))
        header.addStretch()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedHeight(22)
        self._refresh_btn.setStyleSheet("font-size: 10px; padding: 0 6px;")
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        self._stack = QStackedWidget()

        disconnected = QLabel("Not connected")
        disconnected.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disconnected.setStyleSheet("color: #888; font-size: 12px;")
        self._stack.addWidget(disconnected)   # index 0

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        self._tree.setColumnWidth(0, 160)
        self._tree.header().setStretchLastSection(True)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._stack.addWidget(self._tree)     # index 1

        layout.addWidget(self._stack)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #888; font-size: 10px;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

    # ── Public API ───────────────────────────────────────────────────── #

    def set_connected(self, connected: bool) -> None:
        self._set_connected(connected)
        if connected:
            self.refresh()

    def refresh(self) -> None:
        if not self._db.is_connected or (self._worker and self._worker.isRunning()):
            return
        self._status.setText("Loading…")
        self._refresh_btn.setEnabled(False)
        self._worker = _SchemaWorker(self._db, parent=self)
        self._worker.finished.connect(self._on_tree_loaded)
        self._worker.error.connect(self._on_tree_error)
        self._worker.start()

    # ── Private helpers ──────────────────────────────────────────────── #

    def _set_connected(self, connected: bool) -> None:
        self._stack.setCurrentIndex(1 if connected else 0)
        self._refresh_btn.setEnabled(connected)
        if not connected:
            self._tree.clear()
            self._status.setText("")

    @staticmethod
    def _make_bold(item: QTreeWidgetItem) -> None:
        f = item.font(0); f.setBold(True); item.setFont(0, f)

    @staticmethod
    def _make_italic(item: QTreeWidgetItem) -> None:
        f = item.font(0); f.setItalic(True); item.setFont(0, f)

    def _on_tree_loaded(self, tree: list) -> None:
        try:
            self._populate_tree(tree)
        except Exception:
            log.exception("Unexpected error while building schema tree")
            self._refresh_btn.setEnabled(True)
            self._status.setText("Error building tree — see log")

    def _populate_tree(self, tree: list) -> None:
        self._refresh_btn.setEnabled(True)
        self._status.setText("")
        self._tree.clear()

        table_count = sum(len(s.get("tables", [])) for s in tree)
        log.info("Schema loaded  schemas=%d  tables=%d", len(tree), table_count)

        for schema_info in tree:
            schema_name = schema_info["schema"]
            schema_item = QTreeWidgetItem([schema_name, "schema"])
            schema_item.setData(0, Qt.ItemDataRole.UserRole,
                                {"kind": "schema", "schema": schema_name})
            self._make_bold(schema_item)

            for tbl in schema_info.get("tables", []):
                tbl_item = self._make_table_item(schema_name, tbl)
                schema_item.addChild(tbl_item)

            fns = schema_info.get("functions", [])
            if fns:
                fn_group = QTreeWidgetItem(["Functions / Procedures", str(len(fns))])
                self._make_italic(fn_group)
                fn_group.setForeground(0, Qt.GlobalColor.gray)
                for fn in fns:
                    fn_item = QTreeWidgetItem([fn["name"], fn.get("return_type", "")])
                    fn_item.setData(0, Qt.ItemDataRole.UserRole, {
                        "kind": "function", "schema": schema_name, "name": fn["name"],
                    })
                    fn_item.setToolTip(
                        0,
                        f"{fn.get('type','FUNCTION')}  "
                        f"{schema_name}.{fn['name']}() → {fn.get('return_type','')}",
                    )
                    fn_item.setForeground(1, Qt.GlobalColor.gray)
                    fn_group.addChild(fn_item)
                schema_item.addChild(fn_group)

            self._tree.addTopLevelItem(schema_item)

        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item and item.childCount() <= 20:
                item.setExpanded(True)

    def _make_table_item(self, schema: str, tbl: dict) -> QTreeWidgetItem:
        name     = tbl["name"]
        ttype    = tbl.get("type", "")
        abbr     = "V" if "VIEW" in ttype.upper() else "T"
        tbl_item = QTreeWidgetItem([name, abbr])
        tbl_item.setData(0, Qt.ItemDataRole.UserRole,
                         {"kind": "table", "schema": schema, "table": name})
        tbl_item.setToolTip(0, f"{ttype}  {schema}.{name}")

        def _subgroup(label: str, items: list, item_fn, kind: str = "") -> QTreeWidgetItem | None:
            if not items:
                return None
            group = QTreeWidgetItem([label, str(len(items))])
            self._make_italic(group)
            group.setForeground(0, Qt.GlobalColor.gray)
            if kind:
                group.setData(0, Qt.ItemDataRole.UserRole, {"kind": kind})
            for data in items:
                child = item_fn(data)
                group.addChild(child)
            return group

        # Columns
        def _col(c: dict) -> QTreeWidgetItem:
            ci = QTreeWidgetItem([c["name"], c.get("type", "")])
            ci.setData(0, Qt.ItemDataRole.UserRole,
                       {"kind": "column", "schema": schema, "table": name, "column": c["name"]})
            ci.setForeground(1, Qt.GlobalColor.gray)
            return ci

        # Indexes
        def _idx(i: dict) -> QTreeWidgetItem:
            ii = QTreeWidgetItem([i["name"], "idx"])
            ii.setToolTip(0, i.get("definition", ""))
            ii.setForeground(1, Qt.GlobalColor.gray)
            return ii

        # Foreign keys
        def _fk(f: dict) -> QTreeWidgetItem:
            fi = QTreeWidgetItem([f["name"], "fk"])
            fi.setToolTip(0, f.get("definition", ""))
            fi.setForeground(1, Qt.GlobalColor.gray)
            return fi

        for grp in [
            _subgroup("Columns",      tbl.get("columns", []),      _col, "col_group"),
            _subgroup("Indexes",      tbl.get("indexes", []),      _idx),
            _subgroup("Foreign Keys", tbl.get("foreign_keys", []), _fk),
        ]:
            if grp:
                tbl_item.addChild(grp)

        return tbl_item

    def _on_tree_error(self, message: str) -> None:
        log.error("Schema load error: %s", message)
        self._refresh_btn.setEnabled(True)
        self._status.setText(f"Error: {message[:60]}")

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data.get("kind") == "table":
            s, t = data["schema"], data["table"]
            self.insert_sql.emit(f'SELECT * FROM "{s}"."{t}" LIMIT 100;')
        elif data.get("kind") == "function":
            s, n = data["schema"], data["name"]
            self.insert_sql.emit(f'SELECT "{s}"."{n}"();')

    def _on_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("kind") != "table":
            return

        schema = data["schema"]
        table  = data["table"]
        cols   = self._columns_for_item(item)

        menu = QMenu(self._tree)
        menu.addAction("SELECT script",  lambda: self.insert_sql.emit(self._sql_select(schema, table, cols)))
        menu.addAction("UPDATE script",  lambda: self.insert_sql.emit(self._sql_update(schema, table, cols)))
        menu.addAction("DELETE script",  lambda: self.insert_sql.emit(self._sql_delete(schema, table, cols)))
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    @staticmethod
    def _columns_for_item(table_item: QTreeWidgetItem) -> list[str]:
        """Walk the table item's children and return column names in order."""
        cols: list[str] = []
        for i in range(table_item.childCount()):
            group = table_item.child(i)
            if group:
                d = group.data(0, Qt.ItemDataRole.UserRole)
                if d and d.get("kind") == "col_group":
                    for j in range(group.childCount()):
                        col_item = group.child(j)
                        if col_item:
                            cd = col_item.data(0, Qt.ItemDataRole.UserRole)
                            if cd and cd.get("kind") == "column":
                                cols.append(cd["column"])
                    break
        return cols

    @staticmethod
    def _sql_select(schema: str, table: str, cols: list[str]) -> str:
        if cols:
            col_list = ",\n    ".join(f'"{c}"' for c in cols)
            return (
                f'SELECT\n    {col_list}\n'
                f'FROM "{schema}"."{table}"\n'
                f'WHERE \nLIMIT 100;'
            )
        return f'SELECT *\nFROM "{schema}"."{table}"\nWHERE \nLIMIT 100;'

    @staticmethod
    def _sql_update(schema: str, table: str, cols: list[str]) -> str:
        if cols:
            set_clause = ",\n    ".join(f'"{c}" = ' for c in cols)
            return (
                f'UPDATE "{schema}"."{table}"\nSET\n    {set_clause}\n'
                f'WHERE ;'
            )
        return f'UPDATE "{schema}"."{table}"\nSET\n    \nWHERE ;'

    @staticmethod
    def _sql_delete(schema: str, table: str, cols: list[str]) -> str:
        if cols:
            # Suggest filtering by the first column as a starting point
            first = cols[0]
            return f'DELETE FROM "{schema}"."{table}"\nWHERE "{first}" = ;'
        return f'DELETE FROM "{schema}"."{table}"\nWHERE ;'
