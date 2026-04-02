"""Tests for package-level metadata."""
import coruscant


def test_version():
    assert coruscant.__version__ == "0.9.2"


def test_author():
    assert coruscant.__author__ == "Marwa Trust Mutemasango"


def test_app_name():
    assert coruscant.__app_name__ == "Coruscant"
