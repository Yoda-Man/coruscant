"""
coruscant.ui.dialogs.guide
~~~~~~~~~~~~~~~~~~~~~~~~~~
Quick-reference / shortcut guide dialog.

Opened from the Schema Browser's "? Guide" button.  Shows the application
logo, version, and a full reference of keyboard shortcuts, tips, and tricks.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextBrowser, QWidget,
)
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtCore import Qt

from coruscant import __version__, __app_name__

# ── Logo resolution (same strategy as app.py) ────────────────────────── #
_BASE = (
    Path(sys._MEIPASS)
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[3]
)
_ICON_PATH = str(_BASE / "docs" / "icon.png")

# ── Stylesheet ────────────────────────────────────────────────────────── #
_DIALOG_STYLE = """
    QDialog {
        background: #0e0e1a;
    }
    QTextBrowser {
        background: #12121e;
        color: #cdd6f4;
        border: 1px solid #2e2e4e;
        border-radius: 6px;
        padding: 12px;
        font-size: 12px;
    }
    QPushButton {
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 #3c3c52, stop:1 #2e2e42);
        border: 1px solid #555570;
        border-radius: 5px;
        padding: 7px 28px;
        color: #ddd;
        font-size: 12px;
        font-weight: 600;
        min-width: 80px;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 #4a4a62, stop:1 #3c3c52);
        border-color: #7070a0;
        color: #fff;
    }
    QPushButton:pressed {
        background: #4361ee;
        border-color: #4361ee;
    }
    QLabel#title_label {
        color: #cdd6f4;
        font-size: 18px;
        font-weight: bold;
    }
    QLabel#subtitle_label {
        color: #8888aa;
        font-size: 11px;
    }
