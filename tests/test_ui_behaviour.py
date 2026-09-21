"""
Runtime behavioural tests for MainWindow, driven through a real Qt event loop.

Why this module exists
----------------------
Every other UI test in this suite reads the AST. That catches a missing method
or a handler wired to nothing, but it cannot see what Qt does with the calls,
and two defects lived precisely in that gap:

  * ``setTabsClosable(True)`` and ``setMovable(True)`` were called on the
    editor ``QTabWidget`` *before* ``setTabBar()`` installed a new bar. Those
    flags live on the tab bar, so replacing it discarded both: the close
    buttons never rendered and tabs could not be dragged. The source contained
    every call a structural test would look for, and none of them took effect.

  * ``_close_editor_tab`` looked a tab's result area up by index in the result
    stack. Tab order and stack order diverge the moment a tab is dragged, so
    closing one destroyed a different tab's results and left the survivor
    pointing at a deleted widget.

Both are only visible by building the window and asking Qt what it actually
did, which is what these tests do.

Why this module runs in its own process
---------------------------------------
``tests/test_worker.py`` and ``tests/test_ui_ast.py`` deliberately delete the
real PySide6 modules from ``sys.modules`` and install Qt-free stubs, so the
modules under test can be imported without Qt. Dropping the last reference to
PySide6 can finalise the shiboken extension underneath it, and constructing a
real widget afterwards is then undefined behaviour — in practice a Windows
access violation partway through ``MainWindow.__init__``.

Live Qt therefore cannot safely share a process with the rest of this suite.
The module skips unless ``CORUSCANT_QT_TESTS=1``, and CI runs it as a separate
pytest invocation — the same arrangement ``tests/test_live_sql.py`` uses for a
live PostgreSQL::

    CORUSCANT_QT_TESTS=1 pytest tests/test_ui_behaviour.py
"""
from __future__ import annotations

import os

import pytest

QT_TESTS = os.environ.get("CORUSCANT_QT_TESTS", "").strip() == "1"

pytestmark = pytest.mark.skipif(
    not QT_TESTS,
    reason="Qt runtime tests run in their own process: set CORUSCANT_QT_TESTS=1",
)

# Qt must be told to run windowless before any QApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    """
    One QApplication for the module; Qt allows only a single instance.

    Imported here rather than at module scope so that a collection pass with
    the flag unset touches no Qt at all.
    """
    pytest.importorskip("PySide6", reason="PySide6 not installed")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        try:
            app = QApplication([])
        except Exception as exc:                      # pragma: no cover
            pytest.skip(f"Qt could not start: {exc}")
    return app


@pytest.fixture
def window(qapp):
    from coruscant.ui.main_window import MainWindow
    w = MainWindow()
    yield w
    w.close()


class _FakeDB:
    """
    Just what _update_ui_state() reads off the manager, plus the disconnect()
    that closeEvent() calls during teardown when the stub reports a connection.
    """

    def __init__(self, connected: bool, has_last_params: bool = False) -> None:
        self.is_connected = connected
        self.has_last_params = has_last_params
        self.disconnect_calls = 0

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.is_connected = False


def _areas(window):
    """Each editor tab's result area, in tab order."""
    return [window._editor_tabs.widget(i).property("result_area")
            for i in range(window._editor_tabs.count())]


def _area_is_live(window, area) -> bool:
    return area is not None and window._result_stack.indexOf(area) >= 0


# ---------------------------------------------------------------------------
# Closing tabs
# ---------------------------------------------------------------------------

class TestEditorTabsAreClosable:
    """
    The close button is the only discoverable way to close a tab — Ctrl+W is
    invisible to anyone who has not read the shortcut list.
    """

    def test_close_buttons_are_enabled(self, window):
        assert window._editor_tabs.tabsClosable() is True

    def test_the_flag_reached_the_installed_tab_bar(self, window):
        """
        setTabBar() replaces the bar and discards flags set on the old one, so
        asking the QTabWidget is not enough — the live bar must carry it.
        """
        assert window._editor_tabs.tabBar().tabsClosable() is True

    def test_tabs_are_movable(self, window):
        assert window._editor_tabs.isMovable() is True
        assert window._editor_tabs.tabBar().isMovable() is True

    def test_result_tabs_are_closable(self, window):
        _container, _placeholder, tabs = window._create_result_area()
        assert tabs.tabsClosable() is True
        assert tabs.tabBar().tabsClosable() is True


