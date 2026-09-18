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