"""

# ── Guide HTML content ────────────────────────────────────────────────── #
_GUIDE_HTML = """
<style>
  body  { color: #cdd6f4; font-size: 12px; margin: 0; padding: 0; }
  h2    { color: #89b4fa; margin-top: 16px; margin-bottom: 6px;
          border-bottom: 1px solid #2e2e4e; padding-bottom: 4px; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 10px; }
  th    { color: #a6adc8; text-align: left; padding: 4px 10px 4px 0;
          font-size: 11px; border-bottom: 1px solid #2e2e4e; }
  td    { padding: 3px 10px 3px 0; vertical-align: top; }
  td.key{ color: #cba6f7; font-family: monospace; white-space: nowrap;
          font-size: 11px; min-width: 160px; }
  td.desc { color: #cdd6f4; }
  ul    { margin: 4px 0 10px 0; padding-left: 18px; }
  li    { margin-bottom: 4px; }
  code  { color: #a6e3a1; font-family: monospace; font-size: 11px; }
  .tip  { color: #f9e2af; }
  .note { color: #89dceb; }
</style>

<h2>⌨&nbsp; Keyboard Shortcuts</h2>
<table>
  <tr><th>Shortcut</th><th>Action</th></tr>
  <tr><td class="key">F5</td>
      <td class="desc">Execute <b>all</b> editor tabs sequentially</td></tr>
  <tr><td class="key">Ctrl+Enter</td>
      <td class="desc">Execute current tab — selection if any, otherwise full content</td></tr>
  <tr><td class="key">Ctrl+F5</td>
      <td class="desc">Execute only the <b>statement the cursor is inside</b></td></tr>
  <tr><td class="key">Escape</td>
      <td class="desc">Cancel a running query</td></tr>
  <tr><td class="key">Ctrl+T</td>
      <td class="desc">Open a new query tab</td></tr>
  <tr><td class="key">Ctrl+W</td>
      <td class="desc">Close the current query tab</td></tr>
  <tr><td class="key">Ctrl+Tab</td>
      <td class="desc">Switch to the next query tab</td></tr>
  <tr><td class="key">Ctrl+Shift+Tab</td>
      <td class="desc">Switch to the previous query tab</td></tr>
  <tr><td class="key">Ctrl+Space</td>
      <td class="desc">Trigger SQL autocomplete manually</td></tr>
  <tr><td class="key">Ctrl+C</td>
      <td class="desc">Copy selected result rows as TSV (no headers)</td></tr>
  <tr><td class="key">Ctrl+Shift+C</td>
      <td class="desc">Copy selected result rows <i>with</i> column headers</td></tr>
</table>

<h2>🌳&nbsp; Schema Browser</h2>
<ul>
  <li><b>Double-click</b> a table or view → inserts
      <code>SELECT * FROM schema.table LIMIT 100;</code> at the cursor</li>
  <li>Click the <b>▶ SELECT</b> button on a row → same quick-insert</li>
  <li><b>Right-click</b> a table → context menu with
      SELECT / UPDATE / DELETE script templates (all columns pre-filled)</li>
  <li><b>Double-click</b> a function → inserts a
      <code>SELECT schema.fn();</code> call template</li>
  <li>⚙ <b>Settings</b> panel → toggle <i>Auto-complete</i> and
      <i>Auto-close cell viewer after copy</i></li>
  <li class="tip">💡 Tip: expand a table node to browse Columns, Indexes,
      and Foreign Keys inline — hover index rows for the full definition</li>
</ul>

<h2>✏&nbsp; Query Editor</h2>
<ul>
  <li><b>Line-number gutter</b> — the current line is highlighted in blue;
      toggle on/off in ⚙ Settings</li>
  <li><b>Current-line highlight</b> — subtle background band follows the cursor</li>
  <li><b>Double-click</b> a query tab title to rename it manually</li>
  <li>After saving (💾) the tab is <b>auto-renamed</b> to the filename
      — manual renames are never overridden by auto-naming</li>
  <li>📂 Open a <code>.sql</code> file → loads content into the current tab</li>
  <li>🪄 <b>Format</b> → auto-formats SQL
      (reindent + uppercase keywords) via <i>sqlparse</i></li>
  <li>🧹 <b>Clear</b> → clears the editor and all unpinned result tabs</li>
  <li>▸ <b>Parameters</b> → define <code>%(name)s</code> substitution
      variables per tab; values are injected at execution time</li>
  <li class="tip">💡 Tip: Ctrl+Enter runs the selection if text is highlighted —
      perfect for testing one clause at a time</li>
  <li class="tip">💡 Tip: Ctrl+F5 executes only the single statement the cursor
      sits inside — great for multi-statement scripts</li>
</ul>

<h2>📊&nbsp; Result Grid</h2>
<ul>
  <li><b>Double-click</b> a cell → open the Cell Content Viewer
      (ideal for long text, JSON, XML)</li>
  <li>Right-click → Copy / Copy with Headers context menu</li>
  <li><b>Filter</b> box → live row filter; matches any column substring;
      type <code>null</code> to find NULL cells</li>
  <li>Export <b>CSV</b> or <b>JSON</b> → save the full result set to disk</li>
  <li>Click a <b>column header</b> to sort ascending/descending</li>
  <li>Drag column dividers in the header to resize columns</li>
  <li class="note">ℹ️ A yellow banner appears when results are truncated
      by the Row Limit — increase the spinner or set it to 0 for unlimited</li>
</ul>

<h2>📌&nbsp; Result Tabs</h2>
<ul>
  <li><b>Right-click</b> a result tab → <b>Pin</b> / <b>Unpin</b>
      — pinned tabs are preserved when you run the next query</li>
  <li><b>Double-click</b> a result tab title to rename it</li>
  <li>Each statement in a script produces its own labelled result tab</li>
  <li>EXPLAIN and EXPLAIN+ produce a dedicated plan-text tab</li>
</ul>


<h2>📜&nbsp; Support Script Manager</h2>
<ul>
  <li>Open via <b>📜 Scripts</b> button in the Schema Browser panel</li>
  <li>Click <b>⬆ Upload Scripts ZIP</b> to index a collection of .sql files</li>
  <li>Type natural language in the search box — e.g. <code>fix deadlock</code>
      or <code>table bloat</code> — results appear as you type (300 ms debounce)</li>
  <li>Double-click any result (or click <b>▶ Load into Editor</b>) to open the
      script in the active query tab</li>
  <li>Upload a second ZIP to <i>merge</i> collections or choose to replace entirely</li>
  <li>Right-click a result for Copy name / Show details / Load into editor</li>
  <li class="tip">💡 Format scripts for best results:</li>
</ul>
<pre style="background:#1e1e2e;padding:8px;border-radius:4px;font-size:11px;color:#cdd6f4;">
-- @desc:     Brief description of what this script does
-- @fixes:    problem1, problem2, problem3
-- @requires: pg_stat_statements
-- @tables:   pg_locks, pg_stat_activity
-- @date:     2026-01-15

-- Your SQL here
</pre>
<ul>
  <li class="note">ℹ️ The graph stores up to 500 scripts in ~10 MB on disk and
      loads in under 200 ms — works fully offline after initial indexing</li>
  <li>When a query fails with a PostgreSQL error code (e.g. 40P01), the client
      will offer to search for relevant scripts automatically</li>
</ul>

<h2>🔌&nbsp; Connection &amp; Transactions</h2>
<ul>
  <li>Connections button → save/load named connection profiles</li>
  <li><b>Auto-commit</b> on → every statement commits immediately</li>
  <li><b>Auto-commit</b> off → Commit / Rollback buttons become active;
      wrap changes in an explicit transaction</li>
  <li><b>Row limit</b> spinner → max rows returned per SELECT
      (0 = unlimited); default is 100</li>
  <li class="tip">💡 Tip: when disconnected but a profile exists,
      queries will <i>auto-reconnect</i> before executing</li>
</ul>
"""


class ShortcutGuideDialog(QDialog):
    """
    Modal quick-reference dialog.

    Displays the application logo, version string, and a styled HTML
    reference covering all keyboard shortcuts, schema browser tricks,
    editor features, and result-grid tips.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{__app_name__} — Quick Reference Guide")
        self.resize(700, 620)
        self.setStyleSheet(_DIALOG_STYLE)
        self.setModal(True)
        self._build_ui()

    # ── Construction ─────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(_GUIDE_HTML)
        # Scroll back to the top
        browser.verticalScrollBar().setValue(0)
        layout.addWidget(browser)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _build_header(self) -> QWidget:
        """Logo + app name + version row."""
        container = QWidget()
        container.setStyleSheet(
            "QWidget { background: #1a1a2e; border-radius: 8px; }"
        )
        row = QHBoxLayout(container)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(14)

        # Logo
        logo_lbl = QLabel()
        pixmap = QPixmap(_ICON_PATH)
        if not pixmap.isNull():
            logo_lbl.setPixmap(pixmap.scaled(
                52, 52,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            logo_lbl.setText("✦")
            logo_lbl.setStyleSheet("font-size: 32px; color: #89b4fa;")
        logo_lbl.setFixedSize(52, 52)
        row.addWidget(logo_lbl)

        # Text block
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title = QLabel(__app_name__)
        title.setObjectName("title_label")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)
        title.setStyleSheet("color: #cdd6f4;")
        text_col.addWidget(title)

        subtitle = QLabel(
            f"v{__version__}  ·  PostgreSQL multi-query client  "
            f"·  Quick Reference Guide"
        )
        subtitle.setObjectName("subtitle_label")
        subtitle.setStyleSheet("color: #8888aa; font-size: 11px;")
        text_col.addWidget(subtitle)

        row.addLayout(text_col)
        row.addStretch()
        return container