class TestClosingRemovesTheTab:
    def test_closing_reduces_the_count(self, window):
        window._add_editor_tab("SELECT 1;")
        window._add_editor_tab("SELECT 2;")
        before = window._editor_tabs.count()
        window._close_editor_tab(1)
        assert window._editor_tabs.count() == before - 1

    def test_closing_removes_that_tabs_result_area(self, window):
        window._add_editor_tab("SELECT 1;")
        doomed = window._editor_tabs.widget(1).property("result_area")
        window._close_editor_tab(1)
        assert not _area_is_live(window, doomed)

    def test_closing_keeps_the_other_tabs_areas(self, window):
        window._add_editor_tab("SELECT 1;")
        window._add_editor_tab("SELECT 2;")
        keep = [_areas(window)[0], _areas(window)[2]]
        window._close_editor_tab(1)
        assert all(_area_is_live(window, a) for a in keep)

    def test_close_current_closes_the_selected_tab(self, window):
        """The Ctrl+W path."""
        window._add_editor_tab("SELECT 1;")
        window._add_editor_tab("SELECT 2;")
        window._editor_tabs.setCurrentIndex(1)
        target = window._editor_tabs.widget(1)
        window._close_current_editor_tab()
        assert all(window._editor_tabs.widget(i) is not target
                   for i in range(window._editor_tabs.count()))

    def test_closing_every_tab_leaves_one_behind(self, window):
        """
        The last tab clears rather than closing: an editor with no tabs has no
        way back to one.
        """
        window._add_editor_tab("SELECT 1;")
        window._add_editor_tab("SELECT 2;")
        for _ in range(6):
            window._close_editor_tab(0)
        assert window._editor_tabs.count() == 1

    def test_closing_the_last_tab_clears_its_text(self, window):
        tab = window._editor_tabs.widget(0)
        tab.set_sql("SELECT 'leftover';")
        window._close_editor_tab(0)
        assert window._editor_tabs.count() == 1
        assert tab.editor.toPlainText() == ""


class TestClosingAfterReordering:
    """
    Dragging a tab is why the result area must be looked up on the tab and not
    by index. With tabs movable, an index-based lookup closes the wrong tab's
    results — and it only became reachable once the movable flag started
    taking effect.
    """

    def _reorder(self, window):
        window._add_editor_tab("SELECT 1;")
        window._add_editor_tab("SELECT 2;")
        window._add_editor_tab("SELECT 3;")
        window._editor_tabs.tabBar().moveTab(0, window._editor_tabs.count() - 1)

    def test_tab_order_and_stack_order_really_do_diverge(self, window):
        """Guards the guard: without this the tests below prove nothing."""
        self._reorder(window)
        stack_positions = [window._result_stack.indexOf(a) for a in _areas(window)]
        assert stack_positions != sorted(stack_positions)

    def test_survivors_keep_their_result_areas(self, window):
        self._reorder(window)
        survivors = [a for i, a in enumerate(_areas(window)) if i != 0]
        window._close_editor_tab(0)
        assert all(_area_is_live(window, a) for a in survivors)

    def test_the_closed_tabs_area_is_the_one_removed(self, window):
        self._reorder(window)
        doomed = _areas(window)[0]
        window._close_editor_tab(0)
        assert not _area_is_live(window, doomed)

    def test_the_visible_results_still_follow_the_selected_tab(self, window):
        self._reorder(window)
        window._close_editor_tab(0)
        window._editor_tabs.setCurrentIndex(0)
        current = window._editor_tabs.currentWidget().property("result_area")
        assert window._result_stack.currentWidget() is current


# ---------------------------------------------------------------------------
# The Connections action follows the connection
# ---------------------------------------------------------------------------

