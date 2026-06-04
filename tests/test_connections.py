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


# ---------------------------------------------------------------------------
# SavedConnection.to_dict / from_dict / connect_params
# ---------------------------------------------------------------------------

class TestSavedConnectionToDict:
    def test_to_dict_returns_dict(self):
        from coruscant.core.connections import SavedConnection
        c = SavedConnection(name="T", host="h", database="db", user="u")
        assert isinstance(c.to_dict(), dict)

    def test_to_dict_round_trips_via_from_dict(self):
        from coruscant.core.connections import SavedConnection
        c = SavedConnection(name="Local", host="localhost", port=5433,
                            database="app", user="pguser", password="",
                            ssl_mode="require", group="G")
        d = c.to_dict()
        c2 = SavedConnection.from_dict(d)
        assert c2.host == "localhost"
        assert c2.port == 5433
        assert c2.ssl_mode == "require"
        assert c2.group == "G"

    def test_to_dict_normalises_ssl_mode(self):
        from coruscant.core.connections import SavedConnection
        c = SavedConnection(name="T", host="h", database="db", user="u",
                            ssl_mode="REQUIRE")
        # to_dict calls normalise_ssl_mode
        d = c.to_dict()
        assert d["ssl_mode"] == "require"

    def test_to_dict_port_is_int(self):
        from coruscant.core.connections import SavedConnection
        c = SavedConnection(name="T", host="h", database="db", user="u", port=5433)
        d = c.to_dict()
        assert isinstance(d["port"], int)

    def test_from_dict_accepts_dbname_key(self):
        from coruscant.core.connections import SavedConnection
        d = {"host": "h", "dbname": "mydb", "user": "u"}
        c = SavedConnection.from_dict(d)
        assert c.database == "mydb"

    def test_from_dict_accepts_username_key(self):
        from coruscant.core.connections import SavedConnection
        d = {"host": "h", "database": "db", "username": "alice"}
        c = SavedConnection.from_dict(d)
        assert c.user == "alice"

    def test_from_dict_accepts_sslmode_key(self):
        from coruscant.core.connections import SavedConnection
        d = {"host": "h", "database": "db", "user": "u", "sslmode": "require"}
        c = SavedConnection.from_dict(d)
        assert c.ssl_mode == "require"

    def test_from_dict_missing_host_gives_empty_host(self):
        from coruscant.core.connections import SavedConnection
        d = {"database": "db", "user": "u"}
        c = SavedConnection.from_dict(d)
        assert c.host == ""


class TestSavedConnectionConnectParams:
    def test_connect_params_keys(self):
        from coruscant.core.connections import SavedConnection
        c = SavedConnection(name="T", host="h", port=5432, database="db",
                            user="u", password="pw", ssl_mode="prefer")
        p = c.connect_params()
        assert set(p.keys()) == {"host", "port", "database", "user", "password", "ssl_mode"}

    def test_connect_params_values(self):
        from coruscant.core.connections import SavedConnection
        c = SavedConnection(name="T", host="myhost", port=5433, database="mydb",
                            user="myuser", password="mypw", ssl_mode="require")
        p = c.connect_params()
        assert p["host"] == "myhost"
        assert p["port"] == 5433
        assert p["ssl_mode"] == "require"


# ---------------------------------------------------------------------------
# _encode_password / _decode_password
# ---------------------------------------------------------------------------

class TestPasswordEncoding:
    def test_encode_decode_round_trip(self):
        from coruscant.core.connections import _encode_password, _decode_password
        pw = "super$ecret!123"
        assert _decode_password(_encode_password(pw)) == pw

    def test_encode_empty_string(self):
        from coruscant.core.connections import _encode_password, _decode_password
        assert _decode_password(_encode_password("")) == ""

    def test_decode_bad_data_returns_input(self):
        from coruscant.core.connections import _decode_password
        # non-base64 input → falls back to returning input unchanged
        result = _decode_password("###not base64###")
        assert isinstance(result, str)

    def test_encode_unicode_password(self):
        from coruscant.core.connections import _encode_password, _decode_password
        pw = "pässwörd"
        assert _decode_password(_encode_password(pw)) == pw


# ---------------------------------------------------------------------------
# parse_pgadmin_export (dict form)
# ---------------------------------------------------------------------------

class TestParsePageadminExport:
    def test_multiple_servers(self):
        import json
        from coruscant.core.connections import parse_pgadmin_export_text
        raw = json.dumps({
            "Servers": {
                "1": {"Name": "A", "Host": "host1", "Port": 5432,
                      "MaintenanceDB": "postgres", "Username": "u1"},
                "2": {"Name": "B", "Host": "host2", "Port": 5433,
                      "MaintenanceDB": "mydb",     "Username": "u2"},
            }
        })
        conns = parse_pgadmin_export_text(raw)
        assert len(conns) == 2
        hosts = {c.host for c in conns}
        assert hosts == {"host1", "host2"}

    def test_server_without_host_skipped(self):
        import json
        from coruscant.core.connections import parse_pgadmin_export_text
        raw = json.dumps({
            "Servers": {
                "1": {"Name": "NoHost", "Host": "", "Port": 5432,
                      "MaintenanceDB": "db", "Username": "u"},
            }
        })
        conns = parse_pgadmin_export_text(raw)
        assert conns == []

    def test_result_sorted_by_group_then_name(self):
        import json
        from coruscant.core.connections import parse_pgadmin_export_text
        raw = json.dumps({
            "Servers": {
                "1": {"Name": "Zeta", "Group": "Beta", "Host": "h1", "Port": 5432,
                      "MaintenanceDB": "db", "Username": "u"},
                "2": {"Name": "Alpha", "Group": "Alpha", "Host": "h2", "Port": 5432,
                      "MaintenanceDB": "db", "Username": "u"},
            }
        })
        conns = parse_pgadmin_export_text(raw)
        assert conns[0].group == "Alpha"

    def test_non_dict_server_entry_skipped(self):
        import json
        from coruscant.core.connections import parse_pgadmin_export_text
        raw = json.dumps({
            "Servers": {
                "1": "not a dict",
                "2": {"Name": "Good", "Host": "host", "Port": 5432,
                      "MaintenanceDB": "db", "Username": "u"},
            }
        })
        conns = parse_pgadmin_export_text(raw)
        assert len(conns) == 1
        assert conns[0].host == "host"
