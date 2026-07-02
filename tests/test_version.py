"""Tests for package-level metadata."""
import coruscant


def test_version():
    assert coruscant.__version__ == "1.0.8"


def test_author():
    assert coruscant.__author__ == "Marwa Trust Mutemasango"


def test_app_name():
    assert coruscant.__app_name__ == "Coruscant"


# ---------------------------------------------------------------------------
# Import-safety: every core module must be importable without PySide6
# ---------------------------------------------------------------------------

def test_core_modules_importable_without_qt():
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


def test_test_files_parse_cleanly():
    """
    The test files themselves must not be truncated.
    (test_version.py was itself truncated in v1.0.6 — this guards against recurrence.)
    """
    import ast, os
    tests_dir = os.path.dirname(__file__)
    failures = []
    for fname in os.listdir(tests_dir):
        if not fname.endswith('.py'):
            continue
        fpath = os.path.join(tests_dir, fname)
        data = open(fpath, 'rb').read()
        if b'\x00' in data:
            failures.append(f"{fpath}: contains null bytes")
            continue
        try:
            ast.parse(data.decode('utf-8'))
        except SyntaxError as e:
            failures.append(f"{fpath}:{e.lineno}: {e.msg}")
    if failures:
        raise AssertionError(
            f"{len(failures)} test file(s) failed to parse:\n" +
            "\n".join(f"  {f}" for f in failures)
        )


def test_main_window_signal_handlers_all_defined():
    """
    Every .connect(self.X) in main_window.py must have X defined.
    Regression guard for the v1.0.0 crash where _on_results etc. were deleted
    but still referenced in .connect() calls.
    """
    import ast, os
    path = os.path.join(os.path.dirname(__file__), '..', 'coruscant', 'ui', 'main_window.py')
    src  = open(path, encoding='utf-8').read()
    tree = ast.parse(src)

    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    referenced = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "connect"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if (isinstance(arg, ast.Attribute) and
                isinstance(arg.value, ast.Name) and
                arg.value.id == "self"):
            referenced[arg.attr] = getattr(node, 'lineno', 0)

    missing = {m: ln for m, ln in referenced.items() if m not in defined}
    if missing:
        lines = "\n".join(
            f"  line {ln}: self.{m}"
            for m, ln in sorted(missing.items(), key=lambda x: x[1])
        )
        raise AssertionError(
            f"main_window.py: .connect(self.X) referenced but X not defined:\n{lines}"
        )


def test_main_window_file_not_truncated():
    """Guards against Edit-tool truncation of main_window.py."""
    import ast, os
    path = os.path.join(os.path.dirname(__file__), '..', 'coruscant', 'ui', 'main_window.py')
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert 'MainWindow' in classes, "MainWindow class missing — file may be truncated"
    assert src.count('\n') >= 500, f"main_window.py suspiciously short: {src.count(chr(10))} lines"


def test_version_consistent_across_files():
    """__init__.py version must match Version: line in main.py."""
    import re, os
    root = os.path.join(os.path.dirname(__file__), '..')
    pkg_version = coruscant.__version__
    main_src = open(os.path.join(root, 'main.py'), encoding='utf-8').read()
    m = re.search(r'Version:\s*([\d.]+)', main_src)
    assert m, "Could not find 'Version: X.Y.Z' in main.py"
    assert m.group(1) == pkg_version, (
        f"Version mismatch: __init__.py={pkg_version!r}, main.py={m.group(1)!r}"
    )
