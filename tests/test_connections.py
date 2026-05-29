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


# ---------------------------------------------------------------------------
# normalise_ssl_mode
# ---------------------------------------------------------------------------

class TestNormaliseSslMode:
    """normalise_ssl_mode should accept valid modes and fall back to 'prefer'."""

    def test_all_valid_modes_accepted(self):
        from coruscant.core.connections import normalise_ssl_mode, SSL_MODES
        for mode in SSL_MODES:
            assert normalise_ssl_mode(mode) == mode

    def test_unknown_mode_falls_back_to_prefer(self):
        from coruscant.core.connections import normalise_ssl_mode
        assert normalise_ssl_mode("invalid_mode") == "prefer"

    def test_empty_string_falls_back_to_prefer(self):
        from coruscant.core.connections import normalise_ssl_mode
        assert normalise_ssl_mode("") == "prefer"

    def test_case_insensitive(self):
        from coruscant.core.connections import normalise_ssl_mode
        assert normalise_ssl_mode("REQUIRE") == "require"
        assert normalise_ssl_mode("Prefer") == "prefer"
        assert normalise_ssl_mode("VERIFY-FULL") == "verify-full"

    def test_strips_whitespace(self):
        from coruscant.core.connections import normalise_ssl_mode
        assert normalise_ssl_mode("  require  ") == "require"


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------

class TestSafeInt:
    """_safe_int returns the int value or the default on failure."""

    def test_valid_integer_string(self):
        from coruscant.core.connections import _safe_int
        assert _safe_int("5433", 5432) == 5433

    def test_actual_integer(self):
        from coruscant.core.connections import _safe_int
        assert _safe_int(9999, 5432) == 9999

    def test_none_returns_default(self):
        from coruscant.core.connections import _safe_int
        assert _safe_int(None, 5432) == 5432

    def test_empty_string_returns_default(self):
        from coruscant.core.connections import _safe_int
        assert _safe_int("", 5432) == 5432

    def test_non_numeric_string_returns_default(self):
        from coruscant.core.connections import _safe_int
        assert _safe_int("not-a-port", 5432) == 5432

    def test_float_string_returns_default(self):
        from coruscant.core.connections import _safe_int
        # int("3.14") raises ValueError — should fall back
        assert _safe_int("3.14", 5432) == 5432

    def test_zero_is_valid(self):
        from coruscant.core.connections import _safe_int
        assert _safe_int(0, 5432) == 0


# ---------------------------------------------------------------------------
# deserialise_connections — edge cases
# ---------------------------------------------------------------------------

class TestDeserialiseConnectionsEdgeCases:
    """Edge cases not covered by the round-trip test."""

    def test_none_returns_empty_list(self):
        from coruscant.core.connections import deserialise_connections
        assert deserialise_connections(None) == []

    def test_empty_list_returns_empty_list(self):
        from coruscant.core.connections import deserialise_connections
        assert deserialise_connections([]) == []

    def test_malformed_json_string_is_skipped(self):
        from coruscant.core.connections import deserialise_connections
        result = deserialise_connections(["{not valid json"])
        assert result == []

    def test_json_non_dict_root_is_skipped(self):
        """A JSON array root (not a dict) must be silently ignored."""
        import json
        from coruscant.core.connections import deserialise_connections
        result = deserialise_connections([json.dumps(["a", "b"])])
        assert result == []

    def test_entry_without_host_is_skipped(self):
        """Connections with an empty host field must be filtered out."""
        import json
        from coruscant.core.connections import deserialise_connections
        entry = json.dumps({"name": "no-host", "host": "", "database": "db", "user": "u"})
        result = deserialise_connections([entry])
        assert result == []

    def test_mixed_valid_and_invalid_entries(self):
        """Valid entries survive even when accompanied by invalid ones."""
        import json
        from coruscant.core.connections import deserialise_connections
        valid   = json.dumps({"name": "good", "host": "db.example.com",
                              "database": "mydb", "user": "alice"})
        invalid = "{broken json"
        result = deserialise_connections([valid, invalid])
        assert len(result) == 1
        assert result[0].host == "db.example.com"


# ---------------------------------------------------------------------------
# merge_connections — edge cases
# ---------------------------------------------------------------------------

class TestMergeConnectionsEdgeCases:
    """Additional edge cases for merge_connections."""

    def test_empty_incoming_leaves_existing_unchanged(self):
        from coruscant.core.connections import SavedConnection, merge_connections
        existing = [SavedConnection(name="A", host="h1", database="db", user="u")]
        merged, added, updated = merge_connections(existing, [])
        assert added == 0
        assert updated == 0
        assert len(merged) == 1

    def test_new_connection_increments_added(self):
        from coruscant.core.connections import SavedConnection, merge_connections
        existing = [SavedConnection(name="A", host="h1", database="db", user="u")]
        incoming = [SavedConnection(name="B", host="h2", database="db", user="u")]
        merged, added, updated = merge_connections(existing, incoming)
        assert added == 1
        assert updated == 0
        assert len(merged) == 2

    def test_incoming_without_host_is_skipped(self):
        from coruscant.core.connections import SavedConnection, merge_connections
        existing = [SavedConnection(name="A", host="h1", database="db", user="u")]
        # entry with no host must be silently skipped
        incoming = [SavedConnection(name="Ghost", host="", database="db", user="u")]
        merged, added, updated = merge_connections(existing, incoming)
        assert added == 0
        assert len(merged) == 1


# ---------------------------------------------------------------------------
# SavedConnection — key uniqueness / display_name
# ---------------------------------------------------------------------------

class TestSavedConnectionKey:
    def test_key_is_case_insensitive_for_host_and_user(self):
        from coruscant.core.connections import SavedConnection
        c1 = SavedConnection(name="A", host="DB.Example.COM", database="mydb", user="Admin")
        c2 = SavedConnection(name="B", host="db.example.com", database="mydb", user="admin")
        assert c1.key == c2.key

    def test_display_name_uses_name_when_set(self):
        from coruscant.core.connections import SavedConnection
        c = SavedConnection(name="Production DB", host="prod.db", database="app", user="svc")
        assert c.display_name == "Production DB"

    def test_display_name_auto_generates_when_name_blank(self):
        from coruscant.core.connections import SavedConnection
        c = SavedConnection(name="", host="prod.db", port=5432, database="app", user="svc")
        assert "svc" in c.display_name
        assert "prod.db" in c.display_name

    def test_parse_pgadmin_bad_json_raises_value_error(self):
        from coruscant.core.connections import parse_pgadmin_export_text
        import pytest
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_pgadmin_export_text("not json at all")

    def test_parse_pgadmin_missing_servers_key_raises_value_error(self):
        from coruscant.core.connections import parse_pgadmin_export_text
        import pytest, json
        with pytest.raises(ValueError, match="pgAdmin"):
            parse_pgadmin_export_text(json.dumps({"NoServersKey": {}}))
