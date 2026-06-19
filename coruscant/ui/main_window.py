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
  • Persist and restore window geometry, dock positions, and splitter sizes
    across sessions via QSettings.
  • Log key lifecycle events (connect, disconnect, theme toggle, close).

This class deliberately contains NO business logic.  SQL parsing, query
execution, and schema fetching all live in coruscant.core.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTabWidget, QSplitter,
    QLabel, QToolBar, QFileDialog, QSpinBox, QPushButton,
    QDockWidget, QApplication, QSizePolicy, QStackedWidget, QHBoxLayout,
)
from coruscant.ui.dialogs.message import StyledMessageBox
from PySide6.QtCore import Qt, QSize, QSettings, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QCloseEvent

from coruscant import __version__, __app_name__
from coruscant.core.database import DatabaseManager, QueryResult, CommandResult
from coruscant.core.worker import QueryWorker
from coruscant.core.sql import split_statements, split_statements_with_positions
from coruscant.ui.widgets.editor import EditorTab
from coruscant.ui.widgets.results import ResultGrid, MessageResult, ExplainResult, ErrorResult
from coruscant.ui.widgets.tab_bar import PinnableTabBar, EditorTabBar
from coruscant.ui.panels.schema import SchemaBrowser
from coruscant.ui.panels.history import HistoryPanel
from coruscant.ui.dialogs.connection import ConnectionDialog
from coruscant.ui.dialogs.guide import ShortcutGuideDialog
from coruscant.ui.dialogs.about import AboutDialog
from coruscant.ui.dialogs.script_manager_dialog import ScriptManagerDialog
import coruscant.utils.themes as themes

log = logging.getLogger(__name__)

_SETTINGS_ORG = "Coruscant"
_SETTINGS_APP = "Coruscant"


