"""
coruscant.ui.dialogs.connection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Connection manager dialog with saved profiles and pgAdmin import support.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QBrush, QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from coruscant.core.connections import (
    SSL_MODES,
    SavedConnection,
    deserialise_connections,
    merge_connections,
    parse_pgadmin_export_text,
    serialise_connections,
)
from coruscant.ui.dialogs.message import StyledMessageBox


_BASE = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
_BANNER_PATH = str(_BASE / "docs" / "coruscant3.png")

_SETTINGS_ORG = "Coruscant"
_SETTINGS_APP = "Coruscant"
_CONNECTIONS_KEY = "connections/saved"
_LEGACY_RECENT_KEY = "connections/recent"
_LEGACY_SEP = "\x00"

SSL_TOOLTIP = (
    "disable     - never use SSL\n"
    "allow       - use SSL only if the server requires it\n"
    "prefer      - use SSL if available (default)\n"
    "require     - always use SSL\n"
    "verify-ca   - SSL + verify server certificate\n"
    "verify-full - SSL + verify certificate + hostname"
)


def _decode_legacy_password(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode("ascii")).decode()
    except Exception:
        return encoded


def _unpack_legacy_recent(entry: str) -> SavedConnection | None:
    parts = entry.split(_LEGACY_SEP)
    if len(parts) == 5:
        host, port_s, db, user, password = parts
        ssl_mode = "prefer"
    elif len(parts) == 6:
        host, port_s, db, user, encoded_password, ssl_mode = parts
        password = _decode_legacy_password(encoded_password)
    else:
        return None
    try:
        port = int(port_s)
    except ValueError:
        return None
    if not host:
        return None
    return SavedConnection(
        name=f"{user}@{host}:{port}/{db}",
        group="Recent",
        host=host,
        port=port,
        database=db,
        user=user,
        password=password,
        ssl_mode=ssl_mode,
        source="recent",
    )


class ConnectionDialog(QDialog):
    """
    Modal connection manager.

    Call ``get_params()`` after ``exec()`` returns Accepted.  ``get_profile()``
    returns the selected saved profile, including its display name.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connection Manager")
        self.resize(980, 640)
        self.setMinimumSize(860, 560)

        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._connections: list[SavedConnection] = []
        self._accepted_profile: SavedConnection | None = None

        self.setStyleSheet("""
            QDialog {
                background: #12121e;
            }
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
            QComboBox::drop-down {
                border: none;
                width: 22px;
            }
            QComboBox::down-arrow {
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #aaa;
                width: 0;
                height: 0;
            }
            QComboBox QAbstractItemView {
                background: #2a2a3a;
                border: 1px solid #4361ee;
                border-radius: 4px;
                color: #e0e0e0;
                selection-background-color: #4361ee;
                selection-color: #ffffff;
                outline: none;
                padding: 2px;
            }
            QComboBox QAbstractItemView::item {
                padding: 5px 10px;
                min-height: 22px;
            }
            QComboBox QAbstractItemView::item:hover {
                background: #3a3a55;
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
                padding: 6px 14px;
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
            QTableWidget {
                background: #1e1e28;
                alternate-background-color: #242434;
                border: 1px solid #343450;
                gridline-color: #303044;
                color: #d8d8e8;
                selection-background-color: #094771;
                selection-color: #fff;
            }
            QTableWidget::item {
                padding: 5px 6px;
            }
            QHeaderView::section {
                background: #2b2b40;
                color: #d8d8e8;
                border: 1px solid #3b3b56;
                padding: 5px 6px;
                font-size: 11px;
                font-weight: 700;
            }
        """)

        self._build_ui()
        self._load_connections()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 12)
        root.setSpacing(10)

        banner = QLabel()
        banner.setFixedHeight(105)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(_BANNER_PATH)
        if not pixmap.isNull():
            banner.setPixmap(
                pixmap.scaledToHeight(105, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            banner.setText("Coruscant")
            font = QFont()
            font.setPointSize(18)
            font.setBold(True)
            banner.setFont(font)
        banner.setStyleSheet("background: #0d0d1a;")
        root.addWidget(banner)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_library_panel())
        body.addWidget(self._build_details_panel())
        body.setSizes([560, 360])
        root.addWidget(body, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(12, 0, 12, 0)
        self._summary = QLabel("No saved connections.")
        self._summary.setStyleSheet("color: #aeb6d8;")
        footer.addWidget(self._summary, 1)

        self._std_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._std_buttons.accepted.connect(self._on_connect)
        self._std_buttons.rejected.connect(self.reject)

        connect_btn = self._std_buttons.button(QDialogButtonBox.StandardButton.Ok)
        connect_btn.setText("Connect")
        connect_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1976D2, stop:1 #1565C0);
                border: 1px solid #1E88E5;
                border-radius: 4px;
                padding: 6px 22px;
                color: #fff;
                font-weight: 700;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1E88E5, stop:1 #1976D2);
            }
            QPushButton:disabled {
                background: #1a2a3a;
                color: #4a6a8a;
                border-color: #2a3a4a;
            }
        """)
        footer.addWidget(self._std_buttons)
        root.addLayout(footer)

    def _build_library_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)

        filters = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name, host, database, or user")
        self._search.textChanged.connect(self._refresh_table)
        filters.addWidget(self._search, 1)

        self._group_filter = QComboBox()
        self._group_filter.currentTextChanged.connect(self._refresh_table)
        filters.addWidget(self._group_filter)
        layout.addLayout(filters)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["Name", "Group", "Host", "Database", "User", "SSL"])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self._table.itemDoubleClicked.connect(lambda _item: self._on_connect())
        layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        self._import_btn = QPushButton("Import pgAdmin JSON")
        self._import_btn.clicked.connect(self._on_import_pgadmin)
        actions.addWidget(self._import_btn)

        self._new_btn = QPushButton("New")
        self._new_btn.clicked.connect(self._on_new)
        actions.addWidget(self._new_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._on_delete)
        actions.addWidget(self._delete_btn)

        actions.addStretch()
        layout.addLayout(actions)
        return panel

    def _build_details_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 12, 0)
        layout.setSpacing(8)

        box = QGroupBox("Connection details")
        form = QFormLayout(box)
        form.setContentsMargins(14, 14, 14, 14)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)

        self._name = QLineEdit()
        self._group = QLineEdit()
        self._host = QLineEdit("localhost")
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(5432)
        self._database = QLineEdit("postgres")
        self._user = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        # Prevent IME/autocorrect/autocapitalise from silently altering the
        # password — critical for passwords that contain special characters
        # such as $, @, !, #, etc.
        self._password.setInputMethodHints(
            Qt.InputMethodHint.ImhHiddenText
            | Qt.InputMethodHint.ImhNoPredictiveText
            | Qt.InputMethodHint.ImhNoAutoUppercase
            | Qt.InputMethodHint.ImhSensitiveData
        )

        # Show/hide toggle so users can verify they typed the right password
        self._show_pw_btn = QToolButton()
        self._show_pw_btn.setText("👁")
        self._show_pw_btn.setToolTip("Show / hide password")
        self._show_pw_btn.setCheckable(True)
        self._show_pw_btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                padding: 0 4px;
                font-size: 14px;
                color: #888;
            }
            QToolButton:hover  { color: #cdd6f4; }
            QToolButton:checked { color: #89b4fa; }
        """)
        self._show_pw_btn.toggled.connect(self._toggle_password_visibility)

        pw_row = QWidget()
        pw_layout = QHBoxLayout(pw_row)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.setSpacing(4)
        pw_layout.addWidget(self._password, 1)
        pw_layout.addWidget(self._show_pw_btn)

        self._ssl_mode = QComboBox()
        self._ssl_mode.addItems(SSL_MODES)
        self._ssl_mode.setCurrentText("prefer")
        self._ssl_mode.setToolTip(SSL_TOOLTIP)

        self._name.setPlaceholderText("Human friendly name")
        self._group.setPlaceholderText("Optional group")
        self._host.setPlaceholderText("Hostname or IP address")
        self._database.setPlaceholderText("Database name")
        self._user.setPlaceholderText("PostgreSQL username")
        self._password.setPlaceholderText("Password (pgAdmin exports leave this blank)")

        form.addRow("Name:", self._name)
        form.addRow("Group:", self._group)
        form.addRow("Host:", self._host)
        form.addRow("Port:", self._port)
        form.addRow("Database:", self._database)
        form.addRow("Username:", self._user)
        form.addRow("Password:", pw_row)
        form.addRow("SSL mode:", self._ssl_mode)
        layout.addWidget(box)

        btns = QHBoxLayout()
        self._test_btn = QPushButton("Test Connection")
        self._test_btn.clicked.connect(self._on_test)
        btns.addWidget(self._test_btn)

        self._save_btn = QPushButton("Save Profile")
        self._save_btn.clicked.connect(self._on_save_profile)
        btns.addWidget(self._save_btn)
        btns.addStretch()
        layout.addLayout(btns)

        note = QLabel(
            "Imported pgAdmin profiles include names, groups, hosts, databases, users, and SSL mode. "
            "Enter the password before testing or connecting."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #aeb6d8; padding-top: 4px;")
        layout.addWidget(note)
        layout.addStretch()
        return panel

    def _load_connections(self) -> None:
        self._connections = deserialise_connections(self._settings.value(_CONNECTIONS_KEY, []))
        if not self._connections:
            self._connections = self._load_legacy_recent()
            if self._connections:
                self._persist_connections()
        self._refresh_group_filter()
        self._refresh_table()
        self._select_first_row()

    def _load_legacy_recent(self) -> list[SavedConnection]:
        raw = self._settings.value(_LEGACY_RECENT_KEY, [])
        if isinstance(raw, str):
            raw = [raw]
        connections = []
        for entry in raw or []:
            conn = _unpack_legacy_recent(str(entry))
            if conn:
                connections.append(conn)
        return connections

    def _persist_connections(self) -> None:
        self._settings.setValue(_CONNECTIONS_KEY, serialise_connections(self._connections))

    def _refresh_group_filter(self) -> None:
        current = self._group_filter.currentText() if self._group_filter.count() else "All groups"
        groups = sorted({conn.group for conn in self._connections if conn.group.strip()}, key=str.lower)
        self._group_filter.blockSignals(True)
        self._group_filter.clear()
        self._group_filter.addItem("All groups")
        self._group_filter.addItems(groups)
        idx = self._group_filter.findText(current)
        self._group_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self._group_filter.blockSignals(False)

    def _refresh_table(self) -> None:
        selected_key = self._selected_connection().key if self._selected_connection() else ""
        query = self._search.text().strip().lower()
        group = self._group_filter.currentText()

        visible: list[tuple[int, SavedConnection]] = []
        for index, conn in enumerate(self._connections):
            haystack = " ".join(
                [conn.display_name, conn.group, conn.host, conn.database, conn.user, conn.ssl_mode]
            ).lower()
            if query and query not in haystack:
                continue
            if group and group != "All groups" and conn.group != group:
                continue
            visible.append((index, conn))

        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for row, (index, conn) in enumerate(visible):
            self._table.insertRow(row)
            values = [conn.display_name, conn.group, conn.host, conn.database, conn.user, conn.ssl_mode]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, index)
                if col == 0:
                    item.setToolTip(f"{conn.host}:{conn.port}/{conn.database}")
                if conn.bg_color:
                    color = QColor(conn.bg_color)
                    if color.isValid():
                        item.setBackground(QBrush(color))
                        if conn.fg_color and QColor(conn.fg_color).isValid():
                            item.setForeground(QBrush(QColor(conn.fg_color)))
                self._table.setItem(row, col, item)
            if conn.source == "pgadmin":
                self._table.item(row, 0).setToolTip("Imported from pgAdmin")
        self._table.blockSignals(False)

        for row in range(self._table.rowCount()):
            index = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if self._connections[index].key == selected_key:
                self._table.selectRow(row)
                break

        self._summary.setText(
            f"{len(visible)} shown / {len(self._connections)} saved connections"
            if self._connections else
            "No saved connections. Import a pgAdmin JSON export or create one manually."
        )
        self._delete_btn.setEnabled(self._table.currentRow() >= 0)

    def _select_first_row(self) -> None:
        if self._table.rowCount():
            self._table.selectRow(0)
        else:
            self._clear_form()

    def _selected_index(self) -> int | None:
        model = self._table.selectionModel()
        if model is None or not model.hasSelection():
            return None
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if not item:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        return int(index) if index is not None else None

    def _selected_connection(self) -> SavedConnection | None:
        index = self._selected_index()
        if index is None or index >= len(self._connections):
            return None
        return self._connections[index]

    def _on_table_selection_changed(self) -> None:
        conn = self._selected_connection()
        self._delete_btn.setEnabled(conn is not None)
        if conn:
            self._populate_form(conn)

    def _populate_form(self, conn: SavedConnection) -> None:
        self._name.setText(conn.display_name)
        self._group.setText(conn.group)
        self._host.setText(conn.host)
        self._port.setValue(conn.port)
        self._database.setText(conn.database)
        self._user.setText(conn.user)
        self._password.setText(conn.password)
        self._ssl_mode.setCurrentText(conn.ssl_mode)

    def _clear_form(self) -> None:
        self._name.clear()
        self._group.clear()
        self._host.setText("localhost")
        self._port.setValue(5432)
        self._database.setText("postgres")
        self._user.clear()
        self._password.clear()
        self._ssl_mode.setCurrentText("prefer")

    def _profile_from_form(self) -> SavedConnection | None:
        for field, name in [(self._host, "Host"), (self._database, "Database"), (self._user, "Username")]:
            if not field.text().strip():
                StyledMessageBox.warning(self, "Missing field", f"{name} is required.")
                return None

        name = self._name.text().strip()
        conn = SavedConnection(
            name=name or f"{self._user.text().strip()}@{self._host.text().strip()}",
            group=self._group.text().strip(),
            host=self._host.text().strip(),
            port=self._port.value(),
            database=self._database.text().strip(),
            user=self._user.text().strip(),
            password=self._password.text(),
            ssl_mode=self._ssl_mode.currentText(),
            source="manual",
        )
        selected = self._selected_connection()
        if selected:
            conn.bg_color = selected.bg_color
            conn.fg_color = selected.fg_color
            conn.source = selected.source if selected.source == "pgadmin" else "manual"
        return conn

    def _toggle_password_visibility(self, checked: bool) -> None:
        """Switch the password field between hidden and plain-text display."""
        if checked:
            self._password.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self._password.setEchoMode(QLineEdit.EchoMode.Password)

    def _on_import_pgadmin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import pgAdmin Server JSON",
            "",
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return

        try:
            with open(path, encoding="utf-8") as fh:
                imported = parse_pgadmin_export_text(fh.read())
        except (OSError, ValueError) as exc:
            StyledMessageBox.critical(self, "Import pgAdmin JSON", str(exc))
            return

        self._connections, added, updated = merge_connections(self._connections, imported)
        self._persist_connections()
        self._refresh_group_filter()
        self._refresh_table()
        self._select_first_row()
        StyledMessageBox.information(
            self,
            "Import Complete",
            f"Imported {len(imported)} pgAdmin connection(s).\n\nAdded: {added}\nUpdated: {updated}",
        )

    def _on_new(self) -> None:
        self._table.clearSelection()
        self._clear_form()
        self._name.setFocus()

    def _on_delete(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        conn = self._connections[index]
        if not StyledMessageBox.question(
            self,
            "Delete Connection",
            f"Remove '{conn.display_name}' from saved connections?",
        ):
            return
        del self._connections[index]
        self._persist_connections()
        self._refresh_group_filter()
        self._refresh_table()
        self._select_first_row()

    def _on_save_profile(self) -> None:
        conn = self._profile_from_form()
        if not conn:
            return

        index = self._selected_index()
        if index is None:
            self._connections, _, _ = merge_connections(self._connections, [conn])
        else:
            self._connections[index] = conn
            self._connections.sort(key=lambda c: (c.group.lower(), c.display_name.lower()))

        self._persist_connections()
        self._refresh_group_filter()
        self._refresh_table()
        self._select_connection_by_key(conn.key)
        self.status_message(f"Saved '{conn.display_name}'.")

    def _select_connection_by_key(self, key: str) -> None:
        for row in range(self._table.rowCount()):
            index = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if self._connections[index].key == key:
                self._table.selectRow(row)
                return

    def status_message(self, message: str) -> None:
        self._summary.setText(message)

    def _on_test(self) -> None:
        conn = self._profile_from_form()
        if not conn:
            return
        try:
            import psycopg2
            db = psycopg2.connect(
                host=conn.host,
                port=conn.port,
                dbname=conn.database,
                user=conn.user,
                password=conn.password,
                connect_timeout=5,
                sslmode=conn.ssl_mode,
            )
            db.close()
            StyledMessageBox.information(self, "Test Connection", "Connection successful.")
        except Exception as exc:
            StyledMessageBox.critical(self, "Test Connection", f"Connection failed:\n\n{exc}")

    def _on_connect(self) -> None:
        conn = self._profile_from_form()
        if not conn:
            return

        index = self._selected_index()
        if index is None:
            self._connections, _, _ = merge_connections(self._connections, [conn])
        else:
            self._connections[index] = conn
            self._connections.sort(key=lambda c: (c.group.lower(), c.display_name.lower()))
        self._persist_connections()
        self._accepted_profile = conn
        self.accept()

    def get_profile(self) -> SavedConnection:
        if self._accepted_profile is None:
            conn = self._profile_from_form()
            if conn is None:
                raise RuntimeError("No connection profile selected.")
            return conn
        return self._accepted_profile

    def get_params(self) -> dict:
        return self.get_profile().connect_params()
