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

Double-clicking a table emits ``insert_sql`` with a SELECT template.
Double-clicking a function emits ``insert_sql`` with a SELECT call template.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTreeWidget, QTreeWidgetItem, QStackedWidget,
)
from PySide6.QtCore import Qt, Signal, QThread

from coruscant.core.database import DatabaseManager


class _SchemaWorker(QThread):
    """Fetches the schema tree in a background thread."""

    finished: Signal = Signal(list)
    error:    Signal = Signal(str)

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db = db

    def run(self) -> None:
        try:
            self.finished.emit(self._db.get_schema_tree())
        except Exception as exc:
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
        self._refresh_btn.setEnabled(True)
        self._status.setText("")
        self._tree.clear()

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

        def _subgroup(label: str, items: list, item_fn) -> QTreeWidgetItem | None:
            if not items:
                return None
            group = QTreeWidgetItem([label, str(len(items))])
            self._make_italic(group)
            group.setForeground(0, Qt.GlobalColor.gray)
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
            _subgroup("Columns",      tbl.get("columns", []),      _col),
            _subgroup("Indexes",      tbl.get("indexes", []),      _idx),
            _subgroup("Foreign Keys", tbl.get("foreign_keys", []), _fk),
        ]:
            if grp:
                tbl_item.addChild(grp)

        return tbl_item

    def _on_tree_error(self, message: str) -> None:
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