class _GraphLoader(QThread):
    """
    Loads the saved Script Manager knowledge graph off the UI thread.

    The graph is a gzip-compressed JSON file that can be several megabytes;
    decoding it on the main thread freezes the UI the first time the Script
    Manager is opened.  Loading it in the background at startup means the
    dialog opens instantly later on.
    """

    loaded: Signal = Signal(object)   # ScriptKnowledgeGraph

    def run(self) -> None:
        try:
            from coruscant.core.script_manager import ScriptKnowledgeGraph
            graph = ScriptKnowledgeGraph.load()
        except Exception:
            log.exception("Background script-graph load failed")
            return
        self.loaded.emit(graph)


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
        self._schema_words:   list[str]         = []
        self._current_connection_name = ""
        # Run-all-tabs state
        self._run_all_queue: list  = []
        self._run_all_total: int   = 0
        # Script Manager knowledge graph — loaded lazily in the background.
        self._script_graph = None
        self._graph_loader: _GraphLoader | None = None

        self._build_toolbar()
        self._build_left_dock()
        self._build_central()
        self._build_shortcuts()
        self._update_ui_state()
        self.statusBar().showMessage("Ready  –  not connected")
        self._restore_geometry()
        self._prewarm_script_graph()

    def _prewarm_script_graph(self) -> None:
        """Start loading the Script Manager graph off the UI thread."""
        self._graph_loader = _GraphLoader(self)
        self._graph_loader.loaded.connect(self._on_script_graph_loaded)
        self._graph_loader.start()

    def _on_script_graph_loaded(self, graph) -> None:
        """Cache the background-loaded knowledge graph for instant dialog open."""
        self._script_graph = graph
        log.debug("Script graph pre-warmed: %d script(s)",
                  graph.stats().script_count)

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
        self._act_connect    = action("Connections", "Open saved connections")
        self._act_disconnect = action("Disconnect")

        # Query execution
        self._act_execute   = action("▶ Execute",
                                     "Execute current tab — selection or full  (Ctrl+Enter)")
        self._act_cancel    = action("⏹ Cancel",   "Cancel running query (Escape)", "Escape")
        self._act_explain   = action("Explain",     "EXPLAIN the first statement")
        self._act_explain_a = action("Explain+",    "EXPLAIN ANALYZE BUFFERS")

        # Editor
        self._act_format  = action("🪄 Format", "Auto-format SQL (sqlparse)")
        self._act_clear   = action("🧹 Clear",  "Clear editor and unpinned results")
        self._act_open    = action("📂 Open",   "Open a .sql file")
        self._act_save    = action("💾 Save",   "Save editor content to a .sql file")
        self._act_new_tab = action("＋ Tab",     "New editor tab  (Ctrl+T)")

        # Transaction
        self._act_autocommit = action("Auto-commit", checkable=True,
                                      tip="Uncheck for manual BEGIN/COMMIT/ROLLBACK")
        self._act_autocommit.setChecked(True)
        self._act_commit   = action("Commit",   "COMMIT the current transaction")
        self._act_rollback = action("Rollback", "ROLLBACK the current transaction")

        # Theme
        self._act_theme   = action("🌙",           "Toggle light / dark theme")

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
        self._row_limit_spin.setValue(100)
        self._row_limit_spin.setSpecialValueText("Unlimited")
        self._row_limit_spin.setFixedWidth(100)
        self._row_limit_spin.setToolTip("Maximum rows per SELECT result (0 = unlimited)")
        tb.addWidget(self._row_limit_spin)
        tb.addSeparator()

        tb.addAction(self._act_theme)

        self._style_toolbar_buttons(tb)
        self._build_status_bar()

    def _style_toolbar_buttons(self, tb: QToolBar) -> None:
        """Apply semantic color coding to each toolbar button."""

        def _ss(base: str, hover: str, pressed: str,
                bold: bool = False, text: str = "#ffffff") -> str:
            fw = "700" if bold else "400"
            return (
                f"QToolButton {{"
                f" background:{base}; color:{text}; border:none;"
                f" border-radius:4px; padding:5px 13px;"
                f" font-weight:{fw}; font-size:12px; min-width:46px;"
                f"}}"
                f"QToolButton:hover   {{ background:{hover}; }}"
                f"QToolButton:pressed {{ background:{pressed}; }}"
                f"QToolButton:checked {{ background:{pressed};"
                f" border:1px solid {hover}; }}"
                f"QToolButton:disabled {{ background:#1c1c1c;"
                f" color:#444; border:none; }}"
            )

        specs = [
            # (action,               base,      hover,     pressed,    bold)
            (self._act_connect,    "#1565C0", "#1976D2", "#0D47A1", True),
            (self._act_disconnect, "#B71C1C", "#C62828", "#7F0000", False),
            (self._act_execute,    "#1B5E20", "#2E7D32", "#145214", True),
            (self._act_cancel,     "#BF360C", "#D84315", "#8B1A00", False),
            (self._act_explain,    "#4A148C", "#6A1B9A", "#38006B", False),
            (self._act_explain_a,  "#880E4F", "#AD1457", "#6A0036", False),
            (self._act_format,     "#006064", "#00838F", "#004040", False),
            (self._act_clear,      "#4E342E", "#6D4C41", "#3E2723", False),
            (self._act_open,       "#37474F", "#455A64", "#263238", False),
            (self._act_save,       "#37474F", "#455A64", "#263238", False),
            (self._act_new_tab,    "#1A237E", "#283593", "#0D1442", False),
            (self._act_autocommit, "#1A3A4C", "#1E4D66", "#0F2233", False),
            (self._act_commit,     "#1B5E20", "#2E7D32", "#145214", False),
            (self._act_rollback,   "#B71C1C", "#C62828", "#7F0000", False),
            (self._act_theme,      "#212121", "#2D2D2D", "#0A0A0A", False),
        ]

        for act, base, hover, pressed, bold in specs:
            btn = tb.widgetForAction(act)
            if btn:
                btn.setStyleSheet(_ss(base, hover, pressed, bold))

    def _build_status_bar(self) -> None:
        """Permanent connection-status widget on the right of the status bar.

        Clicking the indicator opens the Connection Manager.
        The × button disconnects without going through the dialog.
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 8, 0)
        layout.setSpacing(2)

        self._sb_conn_btn = QPushButton("● Not connected")
        self._sb_conn_btn.setFlat(True)
        self._sb_conn_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sb_conn_btn.setToolTip("Click to open Connection Manager")
        self._sb_conn_btn.setStyleSheet(self._sb_style("#e57373"))
        self._sb_conn_btn.clicked.connect(self._on_connect)
        layout.addWidget(self._sb_conn_btn)

        self._sb_disconnect_btn = QPushButton("×")
        self._sb_disconnect_btn.setFlat(True)
        self._sb_disconnect_btn.setFixedSize(18, 18)
        self._sb_disconnect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sb_disconnect_btn.setToolTip("Disconnect")
        self._sb_disconnect_btn.setStyleSheet("""
            QPushButton { color:#666; font-size:13px; font-weight:bold;
                          border:none; background:transparent; padding:0; }
            QPushButton:hover { color:#e57373; }
        """)
        self._sb_disconnect_btn.clicked.connect(self._on_disconnect)
        self._sb_disconnect_btn.hide()
        layout.addWidget(self._sb_disconnect_btn)

        self.statusBar().addPermanentWidget(container)

    @staticmethod
    def _sb_style(color: str) -> str:
        return (
            f"QPushButton {{ color:{color}; font-weight:bold; font-size:11px;"
            f" border:none; background:transparent; padding:2px 6px; }}"
            f"QPushButton:hover {{ text-decoration:underline; }}"
        )

    def _build_left_dock(self) -> None:
        dock = QDockWidget("Database Explorer", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self._left_splitter = QSplitter(Qt.Orientation.Vertical)

        self._schema_browser = SchemaBrowser(self._db)
        self._schema_browser.insert_sql.connect(self._on_schema_insert_sql)
        self._schema_browser.schema_loaded.connect(self._on_schema_loaded)
        self._schema_browser.autocomplete_changed.connect(self._on_autocomplete_changed)
        self._schema_browser.line_numbers_changed.connect(self._on_line_numbers_changed)
        self._schema_browser.guide_requested.connect(self._on_guide_requested)
        self._schema_browser.about_requested.connect(self._on_about_requested)
        self._schema_browser.scripts_requested.connect(self._on_open_script_manager)
        self._schema_browser.search_scripts_requested.connect(
            self._on_search_scripts
        )
        self._left_splitter.addWidget(self._schema_browser)

        self._history_panel = HistoryPanel()
        self._history_panel.query_selected.connect(self._on_history_selected)
        self._left_splitter.addWidget(self._history_panel)

        self._left_splitter.setSizes([400, 200])
        dock.setWidget(self._left_splitter)
        dock.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_central(self) -> None:
        central = QWidget()
        layout  = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._central_splitter = QSplitter(Qt.Orientation.Vertical)

        # Editor tab widget
        self._editor_tabs = QTabWidget()
        self._editor_tabs.setTabsClosable(True)
        self._editor_tabs.setMovable(True)
        self._editor_tab_bar = EditorTabBar()
        self._editor_tabs.setTabBar(self._editor_tab_bar)
        self._editor_tab_bar.tab_manually_renamed.connect(
            self._on_editor_tab_manually_renamed
        )
        self._editor_tabs.tabCloseRequested.connect(self._close_editor_tab)
        self._editor_tabs.currentChanged.connect(self._on_editor_tab_changed)
        self._central_splitter.addWidget(self._editor_tabs)
        self._result_stack = QStackedWidget()
        self._central_splitter.addWidget(self._result_stack)

        self._add_editor_tab()

        self._central_splitter.setSizes([350, 450])
        layout.addWidget(self._central_splitter)
        self.setCentralWidget(central)

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Tab"),       self, activated=self._next_editor_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=self._prev_editor_tab)
        QShortcut(QKeySequence("Ctrl+W"),         self, activated=self._close_current_editor_tab)
        QShortcut(QKeySequence("Ctrl+T"),         self, activated=lambda: self._add_editor_tab())
        # Query execution shortcuts
        QShortcut(QKeySequence("F5"),             self, activated=self._on_run_all_tabs)
        QShortcut(QKeySequence("Ctrl+F5"),        self, activated=self._on_execute_at_cursor)
        QShortcut(QKeySequence("Ctrl+Return"),    self, activated=self._on_execute)

    # ================================================================== #
    #  Window lifecycle                                                    #
    # ================================================================== #

    def closeEvent(self, event: QCloseEvent) -> None:
        log.info("Application closing")
        self._save_geometry()
        if self._graph_loader and self._graph_loader.isRunning():
            self._graph_loader.wait(2000)
        if self._db.is_connected:
            self._db.disconnect()
        event.accept()

    def _save_geometry(self) -> None:
        self._settings.setValue("window/geometry",         self.saveGeometry())
        self._settings.setValue("window/state",            self.saveState())
        self._settings.setValue("window/central_splitter", self._central_splitter.saveState())
        self._settings.setValue("window/left_splitter",    self._left_splitter.saveState())
        log.debug("Window geometry saved")

    def _restore_geometry(self) -> None:
        if geom := self._settings.value("window/geometry"):
            self.restoreGeometry(geom)
        if state := self._settings.value("window/state"):
            self.restoreState(state)
        if central := self._settings.value("window/central_splitter"):
            self._central_splitter.restoreState(central)
        if left := self._settings.value("window/left_splitter"):
            self._left_splitter.restoreState(left)

    # ================================================================== #
    #  Editor tab management                                               #
    # ================================================================== #

    def _add_editor_tab(self, sql: str = "") -> EditorTab:
        self._tab_counter += 1
        tab = EditorTab()
        if sql:
            tab.set_sql(sql)

        # Create result area for this tab
        area, placeholder, res_tabs = self._create_result_area()
        tab.setProperty("result_area", area)
        tab.setProperty("result_placeholder", placeholder)
        tab.setProperty("result_tabs", res_tabs)
        self._result_stack.addWidget(area)

        idx = self._editor_tabs.addTab(tab, f"Query {self._tab_counter}")
        self._editor_tabs.setCurrentIndex(idx)
        
        if self._schema_words:
            tab.update_completer_words(self._schema_words)

        ac_enabled = self._settings.value("settings/autocomplete", True, type=bool)
        tab.set_autocomplete_enabled(ac_enabled)
        ln_enabled = self._settings.value("settings/line_numbers", True, type=bool)
        tab.set_line_numbers_enabled(ln_enabled)
        tab.set_dark_theme(themes.current_theme(self._settings) == "dark")

        tab.editor.setFocus()
        return tab

    def _create_result_area(self) -> tuple[QWidget, QLabel, QTabWidget]:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        placeholder = QLabel("Results will appear here after executing a query.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #555; font-size: 13px; padding: 40px;")
        layout.addWidget(placeholder)

        tabs = QTabWidget()
        tabs.setProperty("associated_placeholder", placeholder)
        tabs.setTabBar(PinnableTabBar())
        tabs.setTabsClosable(True)
        tabs.tabCloseRequested.connect(self._close_result_tab)
        tabs.hide()
        layout.addWidget(tabs)

        return container, placeholder, tabs

    def _on_editor_tab_changed(self, index: int) -> None:
        tab = self._editor_tabs.widget(index)
        if tab:
            area = tab.property("result_area")
            if area:
                self._result_stack.setCurrentWidget(area)

    def _current_result_widgets(self) -> tuple[QLabel, QTabWidget] | tuple[None, None]:
        tab = self._current_editor_tab()
        if not tab:
            return None, None
        return (tab.property("result_placeholder"),
                tab.property("result_tabs"))

    def _current_editor_tab(self) -> EditorTab | None:
        return self._editor_tabs.currentWidget()  # type: ignore[return-value]

    def _close_editor_tab(self, index: int) -> None:
        if self._editor_tabs.count() > 1:
            area = self._result_stack.widget(index)
            self._result_stack.removeWidget(area)
            if area:
                area.deleteLater()
            self._editor_tabs.removeTab(index)
        else:
            tab = self._editor_tabs.widget(index)
            if isinstance(tab, EditorTab):
                tab.editor.clear()
                # Also clear results for the last tab
                placeholder, tabs = self._current_result_widgets()
                if tabs and placeholder:
                    while tabs.count() > 0:
                        tabs.removeTab(0)
                    tabs.hide()
                    placeholder.show()

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

    def _tab_bar(self) -> PinnableTabBar | None:
        _, tabs = self._current_result_widgets()
        return tabs.tabBar() if tabs else None  # type: ignore[return-value]

    def _add_result_tab(self, widget: QWidget, title: str) -> int:
        _, tabs = self._current_result_widgets()
        if not tabs:
            return -1
        idx = tabs.addTab(widget, title)
        tabs.tabBar().on_tab_added(idx)  # type: ignore[attr-defined]
        return idx

    def _close_result_tab(self, index: int) -> None:
        tabs = self.sender()
        if not isinstance(tabs, QTabWidget):
            _, tabs = self._current_result_widgets()
        if not tabs:
            return

        placeholder = tabs.property("associated_placeholder")
        
        tabs.tabBar().on_tab_removed(index)  # type: ignore[attr-defined]
        tabs.removeTab(index)
        if tabs.count() == 0:
            tabs.hide()
            if placeholder:
                placeholder.show()

    def _clear_unpinned_result_tabs(self) -> None:
        _, tabs = self._current_result_widgets()
        if not tabs:
            return
        bar = tabs.tabBar()
        i = 0
        while i < tabs.count():
            if bar.is_pinned(i):  # type: ignore[attr-defined]
                i += 1
            else:
                bar.on_tab_removed(i)  # type: ignore[attr-defined]
                tabs.removeTab(i)

    def _show_result_area(self) -> None:
        placeholder, tabs = self._current_result_widgets()
        if placeholder:
            placeholder.hide()
        if tabs:
            tabs.show()

    # ================================================================== #
    #  UI state                                                            #
    # ================================================================== #

    def _update_ui_state(self) -> None:
        """Enable / disable actions based on connection and worker state."""
        connected     = self._db.is_connected
        can_reconnect = self._db.has_last_params
        can_act       = connected or can_reconnect

        busy = (
            (self._worker        is not None and self._worker.isRunning())
            or (self._explain_worker is not None and self._explain_worker.isRunning())
        )
        autocommit = self._act_autocommit.isChecked()

        # Connections stays visible so users can switch profiles without extra steps.
        self._act_connect.setVisible(True)
        self._act_disconnect.setVisible(connected)
        
        self._act_connect.setEnabled(not busy)
        self._act_disconnect.setEnabled(connected and not busy)
        
        self._act_execute.setEnabled(can_act and not busy)
        self._act_cancel.setEnabled(connected and busy)
        self._act_explain.setEnabled(can_act and not busy)
        self._act_explain_a.setEnabled(can_act and not busy)
        self._act_autocommit.setEnabled(can_act and not busy)
        self._act_commit.setEnabled(connected and not busy and not autocommit)
        self._act_rollback.setEnabled(connected and not busy and not autocommit)
        self._schema_browser._refresh_btn.setEnabled(can_act and not busy)

        if connected:
            name = self._current_connection_name or "Connected"
            self._sb_conn_btn.setText(f"● {name}")
            self._sb_conn_btn.setStyleSheet(self._sb_style("#81c784"))
            self._sb_disconnect_btn.show()
        elif can_reconnect:
            self._sb_conn_btn.setText("● Ready (auto-reconnect)")
            self._sb_conn_btn.setStyleSheet(self._sb_style("#ffa726"))
            self._sb_disconnect_btn.hide()
        else:
            self._sb_conn_btn.setText("● Not connected")
            self._sb_conn_btn.setStyleSheet(self._sb_style("#e57373"))
            self._sb_disconnect_btn.hide()

    # ================================================================== #
    #  Toolbar handlers                                                    #
    # ================================================================== #

    def _on_connect(self) -> None:
        dlg = ConnectionDialog(self)
        if dlg.exec() != ConnectionDialog.DialogCode.Accepted:
            return
        profile = dlg.get_profile()
        params = profile.connect_params()
        try:
            self._db.connect(**params)
            self._current_connection_name = profile.display_name
            self.statusBar().showMessage(
                f"Connected to {profile.display_name}: {params['database']} on "
                f"{params['host']}:{params['port']}"
            )
            self._schema_browser.set_connected(True)
        except Exception as exc:
            log.error("Connection rejected by UI: %s", exc)
            self._current_connection_name = ""
            self._schema_browser.set_connected(False)
            StyledMessageBox.critical(self, "Connection Error",
                                 f"Could not connect:\n\n{exc}")
        self._update_ui_state()

    def _on_disconnect(self) -> None:
        log.info("User initiated disconnect")
        self._db.disconnect()
        self._current_connection_name = ""
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
        placeholder, tabs = self._current_result_widgets()
        if tabs and tabs.count() == 0:
            if placeholder:
                placeholder.show()
            tabs.hide()

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
        if not self._db.is_connected and not self._db.has_last_params:
            return
        try:
            self._db.set_autocommit(checked)
            mode = "auto-commit" if checked else "manual transaction"
            self.statusBar().showMessage(f"Switched to {mode} mode.")
        except Exception as exc:
            StyledMessageBox.critical(self, "Transaction Mode Error", str(exc))
        self._update_ui_state()

    def _on_commit(self) -> None:
        try:
            self._db.commit()
            self.statusBar().showMessage("Transaction committed.")
        except Exception as exc:
            StyledMessageBox.critical(self, "Commit Error", str(exc))
        self._update_ui_state()

    def _on_rollback(self) -> None:
        try:
            self._db.rollback()
            self.statusBar().showMessage("Transaction rolled back.")
        except Exception as exc:
            StyledMessageBox.critical(self, "Rollback Error", str(exc))
        self._update_ui_state()

    def _on_results(self, results: list) -> None:
        self._clear_unpinned_result_tabs()
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

        _, tabs = self._current_result_widgets()
        if tabs and tabs.count() > 0:
            tabs.setCurrentIndex(0)

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
                _, tabs = self._current_result_widgets()
                if tabs:
                    tabs.setCurrentIndex(idx)
                self.statusBar().showMessage("EXPLAIN complete.")
                return

    def _on_query_error(self, message: str) -> None:
        self._show_result_area()
        idx = self._add_result_tab(ErrorResult(message), "⚠ Error")
        _, tabs = self._current_result_widgets()
        if tabs:
            tabs.setCurrentIndex(idx)
        self.statusBar().showMessage("Query failed — see Error tab.")
        self._update_ui_state()

    def _on_query_cancelled(self) -> None:
        self.statusBar().showMessage("Query cancelled.")
        self._update_ui_state()

    def _on_format_sql(self) -> None:
        try:
            import sqlparse
        except ImportError:
            StyledMessageBox.warning(self, "sqlparse not installed",
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
        placeholder, tabs = self._current_result_widgets()
        if tabs and placeholder and tabs.count() == 0:
            tabs.hide()
            placeholder.show()
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
            StyledMessageBox.critical(self, "Open File", str(exc))

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
            # Auto-rename the tab to the filename stem (unless the user has
            # manually renamed it — in that case we leave their name alone)
            tab_idx = self._editor_tabs.currentIndex()
            if tab and not tab.property("manually_named"):
                self._editor_tabs.setTabText(tab_idx, Path(path).stem)
        except OSError as exc:
            StyledMessageBox.critical(self, "Save File", str(exc))

    def _on_toggle_theme(self) -> None:
        app     = QApplication.instance()
        current = themes.current_theme(self._settings)
        if current == "dark":
            themes.apply_light(app)
            themes.save_theme(self._settings, "light")
            self._act_theme.setText("☀")
            self._act_theme.setToolTip("Switch to dark theme")
            log.info("Theme changed: dark → light")
        else:
            themes.apply_dark(app)
            themes.save_theme(self._settings, "dark")
            self._act_theme.setText("🌙")
            self._act_theme.setToolTip("Switch to light theme")
            log.info("Theme changed: light → dark")

        self._apply_editor_theme()

    def _apply_editor_theme(self) -> None:
        """Propagate the active theme to every editor tab's gutter."""
        dark = themes.current_theme(self._settings) == "dark"
        for i in range(self._editor_tabs.count()):
            tab = self._editor_tabs.widget(i)
            if isinstance(tab, EditorTab):
                tab.set_dark_theme(dark)

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

    def _on_schema_loaded(self, words: list[str]) -> None:
        self._schema_words = words
        for i in range(self._editor_tabs.count()):
            tab = self._editor_tabs.widget(i)
            if isinstance(tab, EditorTab):
                tab.update_completer_words(words)

    def _on_autocomplete_changed(self, enabled: bool) -> None:
        for i in range(self._editor_tabs.count()):
            tab = self._editor_tabs.widget(i)
            if isinstance(tab, EditorTab):
                tab.set_autocomplete_enabled(enabled)

    def _on_line_numbers_changed(self, enabled: bool) -> None:
        for i in range(self._editor_tabs.count()):
            tab = self._editor_tabs.widget(i)
            if isinstance(tab, EditorTab):
                tab.set_line_numbers_enabled(enabled)

    def _on_editor_tab_manually_renamed(self, idx: int) -> None:
        """Mark this editor tab so auto-naming on save will not override it."""
        tab = self._editor_tabs.widget(idx)
        if tab:
            tab.setProperty("manually_named", True)

    def _on_guide_requested(self) -> None:
        """Open the quick-reference guide dialog."""
        dlg = ShortcutGuideDialog(self)
        dlg.exec()

    def _on_about_requested(self) -> None:
        """Open the About dialog."""
        dlg = AboutDialog(self)
        dlg.exec()

    def _on_open_script_manager(self) -> None:
        """Open the Support Script Manager dialog."""
        dlg = ScriptManagerDialog(self, preloaded_graph=self._script_graph)
        dlg.script_selected.connect(self._on_script_manager_load)
        dlg.graph_updated.connect(self._on_script_graph_loaded)
        dlg.exec()

    def _on_script_manager_load(self, sql: str) -> None:
        """Insert a script from the Script Manager into the active editor."""
        tab = self._current_editor_tab()
        if tab:
            tab.set_sql(sql)
            self.statusBar().showMessage("Script loaded from Script Manager.")

    def _on_search_scripts(self, query: str) -> None:
        """Open Script Manager pre-populated with *query* (from QA Engine findings)."""
        from coruscant.core.script_manager import ScriptKnowledgeGraph
        g = (
            self._script_graph
            if self._script_graph is not None
            else ScriptKnowledgeGraph.load()
        )
        if g.stats().script_count == 0:
            StyledMessageBox.information(
                self,
                "No Scripts Loaded",
                "The Script Manager has no scripts indexed.\n\n"
                "Upload a ZIP archive of .sql scripts to enable this feature.",
            )
            return
        dlg = ScriptManagerDialog(self, preloaded_graph=g)
        dlg.script_selected.connect(self._on_script_manager_load)
        dlg.graph_updated.connect(self._on_script_graph_loaded)
        dlg.search_for_error(query, "")
        dlg.exec()

    def suggest_scripts_for_error(self, error_code: str, error_message: str = "") -> None:
        """
        Open the Script Manager pre-searched for *error_code*.
        Called automatically when a query fails with a recognisable SQLSTATE.
        """
        from coruscant.core.script_manager import ScriptKnowledgeGraph
        g = self._script_graph if self._script_graph is not None else ScriptKnowledgeGraph.load()
        if g.stats().script_count == 0:
            return   # nothing to suggest
        dlg = ScriptManagerDialog(self, preloaded_graph=g)
        dlg.script_selected.connect(self._on_script_manager_load)
        dlg.graph_updated.connect(self._on_script_graph_loaded)
        dlg.search_for_error(error_code, error_message)
        dlg.exec()


    # ================================================================== #
    #  Run-all and execute-at-cursor                                       #
    # ================================================================== #

    def _on_run_all_tabs(self) -> None:
        """F5 — execute every non-empty editor tab sequentially."""
        if not (self._db.is_connected or self._db.has_last_params):
            self.statusBar().showMessage("Not connected — cannot execute.")
            return
        if self._worker and self._worker.isRunning():
            self._db.cancel()
            self._run_all_queue.clear()

        self._run_all_queue = []
        for i in range(self._editor_tabs.count()):
            tab = self._editor_tabs.widget(i)
            if isinstance(tab, EditorTab):
                sql = tab.editor.toPlainText().strip()
                if sql:
                    self._run_all_queue.append((i, tab, sql))

        if not self._run_all_queue:
            self.statusBar().showMessage("No SQL to execute across tabs.")
            return

        self._run_all_total = len(self._run_all_queue)
        log.info("Run-all started  tabs=%d", self._run_all_total)
        self._advance_run_all()

    def _advance_run_all(self) -> None:
        """Pop the next tab from the queue and run it; stop when empty."""
        if not self._run_all_queue:
            self.statusBar().showMessage(
                f"All {self._run_all_total} tab(s) executed successfully."
            )
            self._update_ui_state()
            return

        tab_idx, tab, sql = self._run_all_queue.pop(0)
        self._editor_tabs.setCurrentIndex(tab_idx)
        done = self._run_all_total - len(self._run_all_queue)
        self.statusBar().showMessage(
            f"Executing tab {done}/{self._run_all_total}: "
            f"{self._editor_tabs.tabText(tab_idx)}..."
        )

        self._clear_unpinned_result_tabs()
        placeholder, tabs = self._current_result_widgets()
        if tabs and placeholder and tabs.count() == 0:
            placeholder.show()
            tabs.hide()

        self._worker = QueryWorker(
            self._db, sql,
            row_limit=self._row_limit_spin.value(),
            params=tab.get_params() or None,
            parent=self,
        )
        self._worker.finished.connect(self._on_results)
        self._worker.error.connect(self._on_query_error)
        self._worker.cancelled.connect(self._on_query_cancelled)
        self._worker.finished.connect(lambda _: self._advance_run_all())
        self._worker.error.connect(lambda _: self._run_all_queue.clear())
        self._worker.cancelled.connect(lambda: self._run_all_queue.clear())
        self._update_ui_state()
        self._worker.start()

    def _on_execute_at_cursor(self) -> None:
        """Ctrl+F5 — execute only the SQL statement the cursor is inside."""
        tab = self._current_editor_tab()
        if not tab:
            return
        if not (self._db.is_connected or self._db.has_last_params):
            self.statusBar().showMessage("Not connected — cannot execute.")
            return
        if self._worker and self._worker.isRunning():
            return

        full_sql   = tab.editor.toPlainText()
        cursor_pos = tab.editor.textCursor().position()
        sql        = self._statement_at_cursor(full_sql, cursor_pos)

        if not sql:
            self.statusBar().showMessage("No statement found at cursor position.")
            return

        self._clear_unpinned_result_tabs()
        placeholder, tabs = self._current_result_widgets()
        if tabs and placeholder and tabs.count() == 0:
            placeholder.show()
            tabs.hide()
        self.statusBar().showMessage("Executing statement at cursor...")

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

    @staticmethod
    def _statement_at_cursor(sql: str, pos: int) -> str | None:
        """Return the statement containing cursor position *pos*."""
        stmts = split_statements_with_positions(sql)
        if not stmts:
            return None
        for start, end, stmt in stmts:
            if start <= pos < end:
                return stmt
        # Fallback: nearest statement
        return min(stmts, key=lambda s: min(abs(pos - s[0]), abs(pos - s[1])))[2]
