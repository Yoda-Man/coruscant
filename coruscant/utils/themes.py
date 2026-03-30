"""
coruscant.utils.themes
~~~~~~~~~~~~~~~~~~~~~~
Light / dark theme management for the Coruscant application.

Public API
----------
apply_dark(app)            – VS Code-inspired dark palette
apply_light(app)           – standard Fusion light palette
current_theme(settings)    – returns 'dark' or 'light'
save_theme(settings, name) – persists the choice to QSettings

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt, QSettings

_SETTINGS_KEY  = "ui/theme"
_DEFAULT_THEME = "dark"


def apply_dark(app: QApplication) -> None:
    """Apply a dark Fusion palette (VS Code-inspired) to *app*."""
    p = QPalette()

    bg      = QColor(30,  30,  30)
    bg_alt  = QColor(40,  40,  40)
    surface = QColor(37,  37,  38)
    text    = QColor(212, 212, 212)
    mid     = QColor(60,  60,  60)
    btn     = QColor(50,  50,  50)
    accent  = QColor(67,  97,  238)

    p.setColor(QPalette.ColorRole.Window,          surface)
    p.setColor(QPalette.ColorRole.WindowText,      text)
    p.setColor(QPalette.ColorRole.Base,            bg)
    p.setColor(QPalette.ColorRole.AlternateBase,   bg_alt)
    p.setColor(QPalette.ColorRole.ToolTipBase,     bg)
    p.setColor(QPalette.ColorRole.ToolTipText,     text)
    p.setColor(QPalette.ColorRole.Text,            text)
    p.setColor(QPalette.ColorRole.Button,          btn)
    p.setColor(QPalette.ColorRole.ButtonText,      text)
    p.setColor(QPalette.ColorRole.BrightText,      Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.Highlight,       accent)
    p.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.Link,            accent)
    p.setColor(QPalette.ColorRole.Mid,             mid)
    p.setColor(QPalette.ColorRole.Midlight,        QColor(70, 70, 70))
    p.setColor(QPalette.ColorRole.Dark,            QColor(20, 20, 20))
    p.setColor(QPalette.ColorRole.Shadow,          QColor(10, 10, 10))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
               QColor(100, 100, 100))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
               QColor(100, 100, 100))

    app.setPalette(p)
    app.setStyleSheet("""
        QTabBar::tab {
            background: #2d2d2d; color: #aaa;
            padding: 5px 14px;
            border: 1px solid #3c3c3c; border-bottom: none;
            border-radius: 3px 3px 0 0;
        }
        QTabBar::tab:selected  { background: #1e1e1e; color: #fff; border-color: #555; }
        QTabBar::tab:hover:!selected { background: #383838; color: #ddd; }
        QHeaderView::section {
            background: #2d2d2d; color: #ccc;
            padding: 4px 8px; border: 1px solid #3c3c3c; font-weight: 600;
        }
        QToolBar {
            background: #252526; border-bottom: 1px solid #3c3c3c;
            spacing: 4px; padding: 2px 4px;
        }
        QToolButton { padding: 4px 10px; border-radius: 3px; }
        QToolButton:hover   { background: #3c3c3c; }
        QToolButton:pressed { background: #4361ee; }
        QSplitter::handle   { background: #3c3c3c; }
        QStatusBar { background: #007acc; color: #fff; font-size: 12px; }
        QGroupBox {
            border: 1px solid #3c3c3c; border-radius: 4px;
            margin-top: 8px; font-weight: bold; color: #ccc;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QLineEdit, QSpinBox, QComboBox {
            background: #3c3c3c; border: 1px solid #555;
            border-radius: 3px; padding: 3px 6px; color: #ddd;
        }
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #4361ee; }
        QPushButton {
            background: #3c3c3c; border: 1px solid #555;
            border-radius: 3px; padding: 4px 14px; color: #ddd;
        }
        QPushButton:hover    { background: #4a4a4a; }
        QPushButton:pressed  { background: #4361ee; color: #fff; border-color: #4361ee; }
        QPushButton:disabled { color: #666; background: #2d2d2d; border-color: #3c3c3c; }
        QTableWidget         { gridline-color: #3c3c3c; }
        QPlainTextEdit       { background: #1e1e1e; color: #d4d4d4; border: none; }
        QDockWidget::title {
            background: #252526; color: #ccc;
            padding: 4px 8px; border-bottom: 1px solid #3c3c3c;
        }
        QTreeWidget {
            background: #1e1e1e; color: #d4d4d4; border: 1px solid #3c3c3c;
        }
        QTreeWidget::item:hover    { background: #2a2d2e; }
        QTreeWidget::item:selected { background: #094771; }
        QListWidget {
            background: #1e1e1e; color: #d4d4d4; border: 1px solid #3c3c3c;
        }
        QListWidget::item:hover    { background: #2a2d2e; }
        QListWidget::item:selected { background: #094771; }
    """)


def apply_light(app: QApplication) -> None:
    """Apply the standard Fusion light palette with minimal tweaks."""
    app.setPalette(app.style().standardPalette())
    app.setStyleSheet("""
        QStatusBar { background: #0078d4; color: #fff; font-size: 12px; }
        QToolBar {
            background: #f3f3f3; border-bottom: 1px solid #ddd;
            spacing: 4px; padding: 2px 4px;
        }
        QPlainTextEdit { background: #ffffff; color: #1e1e1e; border: 1px solid #ccc; }
        QHeaderView::section {
            background: #f3f3f3; color: #333;
            padding: 4px 8px; border: 1px solid #ddd; font-weight: 600;
        }
        QTabBar::tab {
            background: #ececec; color: #444;
            padding: 5px 14px; border: 1px solid #ccc;
            border-bottom: none; border-radius: 3px 3px 0 0;
        }
        QTabBar::tab:selected       { background: #ffffff; color: #000; border-color: #aaa; }
        QTabBar::tab:hover:!selected { background: #e0e0e0; }
        QSplitter::handle { background: #ddd; }
        QGroupBox {
            border: 1px solid #ccc; border-radius: 4px;
            margin-top: 8px; font-weight: bold;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QDockWidget::title {
            background: #f3f3f3; padding: 4px 8px; border-bottom: 1px solid #ddd;
        }
        QTreeWidget { border: 1px solid #ccc; }
        QListWidget { border: 1px solid #ccc; }
    """)


def current_theme(settings: QSettings) -> str:
    """Return ``'dark'`` or ``'light'`` from *settings* (defaults to dark)."""
    return str(settings.value(_SETTINGS_KEY, _DEFAULT_THEME))


def save_theme(settings: QSettings, name: str) -> None:
    """Persist *name* (``'dark'`` or ``'light'``) to *settings*."""
    settings.setValue(_SETTINGS_KEY, name)
