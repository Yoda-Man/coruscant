"""
tests/test_dashboard.py
~~~~~~~~~~~~~~~~~~~~~~~~
Structural tests for the Live Database Monitor dialog (v1.0.8).

These mirror the AST/source style of test_recovery.py: they verify the
dashboard's classes, methods, and wiring exist without importing PySide6
(which is not installed in CI). Behavioural coverage of the underlying
metrics lives in test_metrics.py.
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_DASH = "coruscant/ui/dialogs/dashboard.py"
_MAIN = "coruscant/ui/main_window.py"


def _src(rel):
    return (_ROOT / rel).read_text(encoding="utf-8")


def _tree(rel):
    return ast.parse(_src(rel))


def _fns(tree):
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _cls(tree):
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


# ---------------------------------------------------------------------------
# 1. dashboard.py structure
# ---------------------------------------------------------------------------

class TestDashboardStructure:

    def test_parses_cleanly_and_no_null_bytes(self):
        data = (_ROOT / _DASH).read_bytes()
        assert b"\x00" not in data
        ast.parse(data.decode("utf-8"))

    def test_dialog_class_exists(self):
        assert "DashboardDialog" in _cls(_tree(_DASH))

    def test_sparkline_class_exists(self):
        assert "Sparkline" in _cls(_tree(_DASH))

    def test_metric_worker_class_exists(self):
        assert "_MetricWorker" in _cls(_tree(_DASH))

    def test_kpi_helper_class_exists(self):
        assert "_Kpi" in _cls(_tree(_DASH))

    def test_key_methods_defined(self):
        fns = _fns(_tree(_DASH))
        for fn in ("_build_ui", "_refresh", "_on_metrics", "_update_kpis",
                   "_update_sparklines", "_update_details", "_apply_interval",
                   "closeEvent"):
            assert fn in fns, f"dashboard.py missing {fn}"

    def test_sparkline_paintevent_and_push(self):
        fns = _fns(_tree(_DASH))
        assert "paintEvent" in fns
        assert "push" in fns


# ---------------------------------------------------------------------------
# 2. dashboard.py behaviour markers (source-level)
# ---------------------------------------------------------------------------

class TestDashboardBehaviourMarkers:

    def test_uses_background_worker_qthread(self):
        assert "QThread" in _src(_DASH)

    def test_uses_qtimer_for_autorefresh(self):
        src = _src(_DASH)
        assert "QTimer" in src
        assert "timeout.connect" in src

    def test_is_non_modal(self):
        assert "setModal(False)" in _src(_DASH)

    def test_pulls_from_metrics_module(self):
        src = _src(_DASH)
        assert "core.metrics" in src
        assert "compute_rates" in src

    def test_defines_ten_detail_tabs(self):
        """_TAB_SPEC drives the tabbed detail area."""
        assert "_TAB_SPEC" in _src(_DASH)

    def test_graceful_error_marker(self):
        assert "__error__" in _src(_DASH)


# ---------------------------------------------------------------------------
# 3. MainWindow wiring for the Dashboard footer button
# ---------------------------------------------------------------------------

class TestMainWindowDashboardWiring:

    def test_dashboard_button_defined(self):
        assert "_sb_dashboard_btn" in _src(_MAIN)

    def test_on_dashboard_handler_defined(self):
        assert "_on_dashboard" in _fns(_tree(_MAIN))

    def test_button_clicked_wired_to_handler(self):
        src = _src(_MAIN)
        assert "_sb_dashboard_btn.clicked.connect(self._on_dashboard)" in src

    def test_dashboard_button_visible_when_connected(self):
        assert "_sb_dashboard_btn.setVisible(connected)" in _src(_MAIN)

    def test_handler_imports_dashboard_dialog(self):
        assert "DashboardDialog" in _src(_MAIN)

    def test_all_footer_buttons_present(self):
        src = _src(_MAIN)
        for btn in ("_sb_doctor_btn", "_sb_recovery_btn", "_sb_dashboard_btn"):
            assert btn in src


# ---------------------------------------------------------------------------
# 4. Signal-handler integrity: .connect(self.X) targets must be defined
# ---------------------------------------------------------------------------

def test_dashboard_connect_targets_defined():
    tree = _tree(_DASH)
    defined = _fns(tree)
    # Slots inherited from QDialog/QWidget are valid connect targets.
    inherited = {"accept", "reject", "close", "show", "hide",
                 "raise_", "activateWindow", "update", "repaint"}
    defined |= inherited
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "connect" and node.args:
            arg = node.args[0]
            if (isinstance(arg, ast.Attribute)
                    and isinstance(arg.value, ast.Name)
                    and arg.value.id == "self"
                    and arg.attr not in defined):
                missing.append(arg.attr)
    assert not missing, f"dashboard.py .connect(self.X) undefined: {missing}"
