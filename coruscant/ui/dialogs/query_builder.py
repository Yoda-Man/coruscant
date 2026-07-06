"""
coruscant.ui.dialogs.query_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Visual Query Builder — opened from the Schema Browser's schema context menu.

Lets the user compose a SELECT statement without typing SQL:

  • Pick a base table (FROM)
  • Stack any number of joins — INNER, LEFT or RIGHT — each with an
    ON <left column> = <right column> condition
  • Foreign keys are parsed from the schema metadata, so when a join
    table is chosen the ON clause is pre-filled automatically whenever
    a FK relationship exists ("⚡ auto-linked")
  • Tick the output fields per table (or take everything with *)
  • Optional WHERE, ORDER BY and LIMIT
  • A live, syntax-highlighted SQL preview updates on every change

The finished statement is emitted through ``insert_sql`` (same contract
as the Schema Browser) and lands in the active editor tab — it is never
executed directly.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import logging
import re

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QLineEdit, QSpinBox, QCheckBox,
    QPlainTextEdit, QWidget, QScrollArea, QFrame, QSplitter, QApplication,
    QHeaderView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from coruscant.ui.style import (
    BG_BASE, BG_SURFACE, BG_PANEL, BG_INPUT, BG_INPUT_FOCUS,
    BORDER, BORDER_LIGHT, BORDER_HOVER, ACCENT, ACCENT_BLUE,
    ACCENT_BLUE_LT, TEXT, TEXT_MUTED, TEXT_DIM, WHITE, SELECTION,
    SPACE_XS, SPACE_SM, SPACE_MD, RADIUS, RADIUS_SM, RADIUS_LG,
)
from coruscant.utils.highlighter import SQLHighlighter

log = logging.getLogger(__name__)

JOIN_TYPES = ["INNER JOIN", "LEFT JOIN", "RIGHT JOIN"]

# "FOREIGN KEY child(a, b) REFERENCES parent(x, y)"
_FK_RE = re.compile(
    r"FOREIGN KEY\s+(\S+)\s*\(([^)]*)\)\s*REFERENCES\s+(\S+)\s*\(([^)]*)\)",
    re.IGNORECASE,
)


def _stylesheet() -> str:
    """Futuristic neon-on-navy skin built from the shared design tokens."""
    return (
        f"QDialog {{ background: {BG_BASE}; }}"
        f"QLabel {{ color: {TEXT}; font-size: 12px; background: transparent; }}"
        f"QLabel#qb_title {{"
        f"  color: {ACCENT_BLUE_LT}; font-size: 16px; font-weight: 800;"
        f"  letter-spacing: 3px;"
        f"}}"
        f"QLabel#qb_subtitle {{ color: {TEXT_DIM}; font-size: 11px; letter-spacing: 1px; }}"
        f"QLabel#section {{"
        f"  color: {ACCENT_BLUE}; font-size: 10px; font-weight: 700;"
        f"  letter-spacing: 2px; padding-top: 2px;"
        f"}}"
        f"QLabel#fk_hint {{ color: #64ffda; font-size: 10px; }}"
        f"QFrame#header_bar {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
        f"      stop:0 #0d0d1a, stop:0.5 #16163a, stop:1 #0d0d1a);"
        f"  border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px;"
        f"}}"
        f"QFrame#card {{"
        f"  background: {BG_SURFACE}; border: 1px solid {BORDER};"
        f"  border-radius: {RADIUS_LG}px;"
        f"}}"
        f"QFrame#join_row {{"
        f"  background: {BG_PANEL}; border: 1px solid {BORDER};"
        f"  border-radius: {RADIUS}px;"
        f"}}"
        f"QFrame#join_row:hover {{ border-color: {ACCENT}; }}"
        f"QComboBox {{"
        f"  background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER_LIGHT};"
        f"  border-radius: {RADIUS}px; padding: 4px 8px; font-size: 12px;"
        f"  min-height: 20px;"
        f"}}"
        f"QComboBox:hover {{ border-color: {BORDER_HOVER}; }}"
        f"QComboBox:focus {{ border-color: {ACCENT}; }}"
        f"QComboBox::drop-down {{ border: none; width: 18px; }}"
        f"QComboBox QAbstractItemView {{"
        f"  background: {BG_INPUT}; color: {TEXT}; border: 1px solid {ACCENT};"
        f"  selection-background-color: {SELECTION}; outline: 0;"
        f"}}"
        f"QLineEdit {{"
        f"  background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER_LIGHT};"
        f"  border-radius: {RADIUS}px; padding: 5px 8px; font-size: 12px;"
        f"  selection-background-color: {ACCENT};"
        f"}}"
        f"QLineEdit:focus {{ border-color: {ACCENT}; background: {BG_INPUT_FOCUS}; }}"
        f"QSpinBox {{"
        f"  background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER_LIGHT};"
        f"  border-radius: {RADIUS}px; padding: 3px 6px; font-size: 12px;"
        f"}}"
        f"QSpinBox:focus {{ border-color: {ACCENT}; }}"
        f"QCheckBox {{ color: {TEXT_MUTED}; font-size: 11px; }}"
        f"QTreeWidget {{"
        f"  background: {BG_PANEL}; color: {TEXT}; border: 1px solid {BORDER};"
        f"  border-radius: {RADIUS}px; font-size: 12px; outline: 0;"
        f"}}"
        f"QTreeWidget::item {{ padding: 2px 4px; }}"
        f"QTreeWidget::item:selected {{ background: {SELECTION}; color: {WHITE}; }}"
        # Checkboxes must read as checkboxes: visible accent border when
        # unchecked, filled accent square when checked.
        f"QTreeWidget::indicator {{"
        f"  width: 14px; height: 14px;"
        f"  border: 1px solid {ACCENT_BLUE};"
        f"  border-radius: {RADIUS_SM}px;"
        f"  background: {BG_INPUT};"
        f"}}"
        f"QTreeWidget::indicator:hover {{ border-color: {ACCENT_BLUE_LT}; }}"
        f"QTreeWidget::indicator:checked {{"
        f"  background: {ACCENT};"
        f"  border-color: {ACCENT_BLUE_LT};"
        f"}}"
        f"QPlainTextEdit {{"
        f"  background: #0a0a14; color: {TEXT};"
        f"  border: 1px solid {ACCENT}; border-radius: {RADIUS_LG}px;"
        f"  font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;"
        f"  font-size: 12px; padding: 8px;"
        f"  selection-background-color: {ACCENT};"
        f"}}"
        f"QPushButton {{"
        f"  background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER_LIGHT};"
        f"  border-radius: {RADIUS}px; padding: 5px 14px;"
        f"  font-size: 11px; font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{ border-color: {ACCENT_BLUE}; color: {WHITE}; }}"
        f"QPushButton:pressed {{ background: {ACCENT}; }}"
        f"QPushButton#primary {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"      stop:0 #4361ee, stop:1 #2a3eb1);"
        f"  border: 1px solid {ACCENT_BLUE}; color: {WHITE}; font-weight: 700;"
        f"  padding: 6px 22px;"
        f"}}"
        f"QPushButton#primary:hover {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"      stop:0 #5a76ff, stop:1 #4361ee);"
        f"}}"
        f"QPushButton#ghost {{ background: transparent; border-color: {BORDER}; color: {TEXT_MUTED}; }}"
        f"QPushButton#ghost:hover {{ border-color: {BORDER_HOVER}; color: {TEXT}; }}"
        f"QPushButton#remove_btn {{"
        f"  background: transparent; border: 1px solid transparent;"
        f"  color: #ef4444; font-weight: 800; padding: 0 6px; min-width: 10px;"
        f"}}"
        f"QPushButton#remove_btn:hover {{ border-color: #ef4444; border-radius: {RADIUS}px; }}"
        f"QScrollArea {{ background: transparent; border: none; }}"
        f"QSplitter::handle {{ background: {BORDER}; }}"
    )


class _JoinRow(QFrame):
    """One join line:  [type] [table]  ON  [left col] = [right col]  ✕"""

    changed = Signal()
    removed = Signal(object)

    def __init__(self, builder: "QueryBuilderDialog", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("join_row")
        self._builder = builder

        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE_SM, SPACE_XS, SPACE_SM, SPACE_XS)
        lay.setSpacing(SPACE_XS)

        self.type_cb = QComboBox()
        self.type_cb.addItems(JOIN_TYPES)
        self.type_cb.setFixedWidth(110)
        lay.addWidget(self.type_cb)

        self.table_cb = QComboBox()
        self.table_cb.setMinimumWidth(130)
        lay.addWidget(self.table_cb, 2)

        on_lbl = QLabel("ON")
        on_lbl.setStyleSheet(f"color: {ACCENT_BLUE}; font-weight: 700; font-size: 10px;")
        lay.addWidget(on_lbl)

        self.left_cb = QComboBox()          # qualified col from tables already in query
        self.left_cb.setMinimumWidth(150)
        lay.addWidget(self.left_cb, 3)

        eq = QLabel("=")
        eq.setStyleSheet(f"color: {ACCENT_BLUE}; font-weight: 700;")
        lay.addWidget(eq)

        self.right_cb = QComboBox()         # column of the joined table
        self.right_cb.setMinimumWidth(130)
        lay.addWidget(self.right_cb, 3)

        self.fk_lbl = QLabel("")
        self.fk_lbl.setObjectName("fk_hint")
        lay.addWidget(self.fk_lbl)

        rm = QPushButton("✕")
        rm.setObjectName("remove_btn")
        rm.setToolTip("Remove this join")
        rm.clicked.connect(lambda: self.removed.emit(self))
        lay.addWidget(rm)

        self.type_cb.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.table_cb.currentIndexChanged.connect(self._on_table_changed)
        self.left_cb.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.right_cb.currentIndexChanged.connect(lambda _i: self.changed.emit())

    # -- population -------------------------------------------------- #

    def set_tables(self, tables: list[str]) -> None:
        cur = self.table_cb.currentText()
        self.table_cb.blockSignals(True)
        self.table_cb.clear()
        self.table_cb.addItems(tables)
        if cur in tables:
            self.table_cb.setCurrentText(cur)
        self.table_cb.blockSignals(False)

    def set_left_columns(self, qualified: list[str]) -> None:
        cur = self.left_cb.currentText()
        self.left_cb.blockSignals(True)
        self.left_cb.clear()
        self.left_cb.addItems(qualified)
        if cur in qualified:
            self.left_cb.setCurrentText(cur)
        self.left_cb.blockSignals(False)

    def _on_table_changed(self) -> None:
        table = self.table_cb.currentText()
        cols = [c["name"] for c in self._builder.columns_of(table)]
        self.right_cb.blockSignals(True)
        self.right_cb.clear()
        self.right_cb.addItems(cols)
        self.right_cb.blockSignals(False)
        self.fk_lbl.setText("")
        self._autolink(table)
        self.changed.emit()

    def _autolink(self, table: str) -> None:
        """Pre-fill the ON clause from a FK between *table* and the query."""
        hit = self._builder.find_fk_link(table)
        if not hit:
            return
        other_table, other_col, own_col = hit
        left = f"{other_table}.{other_col}"
        if self.left_cb.findText(left) >= 0:
            self.left_cb.setCurrentText(left)
        if self.right_cb.findText(own_col) >= 0:
            self.right_cb.setCurrentText(own_col)
        self.fk_lbl.setText("⚡ auto-linked")
        self.fk_lbl.setToolTip(
            f"Foreign key detected: {table}.{own_col} ↔ {other_table}.{other_col}"
        )

    # -- state ------------------------------------------------------- #

    def value(self) -> dict | None:
        table = self.table_cb.currentText()
        left  = self.left_cb.currentText()
        right = self.right_cb.currentText()
        if not table or not left or not right:
            return None
        return {
            "type":  self.type_cb.currentText(),
            "table": table,
            "left":  left,          # "table.column"
            "right": right,         # column of the joined table
        }


class QueryBuilderDialog(QDialog):
    """Futuristic visual query builder for one schema."""

    insert_sql: Signal = Signal(str)

    def __init__(self, schema: str, tables: list[dict], parent=None) -> None:
        super().__init__(parent)
        self._schema = schema
        self._tables = tables          # [{name, columns:[{name,type}], foreign_keys:[...]}]
        self._fk_links = self._parse_fks(tables)
        self._join_rows: list[_JoinRow] = []
        self._checked: dict[str, set[str]] = {}   # table -> checked column names

        self.setWindowTitle(f"Query Builder — {schema}")
        self.setMinimumSize(920, 640)
        self.setStyleSheet(_stylesheet())
        self._build_ui()
        self._refresh()
        log.info("Query Builder opened  schema=%s  tables=%d", schema, len(tables))

    # ── metadata helpers ─────────────────────────────────────────────── #

    @staticmethod
    def _parse_fks(tables: list[dict]) -> list[tuple[str, str, str, str]]:
        """Return (child_table, child_col, parent_table, parent_col) tuples."""
        links: list[tuple[str, str, str, str]] = []
        for tbl in tables:
            for fk in tbl.get("foreign_keys", []):
                m = _FK_RE.search(fk.get("definition", ""))
                if not m:
                    continue
                child, ccols, parent, pcols = m.groups()
                child  = child.strip().strip('"')
                parent = parent.strip().strip('"')
                cc = [c.strip().strip('"') for c in ccols.split(",") if c.strip()]
                pc = [c.strip().strip('"') for c in pcols.split(",") if c.strip()]
                for c, p in zip(cc, pc):
                    links.append((child, c, parent, p))
        return links

    def table_names(self) -> list[str]:
        return [t["name"] for t in self._tables]

    def columns_of(self, table: str) -> list[dict]:
        for t in self._tables:
            if t["name"] == table:
                return t.get("columns", [])
        return []

    def tables_in_query(self) -> list[str]:
        """Base table plus every valid join table, in order, de-duplicated."""
        result: list[str] = []
        base = self._base_cb.currentText()
        if base:
            result.append(base)
        for row in self._join_rows:
            t = row.table_cb.currentText()
            if t and t not in result:
                result.append(t)
        return result

    def find_fk_link(self, table: str) -> tuple[str, str, str] | None:
        """Find a FK between *table* and any other table already in the query.

        Returns (other_table, other_column, table_column) or None.
        """
        others = [t for t in self.tables_in_query() if t != table]
        for child, ccol, parent, pcol in self._fk_links:
            if child == table and parent in others:
                return (parent, pcol, ccol)
            if parent == table and child in others:
                return (child, ccol, pcol)
        return None

    # ── UI construction ──────────────────────────────────────────────── #

    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setObjectName("section")
        return lbl

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        root.setSpacing(SPACE_SM)

        # ── Header ──────────────────────────────────────────────────── #
        header = QFrame()
        header.setObjectName("header_bar")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(SPACE_MD, SPACE_SM, SPACE_MD, SPACE_SM)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("⚡ QUERY BUILDER")
        title.setObjectName("qb_title")
        subtitle = QLabel(f"schema · {self._schema}")
        subtitle.setObjectName("qb_subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hl.addLayout(title_box)
        hl.addStretch()
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        hl.addWidget(self._count_lbl)
        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Top: builder controls ───────────────────────────────────── #
        top = QWidget()
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(0, 0, 0, 0)
        top_l.setSpacing(SPACE_SM)

        # Left card: FROM + JOINs
        left_card = QFrame()
        left_card.setObjectName("card")
        lc = QVBoxLayout(left_card)
        lc.setContentsMargins(SPACE_MD, SPACE_SM, SPACE_MD, SPACE_SM)
        lc.setSpacing(SPACE_XS)

        lc.addWidget(self._section("From — base table"))
        self._base_cb = QComboBox()
        self._base_cb.addItems(self.table_names())
        self._base_cb.currentIndexChanged.connect(lambda _i: self._refresh())
        lc.addWidget(self._base_cb)

        join_hdr = QHBoxLayout()
        join_hdr.addWidget(self._section("Joins"))
        join_hdr.addStretch()
        add_btn = QPushButton("＋ Add Join")
        add_btn.setToolTip("Add an INNER / LEFT / RIGHT join")
        add_btn.clicked.connect(self._add_join)
        join_hdr.addWidget(add_btn)
        lc.addLayout(join_hdr)

        self._joins_holder = QWidget()
        self._joins_layout = QVBoxLayout(self._joins_holder)
        self._joins_layout.setContentsMargins(0, 0, 0, 0)
        self._joins_layout.setSpacing(SPACE_XS)
        self._joins_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._joins_holder)
        lc.addWidget(scroll, 1)
        top_l.addWidget(left_card, 3)

        # Right card: field picker
        right_card = QFrame()
        right_card.setObjectName("card")
        rc = QVBoxLayout(right_card)
        rc.setContentsMargins(SPACE_MD, SPACE_SM, SPACE_MD, SPACE_SM)
        rc.setSpacing(SPACE_XS)

        fields_hdr = QHBoxLayout()
        fields_hdr.addWidget(self._section("Select fields"))
        fields_hdr.addStretch()
        all_btn = QPushButton("All")
        all_btn.setObjectName("ghost")
        all_btn.clicked.connect(lambda: self._check_all(True))
        none_btn = QPushButton("None")
        none_btn.setObjectName("ghost")
        none_btn.clicked.connect(lambda: self._check_all(False))
        fields_hdr.addWidget(all_btn)
        fields_hdr.addWidget(none_btn)
        rc.addLayout(fields_hdr)

        self._fields_tree = QTreeWidget()
        self._fields_tree.setHeaderHidden(True)
        self._fields_tree.setColumnCount(2)
        # Column names must never truncate — size col 0 to its contents and
        # let the data-type column take the leftover space.
        self._fields_tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self._fields_tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._fields_tree.header().setStretchLastSection(False)
        self._fields_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._fields_tree.itemChanged.connect(self._on_field_toggled)
        rc.addWidget(self._fields_tree, 1)

        hint = QLabel("No fields ticked → SELECT *")
        hint.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        rc.addWidget(hint)
        top_l.addWidget(right_card, 2)

        splitter.addWidget(top)

        # ── Bottom: options + preview ───────────────────────────────── #
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(SPACE_XS)

        opts = QHBoxLayout()
        opts.setSpacing(SPACE_SM)
        opts.addWidget(self._section("Where"))
        self._where_edit = QLineEdit()
        self._where_edit.setPlaceholderText('e.g.  "orders"."status" = \'shipped\'')
        self._where_edit.textChanged.connect(lambda _t: self._regen_sql())
        opts.addWidget(self._where_edit, 4)

        opts.addWidget(self._section("Order by"))
        self._order_cb = QComboBox()
        self._order_cb.setMinimumWidth(150)
        self._order_cb.currentIndexChanged.connect(lambda _i: self._regen_sql())
        opts.addWidget(self._order_cb, 2)
        self._dir_cb = QComboBox()
        self._dir_cb.addItems(["ASC", "DESC"])
        self._dir_cb.setFixedWidth(70)
        self._dir_cb.currentIndexChanged.connect(lambda _i: self._regen_sql())
        opts.addWidget(self._dir_cb)

        self._limit_chk = QCheckBox("LIMIT")
        self._limit_chk.setChecked(True)
        self._limit_chk.toggled.connect(lambda _c: self._regen_sql())
        opts.addWidget(self._limit_chk)
        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(1, 1_000_000)
        self._limit_spin.setValue(100)
        self._limit_spin.valueChanged.connect(lambda _v: self._regen_sql())
        opts.addWidget(self._limit_spin)
        bl.addLayout(opts)

        bl.addWidget(self._section("Live SQL preview"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._preview.setFont(font)
        self._highlighter = SQLHighlighter(self._preview.document())
        bl.addWidget(self._preview, 1)

        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        # ── Footer ──────────────────────────────────────────────────── #
        footer = QHBoxLayout()
        footer.addStretch()
        copy_btn = QPushButton("⧉ Copy SQL")
        copy_btn.clicked.connect(self._copy_sql)
        footer.addWidget(copy_btn)
        insert_btn = QPushButton("▶ Insert into Editor")
        insert_btn.setObjectName("primary")
        insert_btn.setDefault(True)
        insert_btn.clicked.connect(self._emit_sql)
        footer.addWidget(insert_btn)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("ghost")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)
        root.addLayout(footer)

    # ── joins ────────────────────────────────────────────────────────── #

    def _add_join(self) -> None:
        row = _JoinRow(self, parent=self._joins_holder)
        row.changed.connect(self._refresh)
        row.removed.connect(self._remove_join)
        self._join_rows.append(row)
        self._joins_layout.insertWidget(self._joins_layout.count() - 1, row)

        row.set_tables(self.table_names())
        # Default to the first table not already in the query.
        used = set(self.tables_in_query())
        for name in self.table_names():
            if name not in used:
                row.table_cb.setCurrentText(name)
                break
        row.set_left_columns(self._qualified_columns(exclude=row.table_cb.currentText()))
        row._on_table_changed()
        self._refresh()

    def _remove_join(self, row: _JoinRow) -> None:
        if row in self._join_rows:
            self._join_rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._refresh()

    def _qualified_columns(self, exclude: str = "") -> list[str]:
        out: list[str] = []
        for t in self.tables_in_query():
            if t == exclude:
                continue
            for c in self.columns_of(t):
                out.append(f"{t}.{c['name']}")
        return out

    # ── field tree ───────────────────────────────────────────────────── #

    def _rebuild_fields(self) -> None:
        self._fields_tree.blockSignals(True)
        self._fields_tree.clear()
        for t in self.tables_in_query():
            top = QTreeWidgetItem([t, ""])
            f = top.font(0); f.setBold(True); top.setFont(0, f)
            top.setForeground(0, Qt.GlobalColor.cyan)
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            checked = self._checked.get(t, set())
            for c in self.columns_of(t):
                ci = QTreeWidgetItem([c["name"], c.get("type", "")])
                ci.setForeground(1, Qt.GlobalColor.gray)
                ci.setFlags(ci.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                ci.setCheckState(
                    0,
                    Qt.CheckState.Checked if c["name"] in checked
                    else Qt.CheckState.Unchecked,
                )
                ci.setData(0, Qt.ItemDataRole.UserRole, {"table": t, "column": c["name"]})
                top.addChild(ci)
            self._fields_tree.addTopLevelItem(top)
            top.setExpanded(True)
        self._fields_tree.blockSignals(False)

    def _on_field_toggled(self, item: QTreeWidgetItem, _col: int) -> None:
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if not d:
            return
        bucket = self._checked.setdefault(d["table"], set())
        if item.checkState(0) == Qt.CheckState.Checked:
            bucket.add(d["column"])
        else:
            bucket.discard(d["column"])
        self._regen_sql()

    def _check_all(self, state: bool) -> None:
        for t in self.tables_in_query():
            self._checked[t] = (
                {c["name"] for c in self.columns_of(t)} if state else set()
            )
        self._rebuild_fields()
        self._regen_sql()

    # ── refresh & SQL generation ─────────────────────────────────────── #

    def _refresh(self) -> None:
        """Full refresh: join-row column lists, field tree, order-by, SQL."""
        for row in self._join_rows:
            row.set_left_columns(
                self._qualified_columns(exclude=row.table_cb.currentText())
            )
        self._rebuild_fields()

        cur = self._order_cb.currentText()
        qualified = [""] + self._qualified_columns()
        self._order_cb.blockSignals(True)
        self._order_cb.clear()
        self._order_cb.addItems(qualified)
        if cur in qualified:
            self._order_cb.setCurrentText(cur)
        self._order_cb.blockSignals(False)

        n = len(self.tables_in_query())
        self._count_lbl.setText(
            f"{n} table{'s' if n != 1 else ''} · {len(self._join_rows)} join"
            f"{'s' if len(self._join_rows) != 1 else ''}"
        )
        self._regen_sql()

    def build_sql(self) -> str:
        """Assemble the SELECT statement from the current UI state."""
        s = self._schema
        base = self._base_cb.currentText()
        if not base:
            return "-- pick a base table"

        # SELECT list
        select_cols: list[str] = []
        for t in self.tables_in_query():
            for c in self.columns_of(t):
                if c["name"] in self._checked.get(t, set()):
                    select_cols.append(f'"{t}"."{c["name"]}"')
        select_clause = (
            ",\n    ".join(select_cols) if select_cols else "*"
        )

        lines = [f"SELECT\n    {select_clause}" if select_cols else "SELECT *"]
        lines.append(f'FROM "{s}"."{base}"')

        for row in self._join_rows:
            v = row.value()
            if not v:
                continue
            lt, lc = v["left"].split(".", 1)
            lines.append(
                f'{v["type"]} "{s}"."{v["table"]}"'
                f'\n    ON "{lt}"."{lc}" = "{v["table"]}"."{v["right"]}"'
            )

        where = self._where_edit.text().strip()
        if where:
            lines.append(f"WHERE {where}")

        order = self._order_cb.currentText()
        if order:
            ot, oc = order.split(".", 1)
            lines.append(f'ORDER BY "{ot}"."{oc}" {self._dir_cb.currentText()}')

        if self._limit_chk.isChecked():
            lines.append(f"LIMIT {self._limit_spin.value()}")

        return "\n".join(lines) + ";"

    def _regen_sql(self) -> None:
        self._preview.setPlainText(self.build_sql())

    # ── actions ──────────────────────────────────────────────────────── #

    def _copy_sql(self) -> None:
        QApplication.clipboard().setText(self._preview.toPlainText())

    def _emit_sql(self) -> None:
        sql = self.build_sql()
        log.info("Query Builder inserted SQL  schema=%s  joins=%d",
                 self._schema, len(self._join_rows))
        self.insert_sql.emit(sql)
        self.accept()
