"""
coruscant.ui.widgets.tab_bar
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pinnable, renameable tab bar for the result QTabWidget.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabBar, QMenu, QInputDialog
from PySide6.QtCore import Qt


class PinnableTabBar(QTabBar):
    """
    QTabBar that adds right-click and double-click behaviour to result tabs.

    Right-click context menu
    ------------------------
    • Rename… – prompts for a new title
    • Pin / Unpin – pinned tabs survive the next Execute (shown with 📌)

    Double-click – inline rename.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pinned: dict[int, bool] = {}

    # ── Event overrides ──────────────────────────────────────────────── #

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            idx = self.tabAt(event.position().toPoint())
            if idx >= 0:
                self._show_context_menu(idx, event.globalPosition().toPoint())
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self.tabAt(event.position().toPoint())
            if idx >= 0:
                self._rename_tab(idx)
                return
        super().mouseDoubleClickEvent(event)

    # ── Private helpers ──────────────────────────────────────────────── #

    def _show_context_menu(self, idx: int, global_pos) -> None:
        menu = QMenu(self)
        rename_act = menu.addAction("Rename…")
        pin_act    = menu.addAction("Unpin" if self._pinned.get(idx) else "Pin")
        chosen     = menu.exec(global_pos)
        if chosen == rename_act:
            self._rename_tab(idx)
        elif chosen == pin_act:
            self._toggle_pin(idx)

    def _rename_tab(self, idx: int) -> None:
        current = self.tabText(idx).removeprefix("📌 ")
        text, ok = QInputDialog.getText(self, "Rename Tab", "New name:", text=current)
        if ok and text.strip():
            title = text.strip()
            self.setTabText(idx, ("📌 " + title) if self._pinned.get(idx) else title)

    def _toggle_pin(self, idx: int) -> None:
        self._pinned[idx] = not self._pinned.get(idx, False)
        title = self.tabText(idx)
        if self._pinned[idx]:
            if not title.startswith("📌 "):
                self.setTabText(idx, "📌 " + title)
        else:
            self.setTabText(idx, title.removeprefix("📌 "))

    # ── Public helpers used by MainWindow ─────────────────────────────── #

    def is_pinned(self, idx: int) -> bool:
        return bool(self._pinned.get(idx, False))

    def on_tab_removed(self, idx: int) -> None:
        """Shift the pin map when a tab at *idx* is removed."""
        self._pinned = {
            (k - 1 if k > idx else k): v
            for k, v in self._pinned.items()
            if k != idx
        }

    def on_tab_added(self, idx: int) -> None:
        """Shift the pin map when a new tab is inserted at *idx*."""
        self._pinned = {
            (k + 1 if k >= idx else k): v
            for k, v in self._pinned.items()
        }
