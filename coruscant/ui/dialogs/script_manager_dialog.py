"""
coruscant.ui.dialogs.script_manager_dialog
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Script Manager dialog — upload, search, and load SQL support scripts.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import (
    Qt, QThread, Signal, QTimer, QSettings, QSize,
)
from PySide6.QtGui import QColor, QFont, QBrush
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QAbstractItemView, QMenu, QFileDialog,
    QSizePolicy, QSplitter, QPlainTextEdit, QFrame,
)

from coruscant.core.script_manager import (
    ScriptIngester, ScriptKnowledgeGraph, SearchResult, GraphStats,
)
from coruscant.ui.dialogs.message import StyledMessageBox
from coruscant.ui.style import script_manager_stylesheet

log = logging.getLogger(__name__)

_SETTINGS_ORG = "Coruscant"
_SETTINGS_APP = "Coruscant"
_GRAPH_KEY    = "script_manager/graph_path"
_WIN_GEO_KEY  = "script_manager/geometry"

# Full dialog stylesheet, assembled from the shared design tokens.
_DIALOG_STYLE = script_manager_stylesheet()


# ── Background worker ─────────────────────────────────────────────────── #

class _IngestionWorker(QThread):
    """Runs zip ingestion in a background thread."""

    progress: Signal = Signal(str, int, int)   # stage, current, total
    finished: Signal = Signal(object)           # ScriptKnowledgeGraph
    error:    Signal = Signal(str)

    def __init__(
        self,
        zip_path: str,
        existing: ScriptKnowledgeGraph | None,
        merge: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._zip_path = zip_path
        self._existing = existing
        self._merge    = merge
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        def _cb(stage: str, current: int, total: int) -> None:
            if self._cancelled:
                return
            self.progress.emit(stage, current, total)

        try:
            ingester = ScriptIngester()
            graph = ingester.ingest_zip(
                self._zip_path,
                existing_graph=self._existing,
                progress_cb=_cb,
                merge=self._merge,
            )
            if not self._cancelled:
                self.finished.emit(graph)
        except Exception as exc:
            log.exception("Ingestion failed")
            if not self._cancelled:
                self.error.emit(str(exc))


# ── Progress dialog ───────────────────────────────────────────────────── #

class _ProgressDialog(QDialog):
    """Shown while ingestion runs in the background."""

    cancelled: Signal = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Processing Scripts")
        self.setModal(True)
        self.setFixedSize(420, 160)
        self.setStyleSheet(_DIALOG_STYLE)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self._status = QLabel("Initialising…")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setFixedHeight(20)
        layout.addWidget(self._bar)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._on_cancel)
        cancel_btn.setFixedWidth(90)
        row = QHBoxLayout()
        row.addStretch(); row.addWidget(cancel_btn); row.addStretch()
        layout.addLayout(row)

    def update_progress(self, stage: str, current: int, total: int) -> None:
        self._status.setText(stage)
        if total > 0:
            self._bar.setValue(int(100 * current / total))
        else:
            self._bar.setRange(0, 0)   # indeterminate

    def _on_cancel(self) -> None:
        self._status.setText("Cancelling…")
        self.cancelled.emit()


# ── Main dialog ───────────────────────────────────────────────────────── #

class ScriptManagerDialog(QDialog):
    """
    Script Manager main window.

    Signals
    -------
    script_selected(str)  — emitted when user wants to load a script into
                            the active editor tab; carries the full SQL content.
    """

    script_selected: Signal = Signal(str)
    graph_updated:   Signal = Signal(object)   # emitted when the loaded graph changes

    def __init__(self, parent=None, preloaded_graph: "ScriptKnowledgeGraph | None" = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Support Script Manager")
        self.resize(980, 640)
        self.setMinimumSize(720, 480)
        self.setStyleSheet(_DIALOG_STYLE)

        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        # Reuse a graph pre-loaded in the background by MainWindow when available;
        # otherwise fall back to loading it here (keeps the dialog self-sufficient).
        self._graph: ScriptKnowledgeGraph = (
            preloaded_graph if preloaded_graph is not None
            else ScriptKnowledgeGraph.load()
        )
        self._worker: _IngestionWorker | None = None
        self._progress_dlg: _ProgressDialog | None = None
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._run_search)

        self._build_ui()
        self._refresh_stats()
        self._update_empty_state()

        if geom := self._settings.value(_WIN_GEO_KEY):
            self.restoreGeometry(geom)

    # ── UI Construction ───────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        root.addWidget(self._build_header())

        # Body — splitter with search/results on left, preview on right
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        body.setContentsMargins(12, 8, 12, 8)
        body.setStyleSheet("QSplitter::handle { background: #2e2e4e; width: 1px; }")

        left = self._build_left_panel()
        right = self._build_preview_panel()
        body.addWidget(left)
        body.addWidget(right)
        body.setSizes([620, 320])
        root.addWidget(body, 1)

        # Status bar
        self._status_bar = QLabel("Ready")
        self._status_bar.setObjectName("stats")
        self._status_bar.setContentsMargins(12, 4, 12, 6)
        root.addWidget(self._status_bar)

    def _build_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setStyleSheet("background: #0d0d1a; border-bottom: 2px solid #4361ee;")
        hdr.setFixedHeight(56)
        row = QHBoxLayout(hdr)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(16)

        title = QLabel("📜  Support Script Manager")
        title.setObjectName("header")
        row.addWidget(title)

        self._stats_label = QLabel("No scripts loaded")
        self._stats_label.setObjectName("stats")
        row.addWidget(self._stats_label)
        row.addStretch()

        upload_btn = QPushButton("⬆  Upload Scripts ZIP")
        upload_btn.setObjectName("upload_btn")
        upload_btn.setFixedHeight(32)
        upload_btn.setToolTip("Add scripts from a .zip archive")
        upload_btn.clicked.connect(self._on_upload)
        row.addWidget(upload_btn)

        self._clear_btn = QPushButton("🗑  Clear All")
        self._clear_btn.setObjectName("clear_btn")
        self._clear_btn.setFixedHeight(32)
        self._clear_btn.setToolTip("Remove all loaded scripts and reset the graph")
        self._clear_btn.clicked.connect(self._on_clear)
        row.addWidget(self._clear_btn)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(32)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        return hdr

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(8)

        # Search box
        search_row = QHBoxLayout()
        search_lbl = QLabel("🔍")
        search_lbl.setFixedWidth(20)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(
            "Describe what you need… e.g. \"fix deadlock\" or \"40P01\""
        )
        self._search_edit.setFixedHeight(34)
        self._search_edit.textChanged.connect(self._on_search_changed)
        self._search_edit.returnPressed.connect(self._run_search)
        search_row.addWidget(search_lbl)
        search_row.addWidget(self._search_edit, 1)
        layout.addLayout(search_row)

        # Results table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Score", "Script Name", "Matched Concepts", "Preview"])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 72)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 200)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 180)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, 1)

        # Empty-state overlay
        self._empty_label = QLabel(
            "No scripts loaded.\n\nClick ⬆ Upload Scripts ZIP to get started."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #555570; font-size: 13px; padding: 40px;")
        self._empty_label.hide()
        layout.addWidget(self._empty_label)

        return panel

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(6)

        hdr = QLabel("Script Preview")
        hdr.setObjectName("stats")
        layout.addWidget(hdr)

        self._preview_name = QLabel("—")
        self._preview_name.setStyleSheet("color: #89b4fa; font-size: 12px; font-weight: bold;")
        layout.addWidget(self._preview_name)

        self._preview_edit = QPlainTextEdit()
        self._preview_edit.setReadOnly(True)
        self._preview_edit.setPlaceholderText("Select a script to preview it here.")
        layout.addWidget(self._preview_edit, 1)

        load_btn = QPushButton("▶  Load into Editor")
        load_btn.setFixedHeight(30)
        load_btn.setToolTip("Open this script in the SQL editor  (double-click)")
        load_btn.clicked.connect(self._load_selected_into_editor)
        layout.addWidget(load_btn)
        self._load_btn = load_btn
        return panel

    # ── Stats and state ───────────────────────────────────────────────── #

    def _refresh_stats(self) -> None:
        s = self._graph.stats()
        if s.script_count == 0:
            self._stats_label.setText("No scripts loaded")
        else:
            ts = f"  ·  Last indexed: {s.last_indexed}" if s.last_indexed else ""
            self._stats_label.setText(
                f"{s.script_count} script(s)  ·  {s.term_count} terms"
                f"  ·  {s.cluster_count} cluster(s){ts}"
            )

    def _update_empty_state(self) -> None:
        has_scripts = self._graph.stats().script_count > 0
        self._search_edit.setEnabled(has_scripts)
        self._clear_btn.setEnabled(has_scripts)
        if has_scripts:
            self._empty_label.hide()
            self._table.show()
        else:
            self._table.hide()
            self._empty_label.show()

    # ── Search ────────────────────────────────────────────────────────── #

    def _on_search_changed(self, text: str) -> None:
        self._debounce_timer.start()

    def _run_search(self) -> None:
        query = self._search_edit.text().strip()
        if not query:
            self._table.setRowCount(0)
            self._status_bar.setText("Ready")
            return
        if not self._graph.stats().script_count:
            return
        try:
            results = self._graph.search(query)
            self._populate_results(results)
            n = len(results)
            self._status_bar.setText(
                f"Found {n} result(s) for: {query}" if n else
                f"No scripts found for: {query}"
            )
        except Exception as exc:
            log.exception("Search failed")
            self._status_bar.setText(f"Search error: {exc}")

    def _populate_results(self, results: list[SearchResult]) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        self._results = results   # keep reference for context menu
        for row, r in enumerate(results):
            self._table.insertRow(row)

            # Score column — color-coded bar via background
            pct  = min(1.0, r.score)
            item = QTableWidgetItem(f"{pct * 100:.0f}%")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            red   = int(255 * (1.0 - pct))
            green = int(180 * pct)
            item.setBackground(QBrush(QColor(red, green, 30, 180)))
            item.setForeground(QBrush(QColor("#ffffff")))
            item.setData(Qt.ItemDataRole.UserRole, r)
            self._table.setItem(row, 0, item)

            # Script name
            name_item = QTableWidgetItem(r.filename)
            name_item.setToolTip(r.path)
            self._table.setItem(row, 1, name_item)

            # Matched concepts
            concepts = ", ".join(r.matched_terms[:6])
            self._table.setItem(row, 2, QTableWidgetItem(concepts))

            # Preview
            self._table.setItem(row, 3, QTableWidgetItem(r.preview))

        self._table.setSortingEnabled(True)

    # ── Selection and preview ─────────────────────────────────────────── #

    def _on_selection_changed(self) -> None:
        result = self._selected_result()
        if not result:
            self._preview_edit.clear()
            self._preview_name.setText("—")
            return
        self._preview_name.setText(result.filename)
        # Load full content from graph
        sc = self._graph._scripts.get(result.script_id)
        if sc:
            self._preview_edit.setPlainText(sc.get("content", result.preview))
        else:
            self._preview_edit.setPlainText(result.preview)

    def _selected_result(self) -> SearchResult | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_double_click(self, _item) -> None:
        self._load_selected_into_editor()

    def _load_selected_into_editor(self) -> None:
        result = self._selected_result()
        if not result:
            return
        sc = self._graph._scripts.get(result.script_id)
        content = sc.get("content", "") if sc else result.preview
        if content:
            self.script_selected.emit(content)
            self.accept()

    # ── Context menu ──────────────────────────────────────────────────── #

    def _on_context_menu(self, pos) -> None:
        result = self._selected_result()
        if not result:
            return
        menu = QMenu(self)
        menu.addAction("▶  Load into editor",   self._load_selected_into_editor)
        menu.addAction("📋  Copy script name",   lambda: self._copy_name(result))
        menu.addAction("ℹ  Show details",        lambda: self._show_details(result))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    @staticmethod
    def _copy_name(result: SearchResult) -> None:
        QApplication.clipboard().setText(result.filename)

    def _show_details(self, result: SearchResult) -> None:
        sc = self._graph._scripts.get(result.script_id, {})
        meta = sc.get("metadata", {})
        lines = [
            f"Filename:  {result.filename}",
            f"Path:      {result.path}",
            f"Score:     {result.score:.4f}",
            f"Cluster:   {result.community}",
            f"Matched:   {', '.join(result.matched_terms)}",
            "",
        ]
        for k, v in meta.items():
            lines.append(f"@{k}: {v}")
        cmds = sc.get("commands", [])
        if cmds:
            lines.append(f"\nCommands:  {', '.join(cmds)}")
        tables = sc.get("tables", [])
        if tables:
            lines.append(f"Tables:    {', '.join(tables)}")
        codes = sc.get("error_codes", [])
        if codes:
            lines.append(f"Err codes: {', '.join(codes)}")
        StyledMessageBox.information(self, f"Details — {result.filename}", "\n".join(lines))

    # ── Upload ────────────────────────────────────────────────────────── #

    def _on_upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Script Collection ZIP",
            "", "Zip archives (*.zip);;All files (*)"
        )
        if not path:
            return

        # Ask merge vs replace if graph already has scripts
        merge = True
        if self._graph.stats().script_count > 0:
            merge = StyledMessageBox.question(
                self,
                "Add or Replace?",
                f"You already have {self._graph.stats().script_count} script(s) loaded.\n\n"
                "Click Yes to merge (add new scripts to existing collection).\n"
                "Click No to replace (clear and re-index from this ZIP only).",
            )

        self._progress_dlg = _ProgressDialog(self)
        self._worker = _IngestionWorker(
            path,
            self._graph if merge else None,
            merge=merge,
            parent=self,
        )
        self._worker.progress.connect(self._progress_dlg.update_progress)
        self._worker.finished.connect(self._on_ingestion_done)
        self._worker.error.connect(self._on_ingestion_error)
        self._progress_dlg.cancelled.connect(self._worker.cancel)
        self._progress_dlg.cancelled.connect(self._progress_dlg.accept)
        self._worker.start()
        self._progress_dlg.exec()

    def _on_ingestion_done(self, graph: ScriptKnowledgeGraph) -> None:
        self._graph = graph
        self.graph_updated.emit(graph)
        if self._progress_dlg:
            self._progress_dlg.accept()
        s = self._graph.stats()
        self._refresh_stats()
        self._update_empty_state()
        self._table.setRowCount(0)
        self._preview_edit.clear()
        self._search_edit.clear()
        self._status_bar.setText(
            f"Indexed {s.script_count} script(s) into {s.cluster_count} cluster(s)."
        )
        StyledMessageBox.information(
            self,
            "Import Complete",
            f"Successfully processed your script collection.\n\n"
            f"  Scripts loaded:  {s.script_count}\n"
            f"  Unique terms:    {s.term_count}\n"
            f"  Topic clusters:  {s.cluster_count}\n\n"
            "Type in the search box to find relevant scripts.",
        )

    def _on_ingestion_error(self, message: str) -> None:
        if self._progress_dlg:
            self._progress_dlg.accept()
        StyledMessageBox.critical(self, "Import Failed", message)
        self._status_bar.setText("Import failed — see error dialog.")

    # ── Clear ─────────────────────────────────────────────────────────── #

    def _on_clear(self) -> None:
        if not StyledMessageBox.question(
            self,
            "Clear All Scripts",
            "This will remove all loaded scripts and delete the saved graph.\n\n"
            "Are you sure?",
        ):
            return
        self._graph = ScriptKnowledgeGraph()
        self.graph_updated.emit(self._graph)
        saved = ScriptKnowledgeGraph.default_path()
        if saved.exists():
            try:
                saved.unlink()
            except OSError:
                pass
        self._table.setRowCount(0)
        self._preview_edit.clear()
        self._search_edit.clear()
        self._refresh_stats()
        self._update_empty_state()
        self._status_bar.setText("All scripts cleared.")

    # ── Auto-suggest on query errors ─────────────────────────────────── #

    def search_for_error(self, error_code: str, error_message: str = "") -> None:
        """
        Programmatically search for scripts related to a PostgreSQL error.
        Called by MainWindow when a query fails with a recognisable error.
        """
        query = f"{error_code} {error_message}"
        self._search_edit.setText(query)
        self._run_search()

    # ── Window lifecycle ──────────────────────────────────────────────── #

    def closeEvent(self, event) -> None:
        self._settings.setValue(_WIN_GEO_KEY, self.saveGeometry())
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().closeEvent(event)
