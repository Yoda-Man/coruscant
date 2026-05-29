"""
coruscant.ui.dialogs.cell_viewer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dialog for viewing and copying the contents of a single result cell.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QPlainTextEdit, QLabel, QCheckBox, QWidget
)
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtCore import Qt, QTimer, QSettings

_DIALOG_STYLE = """
    QDialog {
        background: #12121e;
    }
    QLabel {
        color: #cdd6f4;
    }
    QCheckBox {
        color: #cdd6f4;
        font-size: 12px;
    }
    QCheckBox::indicator {
        width: 14px;
        height: 14px;
        border: 1px solid #555570;
        border-radius: 3px;
        background: #1e1e2e;
    }
    QCheckBox::indicator:checked {
        background: #4361ee;
        border-color: #4361ee;
    }
    QPlainTextEdit {
        background: #1e1e2e;
        color: #cdd6f4;
        border: 1px solid #3c3c52;
        border-radius: 4px;
        padding: 8px;
        selection-background-color: #4361ee;
    }
    QPushButton {
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 #3c3c52, stop:1 #2e2e42);
        border: 1px solid #555570;
        border-radius: 5px;
        padding: 7px 20px;
        color: #ddd;
        font-size: 12px;
        font-weight: 600;
        min-width: 80px;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 #4a4a62, stop:1 #3c3c52);
        border-color: #7070a0;
        color: #fff;
    }
    QPushButton:pressed {
        background: #4361ee;
        border-color: #4361ee;
        color: #fff;
    }
"""

class CellViewerDialog(QDialog):
    """
    A resizable dialog to view massive amounts of text from a single cell.
    Includes options to toggle word wrap and a button to copy to clipboard.
    """
    
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cell Content Viewer")
        self.resize(640, 480)
        self.setStyleSheet(_DIALOG_STYLE)
        self.setModal(True)
        self._text = text
        
        self._build_ui()
        
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        
        # ── Top bar with info / controls ───────────────────────────────── #
        top_layout = QHBoxLayout()
        
        info_label = QLabel(f"Length: {len(self._text):,} characters")
        info_label.setStyleSheet("color: #8888aa; font-size: 12px; font-weight: bold;")
        top_layout.addWidget(info_label)
        
        top_layout.addStretch()
        
        self.wrap_checkbox = QCheckBox("Word Wrap")
        self.wrap_checkbox.setChecked(True)
        self.wrap_checkbox.toggled.connect(self._toggle_wrap)
        top_layout.addWidget(self.wrap_checkbox)
        
        layout.addLayout(top_layout)
        
        # ── Text Editor ────────────────────────────────────────────────── #
        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setPlainText(self._text)
        
        font = QFont("Courier New", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        
        layout.addWidget(self.editor)
        
        # ── Bottom Buttons ─────────────────────────────────────────────── #
        btn_layout = QHBoxLayout()
        
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_layout.addWidget(self.copy_btn)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)

    def _toggle_wrap(self, checked: bool) -> None:
        if checked:
            self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        else:
            self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def _copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self._text)
        
        # Briefly change text to indicate success
        self.copy_btn.setText("Copied!")
        self.copy_btn.setEnabled(False)
        self.copy_btn.setStyleSheet(
            "background: #2E7D32; border-color: #4CAF50; color: #fff;"
        )
        
        QTimer.singleShot(1500, self._restore_copy_btn)
        
    def _restore_copy_btn(self) -> None:
        self.copy_btn.setText("Copy to Clipboard")
        self.copy_btn.setEnabled(True)
        self.copy_btn.setStyleSheet("")  # Restore to original stylesheet class

        settings = QSettings("Coruscant", "Coruscant")
        if settings.value("settings/autoclose_cell_viewer", True, type=bool):
            self.accept()
