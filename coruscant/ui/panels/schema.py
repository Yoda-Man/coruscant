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
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QLabel, QTreeWidget, QTreeWidgetItem, QStackedWidget, QMenu,
    QHeaderView,
)
from PySide6.QtCore import Qt, Signal, QThread, QSettings
from PySide6.QtGui import QColor

from coruscant.core.database import DatabaseManager
from coruscant.ui.style import header_button_style, SPACE_XS, HEIGHT_HEADER_BTN

log = logging.getLogger(__name__)


class _MindMapWorker(QThread):
    """Generates a mind-map HTML in a background thread."""

    finished: Signal = Signal(str, str, str)   # schema, focus_table, html
    error:    Signal = Signal(str)

    def __init__(self, db: DatabaseManager, schema: str,
                 focus_table: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._db          = db
        self._schema      = schema
        self._focus_table = focus_table

    def run(self) -> None:
        from coruscant.core.mind_map_generator import generate_mind_map
        log.info("Mind map started  schema=%s  focus=%s", self._schema, self._focus_table or "—")
        try:
            html = generate_mind_map(
                self._db._conn,   # type: ignore[union-attr]
                self._schema,
                self._focus_table,
            )
            self.finished.emit(self._schema, self._focus_table or "", html)
        except Exception as exc:
            log.exception("Mind map generation failed")
            self.error.emit(str(exc))


class _QAWorker(QThread):
    """Runs the QA engine in a background thread."""

    finished: Signal = Signal(object)   # QAReport
    error:    Signal = Signal(str)

    def __init__(self, db: DatabaseManager, schema: str, parent=None) -> None:
        super().__init__(parent)
        self._db     = db
        self._schema = schema

    def run(self) -> None:
        from coruscant.core.qa_engine import run_qa
        log.info("QA analysis started  schema=%s", self._schema)
        try:
            report = run_qa(self._db._conn, self._schema)  # type: ignore[union-attr]
            self.finished.emit(report)
        except Exception as exc:
            log.exception("QA engine failed for schema %s", self._schema)
            self.error.emit(str(exc))


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

    insert_sql:              Signal = Signal(str)
    schema_loaded:           Signal = Signal(list)   # list[str] of all identifiers
    autocomplete_changed:    Signal = Signal(bool)
    autoclose_changed:       Signal = Signal(bool)
    guide_requested:         Signal = Signal()
    about_requested:         Signal = Signal()
    scripts_requested:       Signal = Signal()
    line_numbers_changed:    Signal = Signal(bool)
    search_scripts_requested: Signal = Signal(str)  # query string → open Script Manager

    def __init__(self, db: DatabaseManager, parent=None) -> None:
        super().__init__(parent)
        self._db            = db
        self._worker:       _SchemaWorker  | None = None
        self._qa_worker:    _QAWorker      | None = None
        self._mm_worker:    _MindMapWorker | None = None
        self._qsettings = QSettings("Coruscant", "Coruscant")
        self._build_ui()
        self._set_connected(False)

    # ── Construction ─────────────────────────────────────────────────── #

    def _make_header_button(self, label: str, tip: str,
                            checkable: bool = False) -> QPushButton:
        """Create a header button with the shared, consistent header style."""
        btn = QPushButton(label)
        btn.setFixedHeight(HEIGHT_HEADER_BTN)
        btn.setStyleSheet(header_button_style())
        btn.setToolTip(tip)
        if checkable:
            btn.setCheckable(True)
        return btn

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_XS, SPACE_XS, SPACE_XS, SPACE_XS)
        layout.setSpacing(SPACE_XS)

        header = QHBoxLayout()
        header.setSpacing(SPACE_XS)
        header.addWidget(QLabel("<b>Schema Browser</b>",
                                styleSheet="font-size: 11px;"))
        header.addStretch()

        # All header controls share one consistent style (see coruscant.ui.style).
        self._refresh_btn = self._make_header_button(
            "↻ Refresh", "Reload the schema tree")
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn)

        self._scripts_btn = self._make_header_button(
            "📜 Scripts", "Open Support Script Manager")
        self._scripts_btn.clicked.connect(lambda: self.scripts_requested.emit())
        header.addWidget(self._scripts_btn)

        self._settings_btn = self._make_header_button(
            "⚙ Settings", "Toggle the settings panel", checkable=True)
        self._settings_btn.clicked.connect(self._toggle_settings_panel)
        header.addWidget(self._settings_btn)

        self._guide_btn = self._make_header_button(
            "📖 Guide", "Open the Coruscant quick-reference guide")
        self._guide_btn.clicked.connect(lambda: self.guide_requested.emit())
        header.addWidget(self._guide_btn)

        self._about_btn = self._make_header_button(
            "ℹ About", "About Coruscant — version, licence, and credits")
        self._about_btn.clicked.connect(lambda: self.about_requested.emit())
        header.addWidget(self._about_btn)
        layout.addLayout(header)

        # ── Settings panel (hidden by default) ──────────────────────── #
        self._settings_panel = QWidget()
        self._settings_panel.setVisible(False)
        self._settings_panel.setStyleSheet(
            "QWidget { background: #1a1a2e; border: 1px solid #2e2e4e;"
            " border-radius: 4px; padding: 2px; }"
            " QCheckBox { color: #cdd6f4; font-size: 11px; border: none; }"
        )
        sp_layout = QVBoxLayout(self._settings_panel)
        sp_layout.setContentsMargins(8, 6, 8, 6)
        sp_layout.setSpacing(6)

        self._autocomplete_cb = QCheckBox("Auto-complete")
        self._autocomplete_cb.setChecked(
            self._qsettings.value("settings/autocomplete", True, type=bool)
        )
        self._autocomplete_cb.toggled.connect(self._on_autocomplete_toggled)
        sp_layout.addWidget(self._autocomplete_cb)

        self._autoclose_cb = QCheckBox("Auto-close cell viewer after copy")
        self._autoclose_cb.setChecked(
            self._qsettings.value("settings/autoclose_cell_viewer", True, type=bool)
        )
        self._autoclose_cb.toggled.connect(self._on_autoclose_toggled)
        sp_layout.addWidget(self._autoclose_cb)

        self._linenumbers_cb = QCheckBox("Line numbers in editor")
        self._linenumbers_cb.setChecked(
            self._qsettings.value("settings/line_numbers", True, type=bool)
        )
        self._linenumbers_cb.toggled.connect(self._on_line_numbers_toggled)
        sp_layout.addWidget(self._linenumbers_cb)

        self._auto_qa_cb = QCheckBox("Run QA Engine on connect")
        self._auto_qa_cb.setChecked(
            self._qsettings.value("settings/auto_qa", False, type=bool)
        )
        self._auto_qa_cb.toggled.connect(self._on_auto_qa_toggled)
        sp_layout.addWidget(self._auto_qa_cb)

        layout.addWidget(self._settings_panel)

        self._stack = QStackedWidget()

        disconnected = QLabel("Not connected")
        disconnected.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disconnected.setStyleSheet("color: #888; font-size: 12px;")
        self._stack.addWidget(disconnected)   # index 0

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        _tree_font = self._tree.font()
        _tree_font.setPointSize(_tree_font.pointSize() + 1)
        self._tree.setFont(_tree_font)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setStretchLastSection(False)
        self._tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        can_act = self._db.is_connected or self._db.has_last_params
        if not can_act or (self._worker and self._worker.isRunning()):
            return
        self._status.setText("Loading…")
        self._refresh_btn.setEnabled(False)
        self._worker = _SchemaWorker(self._db, parent=self)
        self._worker.finished.connect(self._on_tree_loaded)
        self._worker.error.connect(self._on_tree_error)
        self._worker.start()

    # ── Private helpers ──────────────────────────────────────────────── #

    def _toggle_settings_panel(self, checked: bool) -> None:
        self._settings_panel.setVisible(checked)

    def _on_autocomplete_toggled(self, checked: bool) -> None:
        self._qsettings.setValue("settings/autocomplete", checked)
        self.autocomplete_changed.emit(checked)

    def _on_autoclose_toggled(self, checked: bool) -> None:
        self._qsettings.setValue("settings/autoclose_cell_viewer", checked)
        self.autoclose_changed.emit(checked)

    def _on_line_numbers_toggled(self, checked: bool) -> None:
        self._qsettings.setValue("settings/line_numbers", checked)
        self.line_numbers_changed.emit(checked)

    def _on_auto_qa_toggled(self, checked: bool) -> None:
        self._qsettings.setValue("settings/auto_qa", checked)

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
            return

        # Auto-QA: run on the first schema after connect if setting is on
        if (self._qsettings.value("settings/auto_qa", False, type=bool)
                and tree and self._db.is_connected):
            first_schema = tree[0]["schema"]
            log.info("Auto-QA triggered for schema=%s", first_schema)
            self._run_qa(first_schema)

    def _populate_tree(self, tree: list) -> None:
        self._refresh_btn.setEnabled(True)
        self._status.setText("")
        self._tree.clear()

        table_count = sum(len(s.get("tables", [])) for s in tree)
        log.info("Schema loaded  schemas=%d  tables=%d", len(tree), table_count)

        identifiers: set[str] = set()

        for schema_info in tree:
            schema_name = schema_info["schema"]
            schema_item = QTreeWidgetItem([schema_name, "schema"])
            schema_item.setData(0, Qt.ItemDataRole.UserRole,
                                {"kind": "schema", "schema": schema_name})
            self._make_bold(schema_item)

            tbl_items: list[tuple[QTreeWidgetItem, str, str]] = []
            for tbl in schema_info.get("tables", []):
                tbl_item = self._make_table_item(schema_name, tbl)
                schema_item.addChild(tbl_item)
                tbl_items.append((tbl_item, schema_name, tbl["name"]))
                identifiers.add(tbl["name"])
                for col in tbl.get("columns", []):
                    identifiers.add(col["name"])

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
                    identifiers.add(fn["name"])
                schema_item.addChild(fn_group)

            self._tree.addTopLevelItem(schema_item)

            # Add SELECT buttons now that items are in the tree
            for tbl_item, sname, tname in tbl_items:
                self._add_select_button(tbl_item, sname, tname)

        self.schema_loaded.emit(sorted(list(identifiers)))

        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item and item.childCount() <= 20:
                item.setExpanded(True)

    def _make_table_item(self, schema: str, tbl: dict) -> QTreeWidgetItem:
        name     = tbl["name"]
        ttype    = tbl.get("type", "")
        tbl_item = QTreeWidgetItem([name, ""])   # col 1 gets a ▶ SELECT button via setItemWidget
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

    def _add_select_button(self, item: QTreeWidgetItem, schema: str, table: str) -> None:
        """Set a compact SELECT button as the widget for column 1 of a table/view row."""
        btn = QPushButton("▶ SELECT")
        btn.setFixedHeight(18)
        btn.setStyleSheet(
            "QPushButton { font-size: 9px; padding: 0 4px;"
            " background: #1E3A5F; color: #90CAF9;"
            " border: 1px solid #2a5080; border-radius: 3px; }"
            "QPushButton:hover { background: #2a5a8f; }"
            "QPushButton:pressed { background: #1565C0; }"
        )
        btn.setToolTip(f'Append SELECT * FROM "{schema}"."{table}" LIMIT 100;')
        btn.clicked.connect(
            lambda _checked=False, s=schema, t=table:
                self.insert_sql.emit(f'SELECT * FROM "{s}"."{t}" LIMIT 100;')
        )
        self._tree.setItemWidget(item, 1, btn)

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
        if not data:
            return

        kind = data.get("kind")

        if kind == "schema":
            schema = data["schema"]
            menu = QMenu(self._tree)
            menu.addAction("Generate ERD",  lambda: self._generate_erd(schema))
            menu.addAction("\U0001f5fa Mind Map",   lambda: self._open_mind_map(schema, None))
            menu.addAction("\U0001f50d QA Engine",  lambda: self._run_qa(schema))
            menu.exec(self._tree.viewport().mapToGlobal(pos))
            return

        if kind != "table":
            return

        schema = data["schema"]
        table  = data["table"]
        cols   = self._columns_for_item(item)

        menu = QMenu(self._tree)
        menu.addAction("SELECT script",  lambda: self.insert_sql.emit(self._sql_select(schema, table, cols)))
        menu.addAction("UPDATE script",  lambda: self.insert_sql.emit(self._sql_update(schema, table, cols)))
        menu.addAction("DELETE script",  lambda: self.insert_sql.emit(self._sql_delete(schema, table, cols)))
        menu.addSeparator()
        menu.addAction("\U0001f5fa Mind Map from here", lambda: self._open_mind_map(schema, table))
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _open_mind_map(self, schema: str, focus_table: str | None) -> None:
        """Generate a D3 mind map for *schema*, optionally focused on *focus_table*."""
        if not self._db.is_connected:
            self._status.setText("Not connected — cannot generate mind map")
            return
        if self._mm_worker and self._mm_worker.isRunning():
            self._status.setText("Mind map already generating…")
            return
        label = f"'{focus_table}' in '{schema}'" if focus_table else f"'{schema}'"
        self._status.setText(f"Generating mind map for {label}…")
        self._mm_worker = _MindMapWorker(self._db, schema, focus_table, parent=self)
        self._mm_worker.finished.connect(self._on_mind_map_finished)
        self._mm_worker.error.connect(self._on_mind_map_error)
        self._mm_worker.start()

    def _on_mind_map_finished(self, schema: str, focus_table: str, html: str) -> None:
        import tempfile
        import webbrowser
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8",
            prefix=f"coruscant_mm_{schema}_",
        ) as fh:
            fh.write(html)
            tmp_path = fh.name
        webbrowser.open(tmp_path)
        label = f"'{focus_table}'" if focus_table else "all tables"
        self._status.setText(f"Mind map opened for {label}")

    def _on_mind_map_error(self, message: str) -> None:
        log.error("Mind map error: %s", message)
        self._status.setText(f"Mind map error: {message[:60]}")

    def _run_qa(self, schema: str) -> None:
        """Launch the QA engine in a background thread for *schema*."""
        if not self._db.is_connected:
            self._status.setText("Not connected — cannot run QA")
            return
        if self._qa_worker and self._qa_worker.isRunning():
            self._status.setText("QA analysis already running…")
            return
        self._status.setText(f"Running QA on '{schema}'…")
        self._qa_worker = _QAWorker(self._db, schema, parent=self)
        self._qa_worker.finished.connect(lambda report: self._on_qa_finished(report))
        self._qa_worker.error.connect(self._on_qa_error)
        self._qa_worker.start()

    def _on_qa_finished(self, report) -> None:
        from coruscant.ui.dialogs.qa_dialog import QADialog
        score = report.health_score
        self._status.setText(
            f"QA complete — health {score}  "
            f"({report.error_count}✖ {report.warning_count}⚠ {report.info_count}ℹ)"
        )
        color = "#81c784" if score >= 80 else "#ffa726" if score >= 50 else "#ef4444"
        self._status.setStyleSheet(f"color: {color}; font-size: 10px;")
        dlg = QADialog(report, parent=self)
        dlg.send_to_editor.connect(self.insert_sql.emit)
        dlg.search_scripts_requested.connect(self.search_scripts_requested.emit)
        dlg.finished.connect(
            lambda: self._status.setStyleSheet("color: #888; font-size: 10px;")
        )
        dlg.exec()

    def _on_qa_error(self, message: str) -> None:
        log.error("QA engine error: %s", message)
        self._status.setStyleSheet("color: #ef4444; font-size: 10px;")
        self._status.setText(f"QA error: {message[:60]}")

    def _generate_erd(self, schema: str) -> None:
        """Generate a Mermaid ER diagram for all tables in *schema* and open in browser."""
        import tempfile
        import webbrowser

        if not self._db.is_connected:
            self._status.setText("Not connected — cannot generate ERD")
            return

        try:
            conn = self._db._conn
            with conn.cursor() as cur:  # type: ignore[union-attr]
                # Columns with primary-key flag
                cur.execute("""
                    SELECT
                        c.table_name,
                        c.column_name,
                        c.data_type,
                        CASE WHEN pk.column_name IS NOT NULL THEN 'PK' ELSE '' END AS is_pk
                    FROM information_schema.columns c
                    LEFT JOIN (
                        SELECT ku.table_name, ku.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage ku
                            ON tc.constraint_name = ku.constraint_name
                           AND tc.table_schema    = ku.table_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_schema    = %s
                    ) pk ON c.table_name = pk.table_name
                         AND c.column_name = pk.column_name
                    WHERE c.table_schema = %s
                    ORDER BY c.table_name, c.ordinal_position
                """, (schema, schema))
                col_rows = cur.fetchall()

                # Foreign-key relationships (one row per table pair)
                cur.execute("""
                    SELECT
                        tc.table_name      AS child_table,
                        ccu.table_name     AS parent_table
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.constraint_column_usage AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                       AND ccu.table_schema    = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema    = %s
                    GROUP BY tc.table_name, ccu.table_name
                """, (schema,))
                fk_rows = cur.fetchall()

        except Exception as exc:
            log.error("ERD generation failed: %s", exc)
            self._status.setText(f"ERD error: {exc}")
            return

        # Build table -> [(col_name, data_type, is_pk)]
        tables: dict[str, list[tuple[str, str, str]]] = {}
        for table_name, col_name, data_type, is_pk in col_rows:
            tables.setdefault(table_name, []).append((col_name, data_type, is_pk))

        if not tables:
            self._status.setText(f"No tables found in schema '{schema}'")
            return

        def _safe(t: str) -> str:
            """Strip characters Mermaid doesn't allow in type names."""
            return (t.replace(" ", "_").replace("(", "").replace(")", "")
                     .replace(",", "").replace('"', ""))

        lines_mmd = ["erDiagram"]
        for tname in sorted(tables):
            lines_mmd.append(f"    {tname} {{")
            for col_name, data_type, is_pk in tables[tname]:
                pk_marker = " PK" if is_pk else ""
                lines_mmd.append(f"        {_safe(data_type)} {col_name}{pk_marker}")
            lines_mmd.append("    }")

        seen: set[tuple[str, str]] = set()
        for child_table, parent_table in fk_rows:
            pair = (parent_table, child_table)
            if pair not in seen and parent_table in tables and child_table in tables:
                seen.add(pair)
                lines_mmd.append(f'    {parent_table} ||--o{{{{ {child_table} : " "')

        mermaid = "\n".join(lines_mmd)

        n_tables = len(tables)
        n_rels   = len(seen)

        html = (
            "<!DOCTYPE html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "<meta charset=\"utf-8\">\n"
            f"<title>ERD — {schema}</title>\n"
            "<script src=\"https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js\"></script>\n"
            "<script src=\"https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js\"></script>\n"
            "<style>\n"
            "  * { box-sizing:border-box; margin:0; padding:0; }\n"
            "  body { background:#0d0d1a; color:#cdd6f4; font-family:system-ui,sans-serif;\n"
            "          padding:20px; height:100vh; display:flex; flex-direction:column; gap:10px; }\n"
            "  h2  { color:#89b4fa; font-size:17px; flex-shrink:0; }\n"
            "  .meta { color:#666; font-size:11px; flex-shrink:0; }\n"
            "  .toolbar { display:flex; gap:6px; flex-shrink:0; }\n"
            "  .toolbar button {\n"
            "    background:#1e1e2e; color:#cdd6f4; border:1px solid #313244;\n"
            "    border-radius:4px; padding:4px 14px; cursor:pointer; font-size:12px;\n"
            "  }\n"
            "  .toolbar button:hover { background:#313244; border-color:#89b4fa; }\n"
            "  #erd-wrap {\n"
            "    flex:1; background:#1a1a2e; border-radius:8px; border:1px solid #313244;\n"
            "    overflow:hidden; position:relative; min-height:0;\n"
            "  }\n"
            "  #erd-wrap svg { width:100%; height:100%; display:block; }\n"
            "  details { flex-shrink:0; }\n"
            "  summary { cursor:pointer; color:#89b4fa; font-size:12px; padding:4px 0; }\n"
            "  pre { background:#1e1e2e; color:#cdd6f4; padding:14px; border-radius:6px;\n"
            "         font-size:11px; overflow:auto; border:1px solid #313244; margin-top:6px;\n"
            "         max-height:200px; }\n"
            "</style>\n"
            "</head>\n"
            "<body>\n"
            f"<h2>ERD — {schema}</h2>\n"
            f"<p class=\"meta\">{n_tables} table(s) &nbsp;·&nbsp; {n_rels} relationship(s) &nbsp;·&nbsp;\n"
            "  Scroll to zoom &nbsp;·&nbsp; Drag to pan &nbsp;·&nbsp; Generated by Coruscant</p>\n"
            "<div class=\"toolbar\">\n"
            "  <button onclick=\"zoom(0.25)\">＋ Zoom in</button>\n"
            "  <button onclick=\"zoom(-0.25)\">－ Zoom out</button>\n"
            "  <button onclick=\"pz&&(pz.resetZoom(),pz.center())\">⊙ Reset</button>\n"
            "  <button onclick=\"pz&&pz.fit()\">⊞ Fit</button>\n"
            "</div>\n"
            "<div id=\"erd-wrap\">\n"
            "  <div class=\"mermaid\" style=\"width:100%;height:100%;\">\n"
            f"{mermaid}\n"
            "  </div>\n"
            "</div>\n"
            "<details>\n"
            "  <summary>▶ Mermaid source</summary>\n"
            f"  <pre>{mermaid}</pre>\n"
            "</details>\n"
            "<script>\n"
            "let pz = null;\n"
            "function zoom(delta) { if (!pz) return; pz.zoomBy(1 + delta); }\n"
            "mermaid.initialize({\n"
            "  startOnLoad: false, theme: 'dark',\n"
            "  er: { diagramPadding: 30, layoutDirection: 'TB', minEntityWidth: 100 }\n"
            "});\n"
            "async function init() {\n"
            "  try { await mermaid.run({ querySelector: '.mermaid' }); } catch(e) {}\n"
            "  const svg = document.querySelector('#erd-wrap svg');\n"
            "  if (!svg) return;\n"
            "  svg.removeAttribute('width'); svg.removeAttribute('height');\n"
            "  svg.style.width = '100%'; svg.style.height = '100%';\n"
            "  pz = svgPanZoom(svg, {\n"
            "    zoomEnabled: true, controlIconsEnabled: false,\n"
            "    fit: true, center: true, minZoom: 0.05, maxZoom: 50,\n"
            "    zoomScaleSensitivity: 0.3,\n"
            "  });\n"
            "  window.addEventListener('resize', () => { if (pz) { pz.resize(); pz.fit(); pz.center(); } });\n"
            "}\n"
            "document.addEventListener('DOMContentLoaded', init);\n"
            "</script>\n"
            "</body>\n"
            "</html>"
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8",
            prefix=f"coruscant_erd_{schema}_",
        ) as fh:
            fh.write(html)
            tmp_path = fh.name

        webbrowser.open(tmp_path)
        log.info("ERD generated  schema=%s  tables=%d  rels=%d  file=%s",
                 schema, n_tables, n_rels, tmp_path)
        self._status.setText(
            f"ERD opened — {n_tables} table(s), {n_rels} relationship(s)"
        )

    @staticmethod
    def _columns_for_item(table_item: QTreeWidgetItem) -> list[str]:
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
            first = cols[0]
            return f'DELETE FROM "{schema}"."{table}"\nWHERE "{first}" = ;'
        return f'DELETE FROM "{schema}"."{table}"\nWHERE ;'
