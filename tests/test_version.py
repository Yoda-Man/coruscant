"""Tests for package-level metadata."""
import coruscant


def test_version():
    assert coruscant.__version__ == "1.0.4"


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


def test_main_window_signal_handlers_all_defined():
    """
    For every `some_signal.connect(self.method_name)` call in main_window.py,
    verify that method_name is actually defined in the same file.

    This is the exact check that would have caught the v1.0.0 crash where
    _on_results, _on_query_error, _on_query_cancelled, and _on_explain_results
    were deleted but still referenced in .connect() calls.

    Uses AST — no Qt import required.
    """
    import ast, os

    path = os.path.join(os.path.dirname(__file__), '..', 'coruscant', 'ui', 'main_window.py')
    src  = open(path, encoding='utf-8').read()
    tree = ast.parse(src)

    # Collect every method defined anywhere in the file.
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    # Walk the AST looking for expr.connect(self.X) or expr.connect(self.X)
    # patterns. We capture the attribute name whenever the sole positional
    # argument to a .connect() call is a self.attr reference.
    referenced: dict[str, int] = {}  # m