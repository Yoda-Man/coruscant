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
            background: #2a2a2a; color: #999;
            padding: 6px 16px;
            border: 1px solid #383838; border-bottom: none;
            border-radius: 4px 4px 0 0;
            font-size: 12px;
        }
        QTabBar::tab:selected  {
            background: #1e1e1e; color: #fff;
            border-color: #4361ee; border-bottom: 1px solid #1e1e1e;
        }
        QTabBar::tab:hover:!selected { background: #333; color: #ddd; }
        QHeaderView::section {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #333, stop:1 #282828);
            color: #ccc;
            padding: 5px 8px; border: 1px solid #3a3a3a; font-weight: 600;
            font-size: 12px;
        }
        QToolBar {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #2a2a2a, stop:1 #1c1c1c);
            border-bottom: 2px solid #4361ee;
            spacing: 3px; padding: 4px 6px;
        }
        QToolBar::separator {
            background: #3c3c3c; width: 1px; margin: 5px 2px;
        }
        QToolButton {
            padding: 5px 10px; border-radius: 4px;
            font-size: 12px; color: #d4d4d4;
        }
        QToolButton:hover   { background: #3a3a3a; }
        QToolButton:pressed { background: #4361ee; color: #fff; }
        QSplitter::handle   { background: #333; }
        QSplitter::handle:hover { background: #4361ee; }
        QStatusBar {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #0088d4, stop:1 #006aaa);
            color: #fff; font-size: 12px; font-weight: 500;
            padding: 0 6px;
        }
        QGroupBox {
            border: 1px solid #383838; border-radius: 6px;
            margin-top: 10px; padding-top: 4px;
            font-weight: bold; font-size: 11px; color: #89b4fa;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 12px;
            padding: 0 6px; color: #89b4fa;
        }
        QLineEdit, QSpinBox, QComboBox {
            background: #2d2d2d; border: 1px solid #484848;
            border-radius: 4px; padding: 4px 8px; color: #e0e0e0;
            selection-background-color: #4361ee;
            font-size: 12px;
        }
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
            border: 1px solid #4361ee; background: #2f2f3a;
        }
        QLineEdit:hover, QSpinBox:hover, QComboBox:hover {
            border-color: #5a5a5a;
        }
        QSpinBox::up-button, QSpinBox::down-button {
            background: #3a3a3a; border: 1px solid #484848; width: 16px;
        }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background: #4a4a4a;
        }
        QSpinBox::up-arrow {
            border-left: 4px solid transparent; border-right: 4px solid transparent;
            border-bottom: 5px solid #ccc; width: 0; height: 0;
        }
        QSpinBox::down-arrow {
            border-left: 4px solid transparent; border-right: 4px solid transparent;
            border-top: 5px solid #ccc; width: 0; height: 0;
        }
        QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {
            border-bottom-color: #555; border-top-color: #555;
        }
        QComboBox::drop-down { border: none; background: #3a3a3a; width: 22px; }
        QComboBox::down-arrow {
            border-left: 4px solid transparent; border-right: 4px solid transparent;
            border-top: 5px solid #ccc; width: 0; height: 0;
        }
        QPushButton {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #3c3c3c, stop:1 #2e2e2e);
            border: 1px solid #525252;
            border-radius: 4px; padding: 5px 16px;
            color: #ddd; font-size: 12px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #4a4a4a, stop:1 #3c3c3c);
            border-color: #686868;
        }
        QPushButton:pressed  {
            background: #4361ee; color: #fff; border-color: #4361ee;
        }
        QPushButton:disabled { color: #555; background: #252525; border-color: #333; }
        QTableWidget         { gridline-color: #383838; }
        QPlainTextEdit       { background: #1e1e1e; color: #d4d4d4; border: none; }
        QDockWidget::title {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #2a2a2a, stop:1 #1e1e1e);
            color: #bbb; padding: 5px 8px;
            border-bottom: 1px solid #383838; font-weight: 600; font-size: 11px;
        }
        QTreeWidget {
            background: #1e1e1e; color: #d4d4d4;
            border: 1px solid #333; outline: 0;
        }
        QTreeWidget::item { padding: 2px 0; }
        QTreeWidget::item:hover    { background: #2a2d2e; }
        QTreeWidget::item:selected { background: #094771; color: #fff; }
        QListWidget {
            background: #1e1e1e; color: #d4d4d4;
            border: 1px solid #333; outline: 0;
        }
        QListWidget::item { padding: 3px 4px; }
        QListWidget::item:hover    { background: #2a2d2e; }
        QListWidget::item:selected { background: #094771; color: #fff; }
        QScrollBar:vertical {
            background: #1a1a1a; width: 10px; margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #444; border-radius: 5px; min-height: 24px;
        }
        QScrollBar::handle:vertical:hover { background: #555; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal {
            background: #1a1a1a; height: 10px; margin: 0;
        }
        QScrollBar::handle:horizontal {
            background: #444; border-radius: 5px; min-width: 24px;
        }
        QScrollBar::handle:horizontal:hover { background: #555; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        QToolTip {
            background: #252535; color: #e0e0e0;
            border: 1px solid #4361ee; border-radius: 4px;
            padding: 4px 8px; font-size: 11px;
        }
        QMessageBox QPushButton { min-width: 80px; }
    """)


def apply_light(app: QApplication) -> None:
    """Apply the standard Fusion light palette with minimal tweaks."""
    app.setPalette(app.style().standardPalette())
    app.setStyleSheet("""
        QStatusBar {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #0088d4, stop:1 #006aaa);
            color: #fff; font-size: 12px; font-weight: 500; padding: 0 6px;
        }
        QToolBar {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #f5f5f5, stop:1 #e8e8e8);
            border-bottom: 2px solid #0078d4;
            spacing: 3px; padding: 4px 6px;
        }
        QToolBar::separator {
            background: #ccc; width: 1px; margin: 5px 2px;
        }
        QToolButton {
            padding: 5px 10px; border-radius: 4px;
            font-size: 12px; color: #1e1e1e;
        }
        QToolButton:hover   { background: #dde8f5; }
        QToolButton:pressed { background: #0078d4; color: #fff; }
        QPlainTextEdit { background: #ffffff; color: #1e1e1e; border: 1px solid #ccc; }
        QHeaderView::section {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #f5f5f5, stop:1 #eaeaea);
            color: #333;
            padding: 5px 8px; border: 1px solid #ddd; font-weight: 600; font-size: 12px;
        }
        QTabBar::tab {
            background: #eeeeee; color: #555;
            padding: 6px 16px; border: 1px solid #ccc;
            border-bottom: none; border-radius: 4px 4px 0 0; font-size: 12px;
        }
        QTabBar::tab:selected {
            background: #ffffff; color: #000;
            border-color: #0078d4; border-bottom: 1px solid #fff;
        }
        QTabBar::tab:hover:!selected { background: #e0e8f5; }
        QSplitter::handle { background: #d0d0d0; }
        QSplitter::handle:hover { background: #0078d4; }
        QGroupBox {
            border: 1px solid #ccc; border-radius: 6px;
            margin-top: 10px; padding-top: 4px;
            font-weight: bold; font-size: 11px; color: #0060a8;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 12px;
            padding: 0 6px; color: #0060a8;
        }
        QPushButton {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #f5f5f5, stop:1 #e8e8e8);
            border: 1px solid #bbb; border-radius: 4px;
            padding: 5px 16px; color: #222; font-size: 12px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #dde8f5, stop:1 #c8d8ee);
            border-color: #0078d4;
        }
        QPushButton:pressed { background: #0078d4; color: #fff; border-color: #0078d4; }
        QPushButton:disabled { color: #aaa; background: #f0f0f0; border-color: #ddd; }
        QDockWidget::title {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #f5f5f5, stop:1 #e8e8e8);
            padding: 5px 8px; border-bottom: 1px solid #ddd;
            font-weight: 600; font-size: 11px;
        }
        QTreeWidget { border: 1px solid #ccc; outline: 0; }
        QTreeWidget::item:hover    { background: #dde8f5; }
        QTreeWidget::item:selected { background: #0078d4; color: #fff; }
        QListWidget { border: 1px solid #ccc; outline: 0; }
        QListWidget::item:hover    { background: #dde8f5; }
        QListWidget::item:selected { background: #0078d4; color: #fff; }
        QToolTip {
            background: #fff8e1; color: #222;
            border: 1px solid #0078d4; border-radius: 4px;
            padding: 4px 8px; font-size: 11px;
        }
        QMessageBox QPushButton { min-width: 80px; }
    """)


def current_theme(settings: QSettings) -> str:
    """Return ``'dark'`` or ``'light'`` from *settings* (defaults to dark)."""
    return str(settings.value(_SETTINGS_KEY, _DEFAULT_THEME))


def save_theme(settings: QSettings, name: str) -> None:
    """Persist *name* (``'dark'`` or ``'light'``) to *settings*."""
    settings.setValue(_SETTINGS_KEY, name)