class TestConnectionsActionVisibility:
    """
    One connection action on the toolbar at a time: Connections while
    disconnected, Disconnect while connected.
    """

    def test_connections_is_visible_when_disconnected(self, window):
        window._db = _FakeDB(connected=False)
        window._update_ui_state()
        assert window._act_connect.isVisible() is True

    def test_connections_is_hidden_when_connected(self, window):
        window._db = _FakeDB(connected=True)
        window._update_ui_state()
        assert window._act_connect.isVisible() is False

    def test_connections_comes_back_after_disconnecting(self, window):
        window._db = _FakeDB(connected=True)
        window._update_ui_state()
        window._db = _FakeDB(connected=False, has_last_params=True)
        window._update_ui_state()
        assert window._act_connect.isVisible() is True

    def test_disconnect_is_the_mirror_image(self, window):
        for connected in (True, False):
            window._db = _FakeDB(connected=connected)
            window._update_ui_state()
            assert window._act_disconnect.isVisible() is connected
            assert window._act_connect.isVisible() is (not connected)

    def test_exactly_one_of_the_two_is_ever_visible(self, window):
        for connected in (True, False):
            window._db = _FakeDB(connected=connected)
            window._update_ui_state()
            visible = [window._act_connect.isVisible(),
                       window._act_disconnect.isVisible()]
            assert visible.count(True) == 1, visible

    def test_a_reconnectable_session_still_offers_connections(self, window):
        """
        Disconnected but with remembered parameters is still disconnected —
        the action has to be reachable to get back in.
        """
        window._db = _FakeDB(connected=False, has_last_params=True)
        window._update_ui_state()
        assert window._act_connect.isVisible() is True


# ---------------------------------------------------------------------------
# The results grid must not reorder what the server returned
# ---------------------------------------------------------------------------

# Column 0 deliberately unsorted, rows in the order an
#   ORDER BY "modifieddate" DESC
# would hand back. If anything sorts by column 0, the dates scramble visibly.
_COLUMNS = ["tgapplicationid", "entitytype", "modifieddate"]
_ROWS = [
    (500, "A", "2026-08-21 12:07:33"),
    (100, "B", "2026-07-23 10:34:55"),
    (900, "C", "2026-06-02 09:50:31"),
    (300, "D", "2026-04-23 11:03:11"),
    (700, "E", "2026-04-06 07:58:42"),
]


@pytest.fixture
def grid(qapp):
    from coruscant.ui.widgets.results import ResultGrid
    g = ResultGrid(_COLUMNS, _ROWS, label="Query 1")
    yield g
    g.deleteLater()


def _displayed(grid):
    t = grid._table
    return [tuple(t.item(r, c).text() for c in range(t.columnCount()))
            for r in range(t.rowCount())]


def _visible(grid):
    t = grid._table
    return [row for r, row in enumerate(_displayed(grid)) if not t.isRowHidden(r)]


class TestResultOrderIsTheServersOrder:
    """
    A SQL tool that reorders results has thrown away the user's ORDER BY.

    setSortingEnabled(True) sorts immediately, by whatever the current sort
    indicator is — column 0 on a fresh table. Enabling it while building the
    grid therefore re-sorted every result set by its first column, and an
    ORDER BY on any other column was silently discarded.
    """

    def test_rows_appear_in_the_order_they_were_given(self, grid):
        assert [r[2] for r in _displayed(grid)] == [r[2] for r in _ROWS]

    def test_the_first_column_is_not_sorted(self, grid):
        """Guards the guard: fixture data must be able to expose the defect."""
        ids = [int(r[0]) for r in _displayed(grid)]
        assert ids != sorted(ids)
        assert ids != sorted(ids, reverse=True)

    def test_sorting_is_off_until_asked_for(self, grid):
        assert grid._table.isSortingEnabled() is False

    def test_no_sort_indicator_is_advertised(self, grid):
        assert grid._table.horizontalHeader().isSortIndicatorShown() is False

    def test_a_single_row_result_is_unharmed(self, qapp):
        from coruscant.ui.widgets.results import ResultGrid
        g = ResultGrid(_COLUMNS, [_ROWS[0]], label="Q")
        assert _displayed(g)[0][2] == _ROWS[0][2]

    def test_an_empty_result_does_not_raise(self, qapp):
        from coruscant.ui.widgets.results import ResultGrid
        g = ResultGrid(_COLUMNS, [], label="Q")
        assert _displayed(g) == []


