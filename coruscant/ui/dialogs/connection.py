"""
coruscant.ui.dialogs.connection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Connection dialog — host, port, database, user, password, SSL mode.

Recent connections (up to 5) are persisted in QSettings.
Passwords are base64-encoded before storage to avoid plaintext in the registry.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox, QPushButton,
    QDialogButtonBox, QVBoxLayout, QHBoxLayout,
    QComboBox, QGroupBox, QLabel,
)
from coruscant.ui.dialogs.message import StyledMessageBox
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QPixmap, QFont

_BANNER_PATH = str(Path(__file__).resolve().parents[3] / "docs" / "coruscant3.png")

_SETTINGS_ORG = "Coruscant"
_SETTINGS_APP = "Coruscant"
_RECENT_KEY   = "connections/recent"
_MAX_RECENT   = 5
_SEP          = "\x00"   # field separator — must not appear in any value

SSL_MODES = ["prefer", "disable", "allow", "require", "verify-ca", "verify-full"]

SSL_TOOLTIP = (
    "disable     – never use SSL\n"
    "allow       – use SSL only if the server requires it\n"
    "prefer      – use SSL if available  (default)\n"
    "require     – always use SSL\n"
    "verify-ca   – SSL + verify server certificate\n"
    "verify-full – SSL + verify certificate + hostname"
)


# ── Serialisation helpers ────────────────────────────────────────────── #

def _encode(password: str) -> str:
    return base64.b64encode(password.encode()).decode("ascii")

def _decode(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode("ascii")).decode()
    except Exception:
        return encoded   # legacy plaintext fallback

def _pack(host: str, port: int, db: str, user: str,
          password: str, ssl_mode: str) -> str:
    return _SEP.join([host, str(port), db, user, _encode(password), ssl_mode])

def _unpack(s: str) -> dict | None:
    parts = s.split(_SEP)
    if len(parts) == 5:                          # legacy format (no ssl_mode)
        host, port_s, db, user, raw_pw = parts
        ssl_mode = "prefer"
        password = raw_pw
    elif len(parts) == 6:
        host, port_s, db, user, enc_pw, ssl_mode = parts
        password = _decode(enc_pw)
    else:
        return None
    try:
        port = int(port_s)
    except ValueError:
        return None
    return dict(host=host, port=port, database=db,
                user=user, password=password, ssl_mode=ssl_mode)


# ── Dialog ───────────────────────────────────────────────────────────── #

class ConnectionDialog(QDialog):
    """
    Modal dialog for entering PostgreSQL connection parameters.

    Call ``get_params()`` after ``exec()`` returns Accepted.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to PostgreSQL")
        self.setMinimumWidth(500)
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self.setStyleSheet("""
            QGroupBox {
                border: 1px solid #313244;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 4px;
                font-weight: bold;
                font-size: 11px;
                color: #89b4fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLineEdit, QSpinBox, QComboBox {
                background: #2a2a3a;
                border: 1px solid #44446a;
                border-radius: 4px;
                padding: 5px 8px;
                color: #e0e0e0;
                font-size: 12px;
                min-height: 24px;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #4361ee;
                background: #2e2e45;
            }
            QLabel {
                color: #cdd6f4;
                font-size: 12px;
            }
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #3c3c52, stop:1 #2e2e42);
                border: 1px solid #555570;
                border-radius: 4px;
                padding: 6px 18px;
                color: #ddd;
                font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #4a4a62, stop:1 #3c3c52);
                border-color: #7070a0;
            }
            QPushButton:pressed {
                background: #4361ee;
                color: #fff;
                border-color: #4361ee;
            }
        """)
        self._build_ui()
        self._load_recent()

    # ── UI ────────────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 0, 12, 12)

        # ── Banner image ──────────────────────────────────────────────── #
        banner = QLabel()
        banner.setFixedHeight(130)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(_BANNER_PATH)
        if not pixmap.isNull():
            banner.setPixmap(
                pixmap.scaledToHeight(130, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            banner.setText("✦  Coruscant  ✦")
            f = QFont(); f.setPointSize(18); f.setBold(True)
            banner.setFont(f)
        banner.setStyleSheet(
            "background: #0d0d1a; border-radius: 0; margin: 0; padding: 0;"
        )
        root.setContentsMargins(0, 0, 0, 12)
        root.addWidget(banner)

        # ── Padded inner content ──────────────────────────────────────── #
        inner = QVBoxLayout()
        inner.setContentsMargins(12, 0, 12, 0)
        inner.setSpacing(10)

        # Recent connections
        recent_box = QGroupBox("Recent connections")
        rl = QHBoxLayout(recent_box)
        rl.setContentsMargins(10, 10, 10, 10)
        self._recent_combo = QComboBox()
        self._recent_combo.setPlaceholderText("Select a saved connection…")
        self._recent_combo.currentIndexChanged.connect(self._on_recent_selected)
        rl.addWidget(self._recent_combo)
        inner.addWidget(recent_box)

        # Fields
        fields_box = QGroupBox("Connection parameters")
        form = QFormLayout(fields_box)
        form.setContentsMargins(14, 14, 14, 14)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)

        self._host     = QLineEdit("localhost")
        self._port     = QSpinBox(); self._port.setRange(1, 65535); self._port.setValue(5432)
        self._database = QLineEdit()
        self._user     = QLineEdit()
        self._password = QLineEdit(); self._password.setEchoMode(QLineEdit.EchoMode.Password)

        self._ssl_mode = QComboBox()
        for mode in SSL_MODES:
            self._ssl_mode.addItem(mode)
        self._ssl_mode.setCurrentText("prefer")
        self._ssl_mode.setToolTip(SSL_TOOLTIP)

        self._database.setPlaceholderText("database name")
        self._user.setPlaceholderText("username")
        self._password.setPlaceholderText("••••••••")

        form.addRow("Host:",     self._host)
        form.addRow("Port:",     self._port)
        form.addRow("Database:", self._database)
        form.addRow("Username:", self._user)
        form.addRow("Password:", self._password)
        form.addRow("SSL mode:", self._ssl_mode)
        inner.addWidget(fields_box)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        test_btn = QPushButton("⚡  Test Connection")
        test_btn.setToolTip("Verify the connection parameters without saving")
        test_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #006270, stop:1 #004d57);
                border: 1px solid #008899;
                border-radius: 4px; padding: 6px 18px;
                color: #80deea; font-weight: 600; font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #007a8a, stop:1 #006270);
                color: #e0f7fa; border-color: #00acc1;
            }
            QPushButton:pressed { background: #004d57; }
        """)
        test_btn.clicked.connect(self._on_test)
        btn_row.addWidget(test_btn)
        btn_row.addStretch()

        std = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        std.accepted.connect(self._on_ok)
        std.rejected.connect(self.reject)

        ok_btn = std.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Connect")
        ok_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1976D2, stop:1 #1565C0);
                border: 1px solid #1E88E5;
                border-radius: 4px; padding: 6px 22px;
                color: #fff; font-weight: 600; font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1E88E5, stop:1 #1976D2);
            }
            QPushButton:pressed { background: #1565C0; }
            QPushButton:disabled { background: #1a2a3a; color: #4a6a8a; border-color: #2a3a4a; }
        """)

        btn_row.addWidget(std)
        inner.addLayout(btn_row)

        root.addLayout(inner)

    # ── Recent connections ────────────────────────────────────────────── #

    def _load_recent(self) -> None:
        raw = self._settings.value(_RECENT_KEY, [])
        if isinstance(raw, str):
            raw = [raw]
        self._recent_combo.blockSignals(True)
        self._recent_combo.clear()
        for entry in raw:
            params = _unpack(entry)
            if params:
                label = (
                    f"{params['user']}@{params['host']}:{params['port']}"
                    f"/{params['database']}  [{params['ssl_mode']}]"
                )
                self._recent_combo.addItem(label, entry)
        self._recent_combo.blockSignals(False)

    def _save_recent(self) -> None:
        entry = _pack(
            self._host.text().strip(), self._port.value(),
            self._database.text().strip(), self._user.text().strip(),
            self._password.text(), self._ssl_mode.currentText(),
        )
        raw = self._settings.value(_RECENT_KEY, [])
        if isinstance(raw, str):
            raw = [raw]
        raw = [r for r in raw if r != entry]
        raw.insert(0, entry)
        self._settings.setValue(_RECENT_KEY, raw[:_MAX_RECENT])

    def _on_recent_selected(self, index: int) -> None:
        entry = self._recent_combo.itemData(index)
        if not entry:
            return
        params = _unpack(entry)
        if not params:
            return
        self._host.setText(params["host"])
        self._port.setValue(params["port"])
        self._database.setText(params["database"])
        self._user.setText(params["user"])
        self._password.setText(params["password"])
        self._ssl_mode.setCurrentText(params.get("ssl_mode", "prefer"))

    # ── Handlers ─────────────────────────────────────────────────────── #

    def _on_test(self) -> None:
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=self._host.text().strip(), port=self._port.value(),
                dbname=self._database.text().strip(), user=self._user.text().strip(),
                password=self._password.text(), connect_timeout=5,
                sslmode=self._ssl_mode.currentText(),
            )
            conn.close()
            StyledMessageBox.information(self, "Test Connection", "Connection successful!")
        except Exception as exc:
            StyledMessageBox.critical(self, "Test Connection", f"Connection failed:\n\n{exc}")

    def _on_ok(self) -> None:
        for field, name in [(self._host, "Host"), (self._database, "Database"),
                            (self._user, "Username")]:
            if not field.text().strip():
                StyledMessageBox.warning(self, "Missing field", f"{name} is required.")
                return
        self._save_recent()
        self.accept()

    # ── Public API ────────────────────────────────────────────────────── #

    def get_params(self) -> dict:
        return {
            "host":     self._host.text().strip(),
            "port":     self._port.value(),
            "database": self._database.text().strip(),
            "user":     self._user.text().strip(),
            "password": self._password.text(),
            "ssl_mode": self._ssl_mode.currentText(),
        }
