"""
coruscant.ui.dialogs.qa_dialog
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
QA Engine results dialog.

Displays a :class:`~coruscant.core.qa_engine.QAReport` with:

- Health-score badge (colour-coded 0-100)
- Findings tree grouped by check category with severity icons
- Fix SQL pane — copy to clipboard or send directly to the editor
- Suppress finding (persisted to QSettings so it's filtered in future runs)
- Find related scripts — opens Script Manager pre-searched for this issue
- Export findings to CSV

Suppression rules are stored at QSettings key ``qa/suppressed_findings`` as a
JSON array of strings with the form ``"check_name:table_name"`` (table-scoped)
or ``"check_name:*"`` (check-wide).  Suppressed findings are hidden from the
tree on load; they can be cleared via the "Manage Suppressions" button.

Author: Marwa Trust Mutemasango
"""
from __future__ import annotations

import csv
import json
import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from coruscant.core.qa_engine import ERROR, INFO, WARNING, QAFinding, QAReport

log = logging.getLogger(__name__)

_SETTINGS_ORG = "Coruscant"
_SETTINGS_APP = "Coruscant"
_SUPPRESS_KEY = "qa/suppressed_findings"

_SEVERITY_ICON:  dict[str, str] = {ERROR: "✖", WARNING: "⚠", INFO: "ℹ"}
_SEVERITY_COLOR: dict[str, str] = {ERROR: "#ef4444", WARNING: "#f59e0b", INFO: "#60a5fa"}

_CHECK_LABEL: dict[str, str] = {
    "orphaned_tables":    "Orphaned Tables",
    "missing_fk_indexes": "Missing FK Indexes",
    "circular_deps":      "Circular Dependencies",
    "nullable_fks":       "Nullable Foreign Keys",
    "naming_conventions": "Naming Conventions",
    "type_consistency":   "Type Consistency",
}

_DIALOG_STYLE = """
QDialog   { background: #0d0d1a; color: #cdd6f4; }
QLabel    { color: #cdd6f4; }
QTreeWidget {
    background: #1a1a2e; color: #cdd6f4;
    border: 1px solid #313244; border-radius: 4px;
    font-size: 12px;
    alternate-background-color: #12122a;
}
QTreeWidget::item          { padding: 3px 4px; }
QTreeWidget::item:selected { background: #313244; }
QTreeWidget::item:hover    { background: #1e1e3a; }
QHeaderView::section {
    background: #12122a; color: #89b4fa;
    border: 1px solid #313244; padding: 4px 6px;
    font-size: 11px; font-weight: bold;
}
QTextEdit {
    background: #12122a; color: #cdd6f4;
    border: 1px solid #313244; border-radius: 4px;
    font-family: monospace; font-size: 12px; padding: 4px;
}
QPushButton {
    background: #1e1e2e; color: #cdd6f4;
    border: 1px solid #313244; border-radius: 4px;
    padding: 4px 12px; font-size: 11px;
}
QPushButton:hover    { background: #313244; border-color: #89b4fa; }
QPushButton:pressed  { background: #4361ee; color: #fff; }
QPushButton:disabled { color: #555; border-color: #222; }
QSplitter::handle    { background: #313244; }
"""


# ── Suppression helpers ───────────────────────────────────────────────── #

def _load_suppressions() -> set[str]:
    qs  = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    raw = qs.value(_SUPPRESS_KEY, "[]")
    try:
        return set(json.loads(raw))
    except (TypeError, json.JSONDecodeError):
        return set()


def _save_suppressions(rules: set[str]) -> None:
    qs = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    qs.setValue(_SUPPRESS_KEY, json.dumps(sorted(rules)))


def _suppression_key(finding: QAFinding) -> str:
    """Exact key for this finding (table-scoped)."""
    return f"{finding.check}:{finding.table or '*'}"


def _wildcard_key(finding: QAFinding) -> str:
    """Check-wide wildcard key."""
    return f"{finding.check}:*"


def _is_suppressed(finding: QAFinding, rules: set[str]) -> bool:
    return _suppression_key(finding) in rules or _wildcard_key(finding) in rules


# ── Dialog ────────────────────────────────────────────────────────────── #

