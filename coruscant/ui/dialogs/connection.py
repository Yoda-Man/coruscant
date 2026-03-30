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

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox, QPushButton,
    QDialogButtonBox, QVBoxLayout, QHBoxLayout,
    QComboBox, QGroupBox, QMessageBox,
)
from PySide6.QtCore import QSettings

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
        self.setMinimumWidth(460)
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._build_ui()
        self._load_recent()

    # ── UI ────────────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # Recent connections
        recent_box = QGroupBox("Recent connections")
        rl = QHBoxLayout(recent_box)
        rl.setContentsMargins(8, 8, 8, 8)
        self._recent_combo = QComboBox()
        self._recent_combo.setPlaceholderText("Select a saved connection…")
        self._recent_combo.currentIndexChanged.connect(self._on_recent_selected)
        rl.addWidget(self._recent_combo)
        root.addWidget(recent_box)

        # Fields
        fields_box = QGroupBox("Connection parameters")
        form = QFormLayout(fields_box)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

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

        form.addRow("Host:",     self._host)
        form.addRow("Port:",     self._port)
        form.addRow("Database:", self._database)
        form.addRow("Username:", self._user)
        form.addRow("Password:", self._password)
        form.addRow("SSL mode:", self._ssl_mode)
        root.addWidget(fields_box)

        # Buttons
        btn_row = QHBoxLayout()
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._on_test)
        btn_row.addWidget(test_btn)
        btn_row.addStretch()

        std = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        std.accepted.connect(self._on_ok)
        std.rejected.connect(self.reject)
        btn_row.addWidget(std)
        root.addLayout(btn_row)

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
            QMessageBox.information(self, "Test Connection", "Connection successful!")
        except Exception as exc:
            QMessageBox.critical(self, "Test Connection", f"Connection failed:\n\n{exc}")

    def _on_ok(self) -> None:
        for field, name in [(self._host, "Host"), (self._database, "Database"),
                            (self._user, "Username")]:
            if not field.text().strip():
                QMessageBox.warning(self, "Missing field", f"{name} is required.")
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
