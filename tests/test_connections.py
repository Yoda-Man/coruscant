"""Tests for saved connection profiles and pgAdmin import parsing."""

import json

from coruscant.core.connections import (
    SavedConnection,
    deserialise_connections,
    merge_connections,
    parse_pgadmin_export_text,
    serialise_connections,
)


def test_parse_pgadmin_export_maps_server_fields():
    raw = json.dumps(
        {
            "Servers": {
                "1": {
                    "Name": "Branch A",
                    "Group": "Branches",
                    "Host": "10.0.0.5",
                    "Port": 5433,
                    "MaintenanceDB": "postgres",
                    "Username": "analyst",
                    "BGColor": "#B6D7A8",
                    "FGColor": "#FFFFFF",
                    "ConnectionParameters": {"sslmode": "require"},
                }
            }
        }
    )

    connections = parse_pgadmin_export_text(raw)

    assert len(connections) == 1
    assert connections[0] == SavedConnection(
        name="Branch A",
        group="Branches",
        host="10.0.0.5",
        port=5433,
        database="postgres",
        user="analyst",
        password="",
        ssl_mode="require",
        bg_color="#B6D7A8",
        fg_color="#FFFFFF",
        source="pgadmin",
    )


def test_merge_connections_preserves_existing_password_on_pgadmin_update():
    existing = [
        SavedConnection(
            name="Old name",
            host="db.example.com",
            database="postgres",
            user="trust",
            password="secret",
        )
    ]
    incoming = [
        SavedConnection(
            name="New name",
            host="db.example.com",
            database="postgres",
            user="trust",
            source="pgadmin",
        )
    ]

    merged, added, updated = merge_connections(existing, incoming)

    assert added == 0
    assert updated == 1
    assert merged[0].name == "New name"
    assert merged[0].password == "secret"


def test_serialise_connections_round_trips_qsettings_values():
    original = [
        SavedConnection(
            name="Local",
            host="localhost",
            database="app",
            user="postgres",
            password="pw",
            ssl_mode="disable",
        )
    ]

    packed = serialise_connections(original)
    unpacked = deserialise_connections(packed)

    assert unpacked == original
