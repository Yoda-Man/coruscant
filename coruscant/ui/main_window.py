"""
coruscant.ui.main_window
~~~~~~~~~~~~~~~~~~~~~~~~
MainWindow — the application shell.

Responsibilities
----------------
  • Build and wire the toolbar, docks, and central split layout.
  • Translate toolbar actions into calls on DatabaseManager / QueryWorker.
  • Route worker signals to the appropriate result widgets.
  • Manage editor-tab lifecycle and keyboard navigation.

This class deliberately contains NO business logic.  SQL parsing, query
execution, and schema fetching all live in coruscant.core.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTabWidget, QSplitter,
    QLabel, QToolBar, QFileDialog, QMessageBox, QSpinBox,
    QDockWidget, QApplication, QSizePolicy,
)
from PySide6.QtCore import Qt, QSize, QSettings
from PySide6.QtGui import QAction, QKeySequence, QShortcut

from coruscant import __version__, __app_name__
from coruscant.core.database import DatabaseManager, QueryResult, CommandResult
from coruscant.core.worker import QueryWorker
from coruscant.core.sql import split_statements
from coruscant.ui.widgets.editor import EditorTab
from coruscant.ui.widgets.results import ResultGrid, MessageResult, ExplainResult, ErrorResult
from coruscant.ui.widgets.tab_bar import PinnableTabBar
from coruscant.ui.panels.schema import SchemaBrowser
from coruscant.ui.panels.history import HistoryPanel
from coruscant.ui.dialogs.connection import ConnectionDialog
import coruscant.utils.themes as themes

_SETTINGS_ORG = "Coruscant"
_SETTINGS_APP = "Coruscant"


class MainWindow(QMainWindow):
    """
    Application shell.  Coordinates between the core layer and UI widgets.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__}  v{__version__}")
        self.resize(1400, 860)

        self._db:             DatabaseManager   = DatabaseManager()
        self._worker:         QueryWorker | None = None
        self._explain_worker: QueryWorker | None = None
        self._tab_counter:    int               = 0
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)

        self._build_toolbar()
        self._build_left_dock()
        self._build_central()
        self._build_shortcuts()
        self._update_ui_state()
        self.statusBar().showMessage("Ready  –  not connected")

    # ================================================================== #
    #  UI construction                                                     #
    # ================================================================== #

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)

        def action(label: str, tip: str = "", shortcut: str = "",
                   checkable: bool = False) -> QAction:
            a = QAction(label, self)
            if tip:
                a.setToolTip(tip)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if checkable:
                a.setCheckable(True)
            return a

        # Connection
        self._act_connect    = action("Connect")
        self._act_disconnect = action("Disconnect")

        # Query execution
        self._act_execute   = action("▶  Execute",  "Execute (F5)", "F5")
        self._act_cancel    = action("⏹  Cancel",   "Cancel running query (Escape)", "Escape")
        self._act_explain   = action("Explain",     "EXPLAIN the first statement")
        self._act_explain_a = action("Explain+",    "EXPLAIN ANALYZE BUFFERS")

        # Editor
        self._act_format  = action("Format SQL", "Auto-format SQL (sqlparse)")
        self._act_clear   = action("Clear",      "Clear editor and unpinned results")
        self._act_open    = action("Open SQL…",  "Open a .sql file")
        self._act_save    = action("Save SQL…",  "Save editor content to a .sql file")
        self._act_new_tab = action("+ Tab",      "New editor tab  (Ctrl+T)")

        # Transaction
        self._act_autocommit = action("Auto-commit", checkable=True,
                                      tip="Uncheck for manual BEGIN/COMMIT/ROLLBACK")
        self._act_autocommit.setChecked(True)
        self._act_commit   = action("Commit",   "COMMIT the current transaction")
        self._act_rollback = action("Rollback", "ROLLBACK the current transaction")

        # Theme
        self._act_theme = action("🌙", "Toggle light / dark theme")

        # Wire signals
        self._act_connect.triggered.connect(self._on_connect)
        self._act_disconnect.triggered.connect(self._on_disconnect)
        self._act_execute.triggered.connect(self._on_execute)
        self._act_cancel.triggered.connect(self._on_cancel)
        self._act_explain.triggered.connect(lambda: self._on_explain(analyze=False))
        self._act_explain_a.triggered.connect(lambda: self._on_explain(analyze=True))
        self._act_format.triggered.connect(self._on_format_sql)
        self._act_clear.triggered.connect(self._on_clear)
        self._act_open.triggered.connect(self._on_open)
        self._act_save.triggered.connect(self._on_save)
        self._act_new_tab.triggered.connect(lambda: self._add_editor_tab())
        self._act_autocommit.toggled.connect(self._on_autocommit_toggled)
        self._act_commit.triggered.connect(self._on_commit)
        self._act_rollback.triggered.connect(self._on_rollback)
        self._act_theme.triggered.connect(self._on_toggle_theme)

        # Layout
        for a in (self._act_connect, self._act_disconnect):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self._act_execute, self._act_cancel,
                  self._act_explain, self._act_explain_a):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self._act_format, self._act_clear):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self._act_open, self._act_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self._act_new_tab)
        tb.addSeparator()
        for a in (self._act_autocommit, self._act_commit, self._act_rollback):
            tb.addAction(a)
        tb.addSeparator()

        tb.addWidget(QLabel("  Row limit: ", styleSheet="font-size: 11px;"))
        self._row_limit_spin = QSpinBox()
        self._row_limit_spin.setRange(0, 1_000_000)
        self._row_limit_spin.setValue(1000)
        self._row_limit_spin.setSpecialValueText("Unlimited")
        self._row_limit_spin.setFixedWidth(100)
        self._row_limit_spin.setToolTip("Maximum rows per SELECT result (0 = unlimited)")
        tb.addWidget(self._row_limit_spin)
        tb.addSeparator()

        tb.addAction(self._act_theme)
        tb.addSeparator()

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self._conn_label = QLabel("  ● Not connected  ")
        self._conn_label.setStyleSheet(
            "color: #e57373; font-weight: bold; padding-right: 10px;"
        )
        tb.addWidget(self._conn_label)

    def _build_left_dock(self) -> None:
        dock = QDockWidget("Database Explorer", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        splitter = QSplitter(Qt.Orientation.Vertical)

        self._schema_browser = SchemaBrowser(self._db)
        self._schema_browser.insert_sql.connect(self._on_schema_insert_sql)
        splitter.addWidget(self._schema_browser)

        self._history_panel = HistoryPanel()
        self._history_panel.query_selected.connect(self._on_history_selected)
        splitter.addWidget(self._history_panel)

        splitter.setSizes([400, 200])
        dock.setWidget(splitter)
        dock.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_central(self) -> None:
        central = QWidget()
        layout  = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Editor tab widget
        self._editor_tabs = QTabWidget()
        self._editor_tabs.setTabsClosable(True)
        self._editor_tabs.setMovable(True)
        self._editor_tabs.tabCloseRequested.connect(self._close_editor_tab)
        splitter.addWidget(self._editor_tabs)
        self._add_editor_tab()

        # Result area
        result_area = QWidget()
        rl = QVBoxLayout(result_area)
        rl.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel("Results will appear here after executing a query.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #555; font-size: 13px; padding: 40px;")
        rl.addWidget(self._placeholder)

        self._result_tabs = QTabWidget()
        self._result_tabs.setTabBar(PinnableTabBar())
        self._result_tabs.setTabsClosable(True)
        self._result_tabs.tabCloseRequested.connect(self._close_result_tab)
        self._result_tabs.hide()
        rl.addWidget(self._result_tabs)

        splitter.addWidget(result_area)
        splitter.setSizes([350, 450])
        layout.addWidget(splitter)
        self.setCentralWidget(central)

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Tab"),       self, activated=self._next_editor_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=self._prev_editor_tab)
        QShortcut(QKeySequence("Ctrl+W"),         self, activated=self._close_current_editor_tab)
        QShortcut(QKeySequence("Ctrl+T"),         self, activated=lambda: self._add_editor_tab())

    # ================================================================== #
    #  Editor tab management                                               #
    # ================================================================== #

    def _add_editor_tab(self, sql: str = "") -> EditorTab:
        self._tab_counter += 1
        tab = EditorTab()
        if sql:
            tab.set_sql(sql)
        idx = self._editor_tabs.addTab(tab, f"Query {self._tab_counter}")
        self._editor_tabs.setCurrentIndex(idx)
        tab.editor.setFocus()
        return tab

    def _current_editor_tab(self) -> EditorTab | None:
        return self._editor_tabs.currentWidget()  # type: ignore[return-value]

    def _close_editor_tab(self, index: int) -> None:
        if self._editor_tabs.count() > 1:
            self._editor_tabs.removeTab(index)
        else:
            tab = self._editor_tabs.widget(index)
            if isinstance(tab, EditorTab):
                tab.editor.clear()

    def _close_current_editor_tab(self) -> None:
        idx = self._editor_tabs.currentIndex()
        if idx >= 0:
            self._close_editor_tab(idx)

    def _next_editor_tab(self) -> None:
        n = self._editor_tabs.count()
        if n > 1:
            self._editor_tabs.setCurrentIndex(
                (self._editor_tabs.currentIndex() + 1) % n
            )

    def _prev_editor_tab(self) -> None:
        n = self._editor_tabs.count()
        if n > 1:
            self._editor_tabs.setCurrentIndex(
                (self._editor_tabs.currentIndex() - 1) % n
            )

    # ================================================================== #
    #  Result tab management                                               #
    # ================================================================== #

    def _tab_bar(self) -> PinnableTabBar:
        return self._result_tabs.tabBar()  # type: ignore[return-value]

    def _add_result_tab(self, widget: QWidget, title: str) -> int:
        idx = self._result_tabs.addTab(widget, title)
        self._tab_bar().on_tab_added(idx)
        return idx

    def _close_result_tab(self, index: int) -> None:
        self._tab_bar().on_tab_removed(index)
        self._result_tabs.removeTab(index)
        if self._result_tabs.count() == 0:
            self._result_tabs.hide()
            self._placeholder.show()

    def _clear_unpinned_result_tabs(self) -> None:
        i = 0
        while i < self._result_tabs.count():
            if self._tab_bar().is_pinned(i):
                i += 1
            else:
                self._tab_bar().on_tab_removed(i)
                self._result_tabs.removeTab(i)

    def _show_result_area(self) -> None:
        self._placeholder.hide()
        self._result_tabs.show()

    # ================================================================== #
    #  UI state                                                            #
    # ================================================================== #

    def _update_ui_state(self) -> None:
        """Enable / disable actions based on connection and worker state."""
        connected  = self._db.is_connected
        busy       = (
            (self._worker        is not None and self._worker.isRunning())
            or (self._explain_worker is not None and self._explain_worker.isRunning())
        )
        autocommit = self._act_autocommit.isChecked()

        self._act_connect.setEnabled(not connected)
        self._act_disconnect.setEnabled(connected and not busy)
        self._act_execute.setEnabled(connected and not busy)
        self._act_cancel.setEnabled(connected and busy)
        self._act_explain.setEnabled(connected and not busy)
        self._act_explain_a.setEnabled(connected and not busy)
        self._act_autocommit.setEnabled(connected and not busy)
        self._act_commit.setEnabled(connected and not busy and not autocommit)
        self._act_rollback.setEnabled(connected and not busy and not autocommit)
        self._schema_browser._refresh_btn.setEnabled(connected and not busy)

        if connected:
            self._conn_label.setText("  ● Connected  ")
            self._conn_label.setStyleSheet(
                "color: #81c784; font-weight: bold; padding-right: 10px;"
            )
        else:
            self._conn_label.setText("  ● Not connected  ")
            self._conn_label.setStyleSheet(
                "color: #e57373; font-weight: bold; padding-right: 10px;"
            )

    # ================================================================== #
    #  Toolbar handlers                                                    #
    # ================================================================== #

    def _on_connect(self) -> None:
        dlg = ConnectionDialog(self)
        if dlg.exec() != ConnectionDialog.DialogCode.Accepted:
            return
        params = dlg.get_params()
        try:
            self._db.connect(**params)
            self.statusBar().showMessage(
                f"Connected to {params['database']} on "
                f"{params['host']}:{params['port']}"
            )
            self._schema_browser.set_connected(True)
        except Exception as exc:
            QMessageBox.critical(self, "Connection Error",
                                 f"Could not connect:\n\n{exc}")
        self._update_ui_state()

    def _on_disconnect(self) -> None:
        self._db.disconnect()
        self.statusBar().showMessage("Disconnected.")
        self._schema_browser.set_connected(False)
        self._act_autocommit.setChecked(True)
        self._update_ui_state()

    def _on_cancel(self) -> None:
        self._db.cancel()
        self.statusBar().showMessage("Cancel requested…")

    def _on_execute(self) -> None:
        tab = self._current_editor_tab()
        if not tab:
            return
        sql = tab.get_sql().strip()
        if not sql:
            self.statusBar().showMessage("Nothing to execute.")
            return

        self._clear_unpinned_result_tabs()
        if self._result_tabs.count() == 0:
            self._placeholder.show()
            self._result_tabs.hide()

        self.statusBar().showMessage(
            "Executing selection…" if tab.has_selection() else "Executing…"
        )

        self._worker = QueryWorker(
            self._db, sql,
            row_limit=self._row_limit_spin.value(),
            params=tab.get_params() or None,
            parent=self,
        )
        self._worker.finished.connect(self._on_results)
        self._worker.error.connect(self._on_query_error)
        self._worker.cancelled.connect(self._on_query_cancelled)
        self._worker.finished.connect(lambda _: self._update_ui_state())
        self._worker.error.connect(lambda _: self._update_ui_state())
        self._worker.cancelled.connect(self._update_ui_state)
        self._update_ui_state()
        self._worker.start()

    def _on_explain(self, analyze: bool = False) -> None:
        tab = self._current_editor_tab()
        if not tab:
            return
        sql = tab.get_sql().strip()
        if not sql:
            self.statusBar().showMessage("Nothing to explain.")
            return

        stmts = split_statements(sql)
        if not stmts:
            return

        if analyze:
            explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {stmts[0]}"
            title       = "Explain+"
        else:
            explain_sql = f"EXPLAIN {stmts[0]}"
            title       = "Explain"

        self.statusBar().showMessage("Running EXPLAIN…")

        self._explain_worker = QueryWorker(self._db, explain_sql, parent=self)
        self._explain_worker.finished.connect(
            lambda results: self._on_explain_results(results, title)
        )
        self._explain_worker.error.connect(self._on_query_error)
        self._explain_worker.cancelled.connect(self._on_query_cancelled)
        self._explain_worker.finished.connect(lambda _: self._update_ui_state())
        self._explain_worker.error.connect(lambda _: self._update_ui_state())
        self._explain_worker.cancelled.connect(self._update_ui_state)
        self._update_ui_state()
        self._explain_worker.start()

    def _on_autocommit_toggled(self, checked: bool) -> None:
        if not self._db.is_connected:
            return
        try:
            self._db.set_autocommit(checked)
            mode = "auto-commit" if checked else "manual transaction"
            self.statusBar().showMessage(f"Switched to {mode} mode.")
        except Exception as exc:
            QMessageBox.critical(self, "Transaction Mode Error", str(exc))
        self._update_ui_state()

    def _on_commit(self) -> None:
        try:
            self._db.commit()
            self.statusBar().showMessage("Transaction committed.")
        except Exception as exc:
            QMessageBox.critical(self, "Commit Error", str(exc))
        self._update_ui_state()

    def _on_rollback(self) -> None:
        try:
            self._db.rollback()
            self.statusBar().showMessage("Transaction rolled back.")
        except Exception as exc:
            QMessageBox.critical(self, "Rollback Error", str(exc))
        self._update_ui_state()

    def _on_format_sql(self) -> None:
        try:
            import sqlparse
        except ImportError:
            QMessageBox.warning(self, "sqlparse not installed",
                                "pip install sqlparse>=0.4")
            return
        tab = self._current_editor_tab()
        if not tab:
            return
        cursor       = tab.editor.textCursor()
        has_sel      = cursor.hasSelection()
        original     = (cursor.selectedText().replace('\u2029', '\n')
                        if has_sel else tab.editor.toPlainText())
        formatted    = sqlparse.format(
            original, reindent=True, keyword_case='upper',
            identifier_case='lower', strip_comments=False,
        )
        if has_sel:
            cursor.insertText(formatted)
        else:
            tab.editor.setPlainText(formatted)
        self.statusBar().showMessage("SQL formatted.")

    def _on_clear(self) -> None:
        tab = self._current_editor_tab()
        if tab:
            tab.editor.clear()
        self._clear_unpinned_result_tabs()
        if self._result_tabs.count() == 0:
            self._result_tabs.hide()
            self._placeholder.show()
        self.statusBar().showMessage("Editor cleared.")

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SQL File", "",
            "SQL files (*.sql);;Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            tab = self._current_editor_tab()
            if tab:
                tab.set_sql(content)
            self.statusBar().showMessage(f"Opened: {path}")
        except OSError as exc:
            QMessageBox.critical(self, "Open File", str(exc))

    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save SQL File", "",
            "SQL files (*.sql);;Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            tab     = self._current_editor_tab()
            content = tab.editor.toPlainText() if tab else ""
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.statusBar().showMessage(f"Saved: {path}")
        except OSError as exc:
            QMessageBox.critical(self, "Save File", str(exc))

    def _on_toggle_theme(self) -> None:
        app     = QApplication.instance()
        current = themes.current_theme(self._settings)
        if current == "dark":
            themes.apply_light(app)
            themes.save_theme(self._settings, "light")
            self._act_theme.setText("☀")
            self._act_theme.setToolTip("Switch to dark theme")
        else:
            themes.apply_dark(app)
            themes.save_theme(self._settings, "dark")
            self._act_theme.setText("🌙")
            self._act_theme.setToolTip("Switch to light theme")

    # ================================================================== #
    #  Dock / panel signal handlers                                        #
    # ================================================================== #

    def _on_schema_insert_sql(self, sql: str) -> None:
        tab = self._current_editor_tab()
        if tab:
            tab.insert_sql(sql)

    def _on_history_selected(self, sql: str) -> None:
        tab = self._current_editor_tab()
        if tab:
            tab.set_sql(sql)

    # ================================================================== #
    #  Worker result handlers                                              #
    # ================================================================== #

    def _on_results(self, results: list) -> None:
        self._show_result_area()

        result_count  = 0
        total_elapsed = 0.0

        for item in results:
            elapsed_ms     = item.elapsed_ms
            total_elapsed += elapsed_ms

            if isinstance(item, QueryResult):
                grid  = ResultGrid(item.columns, item.rows,
                                   label=item.label, truncated=item.truncated)
                title = f"{item.label}  ({elapsed_ms:.0f} ms, {len(item.rows):,} rows)"
                self._add_result_tab(grid, title)
                result_count += 1
            elif isinstance(item, CommandResult):
                msg   = MessageResult(item.message, item.label)
                title = f"{item.label}  ({elapsed_ms:.0f} ms)"
                self._add_result_tab(msg, title)

        if self._result_tabs.count() > 0:
            self._result_tabs.setCurrentIndex(0)

        # Add to history
        tab = self._current_editor_tab()
        if tab:
            full_sql = tab.editor.toPlainText().strip()
            if full_sql:
                self._history_panel.add_entry(full_sql, total_elapsed)

        self.statusBar().showMessage(
            f"Executed {len(results)} statement(s)  –  "
            f"{result_count} result set(s)  –  "
            f"total {total_elapsed:.0f} ms"
        )

    def _on_explain_results(self, results: list, title: str) -> None:
        for item in results:
            if isinstance(item, QueryResult) and item.rows:
                plan_text = "\n".join(str(row[0]) for row in item.rows)
                self._show_result_area()
                idx = self._add_result_tab(ExplainResult(plan_text, title), title)
                self._result_tabs.setCurrentIndex(idx)
                self.statusBar().showMessage("EXPLAIN complete.")
                return

    def _on_query_error(self, message: str) -> None:
        """Show the error inline as a result tab — no blocking modal."""
        self._show_result_area()
        idx = self._add_result_tab(ErrorResult(message), "⚠ Error")
        self._result_tabs.setCurrentIndex(idx)
        self.statusBar().showMessage("Query failed — see Error tab.")
        self._update_ui_state()

    def _on_query_cancelled(self) -> None:
        self.statusBar().showMessage("Query cancelled.")
        self._update_ui_state()
