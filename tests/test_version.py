"""Tests for package-level metadata."""
import coruscant


def test_version():
    assert coruscant.__version__ == "1.0.0"


def test_author():
    assert coruscant.__author__ == "Marwa Trust Mutemasango"


def test_app_name():
    assert coruscant.__app_name__ == "Coruscant"


# ---------------------------------------------------------------------------
# Import-safety: every core module must be importable without PySide6
# ---------------------------------------------------------------------------

def test_core_modules_importable_without_qt():
    """
    All coruscant.core modules must be importable without PySide6.
    This catches truncated files, syntax errors, and bad top-level imports
    before the application is ever launched.
    """
    import ast, os
    core_dir = os.path.join(os.path.dirname(__file__), '..', 'coruscant', 'core')
    for fname in os.listdir(core_dir):
        if not fname.endswith('.py'):
            continue
        fpath = os.path.join(core_dir, fname)
        src = open(fpath, encoding='utf-8').read()
        try:
            ast.parse(src)
        except SyntaxError as e:
            raise AssertionError(f"Syntax error in {fname}: {e}") from e


def test_ui_modules_parse_cleanly():
    """
    Every .py file under coruscant/ui must parse without syntax errors.
    This is the earliest possible check for truncated or corrupt files —
    a regression guard for the class of bugs we have seen in main_window.py.
    """
    import ast, os
    ui_root = os.path.join(os.path.dirname(__file__), '..', 'coruscant')
    failures = []
    for dirpath, dirnames, filenames in os.walk(ui_root):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fname in filenames:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                data = open(fpath, 'rb').read()
                if b'\x00' in data:
                    failures.append(f"{fpath}: contains null bytes")
                    continue
                ast.parse(data.decode('utf-8'))
            except SyntaxError as e:
                failures.append(f"{fpath}:{e.lineno}: {e.msg}")

    if failures:
        raise AssertionError(
            f"{len(failures)} file(s) failed to parse:\n" +
            "\n".join(f"  {f}" for f in failures)
        )


def test_main_window_has_required_methods():
    """
    Verify that the methods wired up in _build_shortcuts are actually
    defined on MainWindow — the exact failure mode seen in the crash reports.
    """
    import ast, os
    path = os.path.join(os.path.dirname(__file__), '..', 'coruscant', 'ui', 'main_window.py')
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)

    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            defined.add(node.name)

    required = [
        '_on_run_all_tabs',
        '_advance_run_all',
        '_on_execute_at_cursor',
        '_statement_at_cursor',
        '_on_guide_requested',
        '_on_open_script_manager',
        '_on_script_manager_load',
        '_on_autocomplete_changed',
        '_on_line_numbers_changed',
        '_on_editor_tab_manually_renamed',
    ]
    missing = [m for m in required if m not in defined]
    if missing:
        raise AssertionError(
            f"MainWindow is missing {len(missing)} required method(s): "
            + ", ".join(missing)
        )
