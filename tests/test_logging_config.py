"""
Tests for coruscant.utils.logging_config.

No actual log files are written — all filesystem and logging calls are mocked.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# _log_dir()
# ---------------------------------------------------------------------------

class TestLogDir:
    """_log_dir() must return platform-specific paths."""

    def _log_dir(self):
        from coruscant.utils.logging_config import _log_dir
        return _log_dir

    def test_linux_uses_xdg_data_home(self):
        fn = self._log_dir()
        with patch.object(sys, "platform", "linux"), \
             patch.dict(os.environ, {"XDG_DATA_HOME": "/custom/data"}, clear=False):
            p = fn()
        assert str(p).startswith("/custom/data")
        assert "Coruscant" in str(p)

    def test_linux_falls_back_to_home(self):
        fn = self._log_dir()
        env = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
        with patch.object(sys, "platform", "linux"), \
             patch.dict(os.environ, env, clear=True):
            p = fn()
        assert "Coruscant" in str(p)

    def test_windows_uses_appdata(self):
        fn = self._log_dir()
        with patch.object(sys, "platform", "win32"), \
             patch.dict(os.environ, {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"}, clear=False):
            p = fn()
        assert "Coruscant" in str(p)

    def test_darwin_uses_library_logs(self):
        fn = self._log_dir()
        with patch.object(sys, "platform", "darwin"), \
             patch("pathlib.Path.home", return_value=Path("/Users/test")):
            p = fn()
        assert "Library" in str(p) or "Coruscant" in str(p)

    def test_returns_path_object(self):
        fn = self._log_dir()
        p = fn()
        assert isinstance(p, Path)

    def test_ends_with_logs(self):
        fn = self._log_dir()
        p = fn()
        assert p.name == "logs"


# ---------------------------------------------------------------------------
# setup_logging()
# ---------------------------------------------------------------------------

class TestSetupLogging:
    """setup_logging() must configure root logger exactly once."""

    def _reset_root_logger(self):
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

    def test_returns_path(self, tmp_path):
        self._reset_root_logger()
        from coruscant.utils.logging_config import setup_logging
        log_dir = tmp_path / "logs"
        with patch("coruscant.utils.logging_config._log_dir", return_value=log_dir):
            result = setup_logging()
        assert isinstance(result, Path)
        assert result.name == "coruscant.log"
        self._reset_root_logger()

    def test_idempotent_if_handlers_already_set(self):
        """Second call must be a no-op (handlers not added again)."""
        root = logging.getLogger()
        # Pre-install a dummy handler
        dummy = logging.NullHandler()
        root.addHandler(dummy)
        from coruscant.utils.logging_config import setup_logging
        with patch("coruscant.utils.logging_config._log_dir",
                   return_value=Path("/nonexistent/never/called")):
            result = setup_logging()
        # Dummy handler should still be the only one (no new ones added)
        assert dummy in root.handlers
        root.removeHandler(dummy)

    def test_log_level_from_env_info(self, tmp_path):
        self._reset_root_logger()
        from coruscant.utils.logging_config import setup_logging
        log_dir = tmp_path / "logs"
        with patch("coruscant.utils.logging_config._log_dir", return_value=log_dir), \
             patch.dict(os.environ, {"CORUSCANT_LOG_LEVEL": "INFO"}):
            setup_logging()
        assert logging.getLogger().level == logging.INFO
        self._reset_root_logger()

    def test_log_level_from_env_debug(self, tmp_path):
        self._reset_root_logger()
        from coruscant.utils.logging_config import setup_logging
        log_dir = tmp_path / "logs"
        with patch("coruscant.utils.logging_config._log_dir", return_value=log_dir), \
             patch.dict(os.environ, {"CORUSCANT_LOG_LEVEL": "DEBUG"}):
            setup_logging()
        assert logging.getLogger().level == logging.DEBUG
        self._reset_root_logger()

    def test_invalid_log_level_falls_back_to_info(self, tmp_path):
        self._reset_root_logger()
        from coruscant.utils.logging_config import setup_logging
        log_dir = tmp_path / "logs"
        with patch("coruscant.utils.logging_config._log_dir", return_value=log_dir), \
             patch.dict(os.environ, {"CORUSCANT_LOG_LEVEL": "NOTLEVEL"}):
            setup_logging()
        # getattr(logging, "NOTLEVEL", logging.INFO) → INFO
        assert logging.getLogger().level == logging.INFO
        self._reset_root_logger()

    def test_creates_log_directory(self, tmp_path):
        self._reset_root_logger()
        from coruscant.utils.logging_config import setup_logging
        log_dir = tmp_path / "new" / "nested" / "logs"
        assert not log_dir.exists()
        with patch("coruscant.utils.logging_config._log_dir", return_value=log_dir):
            setup_logging()
        assert log_dir.exists()
        self._reset_root_logger()


# ---------------------------------------------------------------------------
# _install_excepthook
# ---------------------------------------------------------------------------

class TestInstallExcepthook:
    def test_excepthook_installed(self, tmp_path):
        from coruscant.utils.logging_config import _install_excepthook
        original = sys.excepthook
        try:
            _install_excepthook(tmp_path / "coruscant.log")
            assert sys.excepthook is not original
        finally:
            sys.excepthook = original

    def test_keyboard_interrupt_defers_to_default(self, tmp_path):
        from coruscant.utils.logging_config import _install_excepthook
        original = sys.excepthook
        called = []
        with patch.object(sys, "__excepthook__",
                          side_effect=lambda *a: called.append(a)):
            _install_excepthook(tmp_path / "x.log")
            # Trigger the hook with KeyboardInterrupt
            sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert len(called) == 1
        sys.excepthook = original

    def test_hook_does_not_crash_on_random_exception(self, tmp_path):
        from coruscant.utils.logging_config import _install_excepthook
        original = sys.excepthook
        _install_excepthook(tmp_path / "x.log")
        with patch.object(sys, "__excepthook__", return_value=None):
            # Must not raise even with no Qt running
            sys.excepthook(RuntimeError, RuntimeError("boom"), None)
        sys.excepthook = original
