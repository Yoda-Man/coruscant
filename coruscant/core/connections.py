"""
coruscant.core.connections
~~~~~~~~~~~~~~~~~~~~~~~~~~
Saved PostgreSQL connection profiles and pgAdmin import helpers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import json
from typing import Any


SSL_MODES = ["prefer", "disable", "allow", "require", "verify-ca", "verify-full"]


@dataclass
class SavedConnection:
    """A named PostgreSQL connection profile."""

    name: str
    host: str
    port: int = 5432
    database: str = "postgres"
    user: str = ""
    password: str = ""
    ssl_mode: str = "prefer"
    group: str = ""
    bg_color: str = ""
    fg_color: str = ""
    source: str = "manual"

    @property
    def key(self) -> str:
        """Stable identity used for de-duplicating imports."""
        return "|".join(
            [
                self.host.strip().lower(),
                str(int(self.port)),
                self.database.strip().lower(),
                self.user.strip().lower(),
            ]
        )

    @property
    def display_name(self) -> str:
        return self.name.strip() or f"{self.user}@{self.host}:{self.port}/{self.database}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["port"] = int(data.get("port") or 5432)
        data["ssl_mode"] = normalise_ssl_mode(str(data.get("ssl_mode") or "prefer"))
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SavedConnection":
        return cls(
            name=str(data.get("name") or ""),
            host=str(data.get("host") or ""),
            port=_safe_int(data.get("port"), 5432),
            database=str(data.get("database") or data.get("dbname") or "postgres"),
            user=str(data.get("user") or data.get("username") or ""),
            password=str(data.get("password") or ""),
            ssl_mode=normalise_ssl_mode(str(data.get("ssl_mode") or data.get("sslmode") or "prefer")),
            group=str(data.get("group") or ""),
            bg_color=str(data.get("bg_color") or ""),
            fg_color=str(data.get("fg_color") or ""),
            source=str(data.get("source") or "manual"),
        )

    def connect_params(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": int(self.port),
            "database": self.database,
            "user": self.user,
            "password": self.password,
            "ssl_mode": self.ssl_mode,
        }


def serialise_connections(connections: list[SavedConnection]) -> list[str]:
    """Return JSON strings suitable for QSettings."""
    packed = []
    for conn in connections:
        data = conn.to_dict()
        data["password"] = _encode_password(str(data.get("password") or ""))
        data["password_encoding"] = "base64"
        packed.append(json.dumps(data, sort_keys=True, separators=(",", ":")))
    return packed


def deserialise_connections(raw: Any) -> list[SavedConnection]:
    """Load saved connections from QSettings-compatible values."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]

    connections: list[SavedConnection] = []
    for item in raw:
        if isinstance(item, SavedConnection):
            connections.append(item)
            continue
        if isinstance(item, dict):
            data = dict(item)
            if data.get("password_encoding") == "base64":
                data["password"] = _decode_password(str(data.get("password") or ""))
            conn = SavedConnection.from_dict(data)
        else:
            try:
                data = json.loads(str(item))
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                if data.get("password_encoding") == "base64":
                    data["password"] = _decode_password(str(data.get("password") or ""))
                conn = SavedConnection.from_dict(data)
            else:
                continue
        if conn.host:
            connections.append(conn)
    return connections


def merge_connections(
    existing: list[SavedConnection],
    incoming: list[SavedConnection],
) -> tuple[list[SavedConnection], int, int]:
    """Merge incoming profiles by key, preserving existing passwords."""
    by_key = {conn.key: conn for conn in existing}
    added = 0
    updated = 0

    for conn in incoming:
        if not conn.host:
            continue
        if conn.key in by_key:
            current = by_key[conn.key]
            if current.password and not conn.password:
                conn.password = current.password
            by_key[conn.key] = conn
            updated += 1
        else:
            by_key[conn.key] = conn
            added += 1

    return sorted(by_key.values(), key=lambda c: (c.group.lower(), c.display_name.lower())), added, updated


def parse_pgadmin_export_text(text: str) -> list[SavedConnection]:
    """Parse a pgAdmin server export JSON document."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    return parse_pgadmin_export(data)


def parse_pgadmin_export(data: dict[str, Any]) -> list[SavedConnection]:
    """Extract saved connection profiles from a pgAdmin export."""
    servers = data.get("Servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise ValueError("This does not look like a pgAdmin server export.")

    connections: list[SavedConnection] = []
    for server in servers.values():
        if not isinstance(server, dict):
            continue
        host = str(server.get("Host") or "").strip()
        if not host:
            continue

        params = server.get("ConnectionParameters")
        ssl_mode = "prefer"
        if isinstance(params, dict):
            ssl_mode = str(params.get("sslmode") or ssl_mode)

        connections.append(
            SavedConnection(
                name=str(server.get("Name") or host).strip(),
                group=str(server.get("Group") or "").strip(),
                host=host,
                port=_safe_int(server.get("Port"), 5432),
                database=str(server.get("MaintenanceDB") or "postgres").strip(),
                user=str(server.get("Username") or "").strip(),
                password="",
                ssl_mode=normalise_ssl_mode(ssl_mode),
                bg_color=str(server.get("BGColor") or "").strip(),
                fg_color=str(server.get("FGColor") or "").strip(),
                source="pgadmin",
            )
        )

    return sorted(connections, key=lambda c: (c.group.lower(), c.display_name.lower()))


def normalise_ssl_mode(value: str) -> str:
    value = value.strip().lower()
    return value if value in SSL_MODES else "prefer"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _encode_password(password: str) -> str:
    return base64.b64encode(password.encode()).decode("ascii")


def _decode_password(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode("ascii")).decode()
    except Exception:
        return encoded