class TestSortingOnDemand:
    """
    The manual promises "Click any column header to sort by that column".
    Deferring it must not take that away.
    """

    def test_clicking_a_header_sorts_by_it(self, grid):
        grid._table.horizontalHeader().sectionClicked.emit(0)
        ids = [int(r[0]) for r in _displayed(grid)]
        assert ids == sorted(ids)

    def test_clicking_enables_sorting_for_later_clicks(self, grid):
        grid._table.horizontalHeader().sectionClicked.emit(0)
        assert grid._table.isSortingEnabled() is True

    def test_clicking_reveals_the_sort_indicator(self, grid):
        grid._table.horizontalHeader().sectionClicked.emit(0)
        assert grid._table.horizontalHeader().isSortIndicatorShown() is True

    def test_a_later_column_can_be_sorted_too(self, grid):
        grid._table.horizontalHeader().sectionClicked.emit(2)
        dates = [r[2] for r in _displayed(grid)]
        assert dates == sorted(dates)

    def test_the_handler_does_not_re_sort_once_enabled(self, grid):
        """
        After the first click Qt owns header clicks. Re-running our handler
        would fight it and snap the grid back to ascending.
        """
        from PySide6.QtCore import Qt

        hdr = grid._table.horizontalHeader()
        hdr.sectionClicked.emit(0)
        grid._table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        grid._on_header_clicked(0)
        ids = [int(r[0]) for r in _displayed(grid)]
        assert ids == sorted(ids, reverse=True)


class TestFilteringFollowsTheDisplayedRows:
    """
    The filter hid rows by their position in the source list while calling
    setRowHidden() with that same number on the table. Those agree only until
    the grid is sorted, after which it hid the wrong rows.
    """

    def test_filter_matches_the_right_row_unsorted(self, grid):
        grid._apply_filter("2026-06-02")
        assert _visible(grid) == [("900", "C", "2026-06-02 09:50:31")]

    def test_filter_matches_the_right_row_after_sorting(self, grid):
        grid._table.horizontalHeader().sectionClicked.emit(0)
        grid._apply_filter("2026-06-02")
        assert _visible(grid) == [("900", "C", "2026-06-02 09:50:31")]

    def test_filter_on_the_first_column_after_sorting(self, grid):
        grid._table.horizontalHeader().sectionClicked.emit(2)
        grid._apply_filter("700")
        assert _visible(grid) == [("700", "E", "2026-04-06 07:58:42")]

    def test_clearing_the_filter_shows_everything_again(self, grid):
        grid._table.horizontalHeader().sectionClicked.emit(0)
        grid._apply_filter("2026-06-02")
        grid._apply_filter("")
        assert len(_visible(grid)) == len(_ROWS)

    def test_a_filter_matching_nothing_hides_everything(self, grid):
        grid._apply_filter("no such value anywhere")
        assert _visible(grid) == []

    def test_nulls_are_still_findable_after_sorting(self, qapp):
        from coruscant.ui.widgets.results import ResultGrid
        g = ResultGrid(_COLUMNS, [(1, "x", None), (2, "y", "2026-01-01")], label="Q")
        g._table.horizontalHeader().sectionClicked.emit(0)
        g._apply_filter("null")
        assert [r[0] for r in _visible(g)] == ["1"]

    def test_source_row_maps_back_correctly_after_sorting(self, grid):
        grid._table.horizontalHeader().sectionClicked.emit(0)
        ids_in_display_order = [int(r[0]) for r in _displayed(grid)]
        mapped = [_ROWS[grid._source_row(r)][0]
                  for r in range(grid._table.rowCount())]
        assert mapped == ids_in_display_order