class QADialog(QDialog):
    """Modal dialog that presents a :class:`QAReport`."""

    #: Emitted when the user clicks "Send to Editor" — carries the fix SQL.
    send_to_editor: Signal = Signal(str)

    #: Emitted when the user clicks "Find Scripts" — carries a search query.
    search_scripts_requested: Signal = Signal(str)

    def __init__(self, report: QAReport, parent=None) -> None:
        super().__init__(parent)
        self._report      = report
        self._suppressions = _load_suppressions()
        self.setWindowTitle(f"QA Engine — schema: {report.schema}")
        self.resize(920, 600)
        self.setStyleSheet(_DIALOG_STYLE)
        self._build_ui()
        self._populate(report)

    # ── Construction ─────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Health-score header ─────────────────────────────────────────
        header_frame = QFrame()
        header_frame.setStyleSheet(
            "QFrame { background: #1a1a2e; border: 1px solid #313244;"
            " border-radius: 6px; }"
        )
        hf_layout = QHBoxLayout(header_frame)
        hf_layout.setContentsMargins(14, 10, 14, 10)
        hf_layout.setSpacing(16)

        self._score_lbl = QLabel("100")
        self._score_lbl.setFont(QFont("system-ui", 28, QFont.Weight.Bold))
        hf_layout.addWidget(self._score_lbl)

        score_sub = QVBoxLayout()
        score_sub.setSpacing(2)
        score_title = QLabel("Health Score")
        score_title.setStyleSheet("color: #89b4fa; font-size: 11px; font-weight: bold;")
        score_sub.addWidget(score_title)
        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet("font-size: 11px; color: #888;")
        score_sub.addWidget(self._summary_lbl)
        hf_layout.addLayout(score_sub)
        hf_layout.addStretch()

        # Export button in header
        export_btn = QPushButton("📄  Export CSV")
        export_btn.setToolTip("Save all findings to a CSV file")
        export_btn.clicked.connect(self._on_export_csv)
        hf_layout.addWidget(export_btn)

        self._schema_lbl = QLabel("")
        self._schema_lbl.setStyleSheet("font-size: 11px; color: #555;")
        hf_layout.addWidget(self._schema_lbl)

        root.addWidget(header_frame)

        # ── Splitter: tree left | fix-SQL panel right ────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Findings tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Severity", "Table", "Column", "Message"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setColumnWidth(0, 100)
        self._tree.setColumnWidth(1, 160)
        self._tree.setColumnWidth(2, 110)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        splitter.addWidget(self._tree)

        # Right pane: fix SQL + action buttons
        fix_frame = QFrame()
        fix_layout = QVBoxLayout(fix_frame)
        fix_layout.setContentsMargins(4, 0, 0, 0)
        fix_layout.setSpacing(6)

        fix_title = QLabel("Fix SQL")
        fix_title.setStyleSheet(
            "color: #89b4fa; font-size: 11px; font-weight: bold;"
        )
        fix_layout.addWidget(fix_title)

        self._fix_sql_box = QTextEdit()
        self._fix_sql_box.setReadOnly(True)
        self._fix_sql_box.setPlaceholderText("Select a finding with a suggested fix…")
        fix_layout.addWidget(self._fix_sql_box)

        # Fix SQL action row
        fix_btns = QHBoxLayout()
        self._copy_btn = QPushButton("📋  Copy SQL")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._on_copy_sql)
        fix_btns.addWidget(self._copy_btn)

        self._send_btn = QPushButton("⮕  Send to Editor")
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._on_send_to_editor)
        fix_btns.addWidget(self._send_btn)
        fix_layout.addLayout(fix_btns)

        # Finding action row
        find_btns = QHBoxLayout()
        self._find_scripts_btn = QPushButton("🔎  Find Scripts")
        self._find_scripts_btn.setEnabled(False)
        self._find_scripts_btn.setToolTip(
            "Search the Script Manager for scripts related to this finding"
        )
        self._find_scripts_btn.clicked.connect(self._on_find_scripts)
        find_btns.addWidget(self._find_scripts_btn)

        self._suppress_btn = QPushButton("🔕  Suppress")
        self._suppress_btn.setEnabled(False)
        self._suppress_btn.setToolTip(
            "Suppress this finding for this table in future QA runs"
        )
        self._suppress_btn.clicked.connect(self._on_suppress)
        find_btns.addWidget(self._suppress_btn)
        fix_layout.addLayout(find_btns)

        splitter.addWidget(fix_frame)
        splitter.setSizes([580, 320])
        root.addWidget(splitter, stretch=1)

        # ── Bottom row ──────────────────────────────────────────────────
        bottom_row = QHBoxLayout()
        manage_btn = QPushButton("🔕  Manage Suppressions")
        manage_btn.setToolTip("View and clear all active suppression rules")
        manage_btn.clicked.connect(self._on_manage_suppressions)
        bottom_row.addWidget(manage_btn)
        bottom_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)
        root.addLayout(bottom_row)

    # ── Populate ──────────────────────────────────────────────────────── #

    def _populate(self, report: QAReport) -> None:
        score = report.health_score
        color = (
            "#81c784" if score >= 80
            else "#ffa726" if score >= 50
            else "#ef4444"
        )
        self._score_lbl.setText(str(score))
        self._score_lbl.setStyleSheet(
            f"font-size: 28px; font-weight: bold; color: {color};"
        )

        suppressed_count = sum(
            1 for f in report.findings if _is_suppressed(f, self._suppressions)
        )
        visible = [f for f in report.findings if not _is_suppressed(f, self._suppressions)]

        parts = []
        ec = sum(1 for f in visible if f.severity == "ERROR")
        wc = sum(1 for f in visible if f.severity == "WARNING")
        ic = sum(1 for f in visible if f.severity == "INFO")
        if ec:
            parts.append(f"{ec} error{'s' if ec>1 else ''}")
        if wc:
            parts.append(f"{wc} warning{'s' if wc>1 else ''}")
        if ic:
            parts.append(f"{ic} info")
        summary = ", ".join(parts) if parts else "No issues found"
        if suppressed_count:
            summary += f"  ({suppressed_count} suppressed)"
        self._summary_lbl.setText(summary)
        self._schema_lbl.setText(f"schema: {report.schema}")

        # Group findings by check name
        grouped: dict[str, list[QAFinding]] = {}
        for f in visible:
            grouped.setdefault(f.check, []).append(f)

        self._tree.clear()
        for check_name, findings in grouped.items():
            label = _CHECK_LABEL.get(check_name, check_name.replace("_", " ").title())
            # Determine group severity (worst first)
            sevs = {f.severity for f in findings}
            if "ERROR" in sevs:
                grp_sev, grp_color = "ERROR", _SEVERITY_COLOR["ERROR"]
            elif "WARNING" in sevs:
                grp_sev, grp_color = "WARNING", _SEVERITY_COLOR["WARNING"]
            else:
                grp_sev, grp_color = "INFO", _SEVERITY_COLOR["INFO"]

            group_item = QTreeWidgetItem([
                f"{_SEVERITY_ICON.get(grp_sev, '')} {label} ({len(findings)})",
                "", "", "",
            ])
            group_item.setForeground(0, QColor(grp_color))
            group_item.setData(0, Qt.ItemDataRole.UserRole, None)

            for f in findings:
                icon  = _SEVERITY_ICON.get(f.severity, "")
                color = _SEVERITY_COLOR.get(f.severity, "#cdd6f4")
                child = QTreeWidgetItem([
                    f"{icon} {f.severity}",
                    f.table or "",
                    f.column or "",
                    f.message,
                ])
                child.setForeground(0, QColor(color))
                child.setData(0, Qt.ItemDataRole.UserRole, f)
                group_item.addChild(child)

            self._tree.addTopLevelItem(group_item)
            group_item.setExpanded(True)

    # ── Slots ─────────────────────────────────────────────────────────── #

    def _on_item_double_clicked(
        self, item: QTreeWidgetItem, _column: int
    ) -> None:
        """Open a detail dialog so the user can read and copy the full message."""
        finding: QAFinding | None = item.data(0, Qt.ItemDataRole.UserRole)
        if finding is None:
            return  # group-header row – nothing to show

        dlg = QDialog(self)
        dlg.setWindowTitle("Finding Detail")
        dlg.setMinimumWidth(560)
        dlg.setStyleSheet(
            "QDialog { background: #0d0d1a; color: #cdd6f4; }"
            "QLabel  { color: #cdd6f4; font-size: 13px; }"
            "QTextEdit { background: #1e1e2e; color: #cdd6f4; border: 1px solid #313244;"
            "            font-family: monospace; font-size: 13px; }"
            "QPushButton { background: #313244; color: #cdd6f4; border: 1px solid #45475a;"
            "              padding: 5px 14px; border-radius: 4px; }"
            "QPushButton:hover { background: #45475a; }"
        )

        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)

        # Meta row
        severity_icon = {"WARNING": "⚠", "ERROR": "✖", "INFO": "ℹ"}.get(finding.severity, "")
        meta_parts = [f"{severity_icon} <b>{finding.severity}</b>"]
        if finding.table:
            meta_parts.append(f"Table: <b>{finding.table}</b>")
        if finding.column:
            meta_parts.append(f"Column: <b>{finding.column}</b>")
        meta_lbl = QLabel("  ·  ".join(meta_parts))
        meta_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(meta_lbl)

        # Full message (selectable, read-only)
        msg_edit = QTextEdit()
        msg_edit.setReadOnly(True)
        msg_edit.setPlainText(finding.message)
        msg_edit.setFixedHeight(100)
        layout.addWidget(msg_edit)

        # Fix SQL (if any)
        if finding.fix_sql:
            fix_lbl = QLabel("<b>Suggested Fix SQL:</b>")
            fix_lbl.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(fix_lbl)
            fix_edit = QTextEdit()
            fix_edit.setReadOnly(True)
            fix_edit.setPlainText(finding.fix_sql)
            fix_edit.setFixedHeight(90)
            layout.addWidget(fix_edit)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        copy_msg_btn = QPushButton("📋  Copy Message")
        copy_msg_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(finding.message)
        )
        btn_row.addWidget(copy_msg_btn)

        if finding.fix_sql:
            copy_sql_btn = QPushButton("📋  Copy SQL")
            copy_sql_btn.clicked.connect(
                lambda: QApplication.clipboard().setText(finding.fix_sql)
            )
            btn_row.addWidget(copy_sql_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
        dlg.exec()

    def _on_selection_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        finding: QAFinding | None = (
            current.data(0, Qt.ItemDataRole.UserRole) if current else None
        )
        has_fix    = bool(finding and finding.fix_sql)
        has_finding = finding is not None

        self._copy_btn.setEnabled(has_fix)
        self._send_btn.setEnabled(has_fix)
        self._find_scripts_btn.setEnabled(has_finding)
        self._suppress_btn.setEnabled(has_finding)

        if has_fix:
            self._fix_sql_box.setPlainText(finding.fix_sql)  # type: ignore[union-attr]
        else:
            self._fix_sql_box.clear()

    def _on_copy_sql(self) -> None:
        sql = self._fix_sql_box.toPlainText()
        if sql:
            QApplication.clipboard().setText(sql)

    def _on_send_to_editor(self) -> None:
        sql = self._fix_sql_box.toPlainText()
        if sql:
            self.send_to_editor.emit(sql)
            self.accept()

    def _on_find_scripts(self) -> None:
        item = self._tree.currentItem()
        if not item:
            return
        finding: QAFinding | None = item.data(0, Qt.ItemDataRole.UserRole)
        if not finding:
            return
        parts = [finding.check.replace("_", " ")]
        if finding.table:
            parts.append(finding.table)
        if finding.column:
            parts.append(finding.column)
        query = " ".join(parts)
        self.search_scripts_requested.emit(query)

    def _on_suppress(self) -> None:
        item = self._tree.currentItem()
        if not item:
            return
        finding: QAFinding | None = item.data(0, Qt.ItemDataRole.UserRole)
        if not finding:
            return
        key = _suppression_key(finding)
        self._suppressions.add(key)
        _save_suppressions(self._suppressions)

        # Remove from tree
        parent = item.parent()
        if parent:
            parent.removeChild(item)
            if parent.childCount() == 0:
                idx = self._tree.indexOfTopLevelItem(parent)
                self._tree.takeTopLevelItem(idx)

        # Update summary count
        suppressed_count = len(self._suppressions)
        cur_summary = self._summary_lbl.text()
        # Recount from tree
        visible_count = sum(
            self._tree.topLevelItem(i).childCount()
            for i in range(self._tree.topLevelItemCount())
        )
        self._summary_lbl.setText(
            f"{visible_count} finding(s) shown  ({suppressed_count} suppressed)"
        )
        log.info("Suppressed finding: %s", key)

    def _on_manage_suppressions(self) -> None:
        from coruscant.ui.widgets.styled_message_box import StyledMessageBox
        rules = sorted(self._suppressions)
        if not rules:
            StyledMessageBox.information(
                self, "No Suppressions",
                "No findings are currently suppressed."
            )
            return
        rules_text = "\n".join(f"  • {r}" for r in rules)
        answer = StyledMessageBox.question(
            self,
            "Manage Suppressions",
            f"Active suppression rules ({len(rules)}):\n\n{rules_text}\n\n"
            "Click OK to clear ALL suppressions, or Cancel to keep them.",
        )
        if answer:
            self._suppressions.clear()
            _save_suppressions(self._suppressions)
            self._populate(self._report)
            log.info("All suppressions cleared")

    def _on_export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export QA Findings",
            f"qa_report_{self._report.schema}.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Schema", "Check", "Severity", "Table", "Column", "Message", "Fix SQL"])
                for f in self._report.findings:
                    writer.writerow([
                        self._report.schema,
                        f.check,
                        f.severity,
                        f.table or "",
                        f.column or "",
                        f.message,
                        f.fix_sql or "",
                    ])
            log.info("QA findings exported to %s", path)
        except OSError as exc:
            log.error("Export failed: %s", exc)
