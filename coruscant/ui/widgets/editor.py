"""
coruscant.ui.widgets.editor
~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQL editor tab and its collapsible parameters panel.

  ParamsPanel  -- %(name)s parameter substitution table
  _LineNumberArea -- gutter widget that paints line numbers
  SQLEditor    -- QPlainTextEdit with autocomplete + line-number gutter
                  + current-line highlight
  EditorTab    -- SQL editor + syntax highlighter + ParamsPanel

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QTableWidget,
    QCompleter, QAbstractItemView, QTextEdit,
)
from PySide6.QtGui import (
    QFont, QTextCursor, QPainter, QColor, QTextCharFormat,
)
from PySide6.QtCore import Qt, QRect, QSize, QStringListModel

from coruscant.utils.highlighter import SQLHighlighter, KEYWORDS, FUNCTIONS


# =========================================================================== #
#  ParamsPanel                                                                 #
# =========================================================================== #

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


# =========================================================================== #
#  _LineNumberArea                                                             #
# =========================================================================== #

class _LineNumberArea(QWidget):
    """
    Thin gutter widget that lives to the left of SQLEditor and paints
    line numbers by delegating back to the editor's paint method.

    This follows the standard Qt line-number example pattern:
    the area is a child widget of the editor, positioned inside
    the editor's content rect so it scrolls in sync automatically.
    """

    def __init__(self, editor: "SQLEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor._line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor._paint_line_numbers(event)


# =========================================================================== #
#  SQLEditor                                                                   #
# =========================================================================== #

# Colours used for the gutter and current-line highlight.
# Two sets — one per theme — so the gutter matches the editor in both light
# and dark mode. Selected at paint time by SQLEditor._dark.
_GUTTER_DARK = {
    "bg":      QColor("#141420"),   # slightly darker than the dark editor bg
    "active":  QColor("#89b4fa"),   # blue — current line number
    "normal":  QColor("#5a5a7c"),   # muted — other line numbers
    "current": QColor("#1a1a30"),   # subtle current-line highlight band
}
_GUTTER_LIGHT = {
    "bg":      QColor("#eef1f6"),   # soft grey, a touch darker than white
    "active":  QColor("#0078d4"),   # accent blue — current line number
    "normal":  QColor("#9aa3b2"),   # muted slate — other line numbers
    "current": QColor("#eaf2fb"),   # pale blue current-line highlight band
}


class SQLEditor(QPlainTextEdit):
    """
    Enhanced QPlainTextEdit with:
      - SQL autocomplete (QCompleter, Ctrl+Space)
      - Line-number gutter with current-line highlight
    Both features can be enabled/disabled at runtime.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._completer: QCompleter | None = None
        self._completer_enabled: bool = True
        self._line_numbers_enabled: bool = True
        self._dark: bool = True   # gutter palette; updated via set_dark_theme()

        # -- Line-number gutter setup ---------------------------------- #
        self._ln_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_viewport_margins)
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_viewport_margins(0)
        self._highlight_current_line()

        # -- Autocomplete setup ---------------------------------------- #
        words = sorted(set(KEYWORDS) | set(FUNCTIONS))
        self.set_completer_words(words)

    # ------------------------------------------------------------------ #
    #  Line-number gutter                                                  #
    # ------------------------------------------------------------------ #

    def _line_number_area_width(self) -> int:
        """Pixel width needed to display the widest line number."""
        if not self._line_numbers_enabled:
            return 0
        digits = len(str(max(1, self.blockCount())))
        char_w = self.fontMetrics().horizontalAdvance("9")
        return 6 + char_w * max(digits, 2)   # minimum 2 digits + 6 px padding

    def _update_viewport_margins(self, _block_count: int = 0) -> None:
        self.setViewportMargins(self._line_number_area_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._ln_area.scroll(0, dy)
        else:
            self._ln_area.update(0, rect.y(), self._ln_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_viewport_margins()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._ln_area.setGeometry(
            QRect(cr.left(), cr.top(),
                  self._line_number_area_width(), cr.height())
        )

    def set_dark_theme(self, dark: bool) -> None:
        """Switch the gutter / current-line palette to match the app theme."""
        if dark == self._dark:
            return
        self._dark = dark
        self._highlight_current_line()
        self._ln_area.update()
        self.viewport().update()

    @property
    def _gutter(self) -> dict:
        """The active gutter colour set for the current theme."""
        return _GUTTER_DARK if self._dark else _GUTTER_LIGHT

    def _highlight_current_line(self) -> None:
        """Paint a subtle background band on the line containing the cursor."""
        if self.isReadOnly() or not self._line_numbers_enabled:
            self.setExtraSelections([])
            return
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(self._gutter["current"])
        sel.format.setProperty(
            QTextCharFormat.Property.FullWidthSelection, True  # type: ignore[attr-defined]
        )
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])

    def _paint_line_numbers(self, event) -> None:
        """Called by _LineNumberArea.paintEvent — draw line numbers in the gutter."""
        gutter = self._gutter
        painter = QPainter(self._ln_area)
        painter.fillRect(event.rect(), gutter["bg"])

        block        = self.firstVisibleBlock()
        block_num    = block.blockNumber()
        offset       = self.contentOffset()
        geom         = self.blockBoundingGeometry(block).translated(offset)
        top          = round(geom.top())
        bottom       = top + round(self.blockBoundingRect(block).height())
        current_line = self.textCursor().blockNumber()
        line_h       = self.fontMetrics().height()
        gutter_w     = self._ln_area.width()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(
                    gutter["active"] if block_num == current_line else gutter["normal"]
                )
                painter.drawText(
                    0, top, gutter_w - 4, line_h,
                    Qt.AlignmentFlag.AlignRight,
                    str(block_num + 1),
                )
            block     = block.next()
            top       = bottom
            bottom    = top + round(self.blockBoundingRect(block).height())
            block_num += 1

    def set_line_numbers_enabled(self, enabled: bool) -> None:
        """Show or hide the line-number gutter and current-line highlight."""
        self._line_numbers_enabled = enabled
        self._ln_area.setVisible(enabled)
        self._update_viewport_margins()
        self._highlight_current_line()
        self.viewport().update()

    # ------------------------------------------------------------------ #
    #  Autocomplete                                                        #
    # ------------------------------------------------------------------ #

    def set_completer_words(self, words: list[str]) -> None:
        """Replace the word list without touching the enabled/disabled state."""
        completer = QCompleter(words, self)
        completer.setWidget(self)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.activated.connect(self.insert_completion)
        self._completer = completer
        # _completer_enabled is managed solely by set_autocomplete_enabled();
        # never reset it here.

    def set_autocomplete_enabled(self, enabled: bool) -> None:
        """Enable or disable auto-complete."""
        self._completer_enabled = enabled
        if not enabled and self._completer:
            self._completer.popup().hide()

    def insert_completion(self, completion: str) -> None:
        if self._completer is None:
            return
        tc = self.textCursor()
        tc.movePosition(
            QTextCursor.MoveOperation.Left,
            QTextCursor.MoveMode.KeepAnchor,
            len(self._completer.completionPrefix()),
        )
        tc.insertText(completion)
        self.setTextCursor(tc)

    def _text_under_cursor(self) -> str:
        tc = self.textCursor()
        tc.select(QTextCursor.SelectionType.WordUnderCursor)
        return tc.selectedText()

    def focusInEvent(self, event) -> None:
        if self._completer:
            self._completer.setWidget(self)
        super().focusInEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._completer and self._completer.popup().isVisible():
            if event.key() in (
                Qt.Key.Key_Enter, Qt.Key.Key_Return,
                Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
            ):
                event.ignore()
                return

        # Pass through immediately when autocomplete is disabled
        if not self._completer_enabled:
            super().keyPressEvent(event)
            return

        is_shortcut = (
            (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            and event.key() == Qt.Key.Key_Space
        )
        if not self._completer or not is_shortcut:
            super().keyPressEvent(event)

        ctrl_or_shift = event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        )
        if not self._completer or (ctrl_or_shift and not event.text()):
            return

        eow = "~!@#$%^&*()_+{}|:\"<>?,./;'[]\\-="
        has_modifier = (
            event.modifiers() != Qt.KeyboardModifier.NoModifier
        ) and not ctrl_or_shift
        prefix = self._text_under_cursor()

        if not is_shortcut and (
            has_modifier or not event.text()
            or len(prefix) < 2 or event.text()[-1] in eow
        ):
            self._completer.popup().hide()
            return

        if prefix != self._completer.completionPrefix():
            self._completer.setCompletionPrefix(prefix)
            self._completer.popup().setCurrentIndex(
                self._completer.completionModel().index(0, 0)
            )

        cr = self.cursorRect()
        cr.setWidth(
            self._completer.popup().sizeHintForColumn(0)
            + self._completer.popup().verticalScrollBar().sizeHint().width()
        )
        self._completer.complete(cr)


# =========================================================================== #
#  EditorTab                                                                   #
# =========================================================================== #

class EditorTab(QWidget):
    """
    A single editor tab containing:
      * Header bar with a Parameters toggle button
      * Syntax-highlighted SQLEditor (line numbers + autocomplete)
      * Collapsible ParamsPanel
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
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
        self.editor = SQLEditor()
        self.editor.setPlaceholderText(
            "-- Enter SQL here.  Separate statements with semicolons.\n"
            "-- F5  -- Execute all tabs\n"
            "-- Ctrl+F5  -- Execute statement at cursor\n"
            "-- Ctrl+Enter  -- Execute this tab\n\n"
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

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def get_sql(self) -> str:
        """Return the selection if any, otherwise the full editor content."""
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText().replace(" ", "\n")
        return self.editor.toPlainText()

    def has_selection(self) -> bool:
        return self.editor.textCursor().hasSelection()

    def set_sql(self, sql: str) -> None:
        self.editor.setPlainText(sql)

    def insert_sql(self, sql: str) -> None:
        self.editor.insertPlainText(sql)

    def get_params(self) -> dict[str, str]:
        return self.params_panel.get_params()

    def update_completer_words(self, schema_words: list[str]) -> None:
        """Merge schema-specific identifiers with default SQL keywords."""
        all_words = sorted(set(KEYWORDS) | set(FUNCTIONS) | set(schema_words))
        self.editor.set_completer_words(all_words)

    def set_autocomplete_enabled(self, enabled: bool) -> None:
        """Enable or disable the SQL auto-completer."""
        self.editor.set_autocomplete_enabled(enabled)

    def set_line_numbers_enabled(self, enabled: bool) -> None:
        """Show or hide the line-number gutter."""
        self.editor.set_line_numbers_enabled(enabled)

    def set_dark_theme(self, dark: bool) -> None:
        """Match the editor gutter / current-line highlight to the app theme."""
        self.editor.set_dark_theme(dark)
